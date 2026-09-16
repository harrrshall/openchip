"""Read a table printed in a request exactly as printed.

A Karnaugh map, truth table or waveform in the request is the one piece of ground truth that does
not pass through a model. Everything downstream of intake is written from the contract, so when the
grid is misread the reference model and the RTL agree with each other and are both wrong, and
simulation cannot see it. The most common misreading by far is applying the textbook MSB-first
convention instead of the axis labels that are actually printed.

This module does the mechanical part only: it reproduces the printed table and never infers,
repairs or completes anything. Declining is always the correct answer when a grid is not exactly
one of the recognised shapes, because a later step treats the result as ground truth.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

DONT_CARE = frozenset({"d", "x", "-"})
SUBSCRIPT_RE = re.compile(r"([A-Za-z_]\w*)\[(\d+)\]")
BINARY_RE = re.compile(r"^[01]+$")
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
TIME_RE = re.compile(r"^\d+\s*[munp]?s$", re.I)
CLOCKISH_RE = re.compile(r"^(clk|clock)\w*$|\w*(clk|clock)$", re.I)
CELL_ROW_RE = re.compile(r"^\s*([01]+)\s*\|(.*)\|\s*$")
OUTPUT_BULLET_RE = re.compile(r"^\s*-\s+output\s+([A-Za-z_]\w*)\s*(?:\(\s*(\d+)\s*bits?\s*\))?\s*$", re.M)


@dataclass(frozen=True)
class TableVar:
    """One column/row variable of a printed table."""

    name: str  # verbatim token from the request, e.g. "a" or "x[0]"
    port: str  # signal name, e.g. "a" or "x"
    bit: int | None  # bit index when the token was subscripted, else None


@dataclass(frozen=True)
class RequestTable:
    kind: str  # "kmap" | "truth_table" | "waveform" | "one_hot_state_table"
    inputs: tuple[TableVar, ...]  # row-axis variables first, then column-axis variables
    output: TableVar
    rows: tuple[tuple[tuple[int, ...], int], ...]  # ((value per entry of `inputs`), output)
    dont_care: int  # cells printed as don't-care or outside an explicit one-hot domain
    source: str  # the verbatim block of request text this came from
    submodule_scope: str = ""  # a child described before an explicit top-level composition


def _names_each_bit_once(table: RequestTable) -> bool:
    """An axis naming the same signal bit twice makes the grid unreadable; decline rather than guess.

    Two columns headed by the same bit assign it conflicting values, so no row is determined. The
    sign-off gate rejects such a table anyway (`verification/tablecheck.bind`); declining here keeps
    a table nobody can read out of the prompt as well.
    """
    keys = [(v.port, v.bit) for v in (*table.inputs, table.output)]
    return len(keys) == len(set(keys))


def parse_request_tables(request: str, *, include_external_mux: bool = False, include_state_graphs: bool = False) -> list[RequestTable]:
    """Every table in `request` that can be read without guessing. `[]` when none can."""
    lines = request.splitlines()
    out: list[RequestTable] = []
    i = 0
    while i < len(lines):
        for parse in (_parse_kmap, _parse_truth_table, _parse_waveform):
            table, nxt = parse(lines, i, request)
            if nxt > i:
                if table is not None and _names_each_bit_once(table):
                    prefix, suffix = "\n".join(lines[:i]), "\n".join(lines[nxt:])
                    owners = list(re.finditer(r"(?im)^\s*Module\s+([A-Za-z_]\w*)\b", prefix))
                    if owners and re.search(r"\btop[- ]level\s+module\b", suffix, re.I) and re.search(r"\bsubmodules?\b", suffix, re.I):
                        table = replace(table, submodule_scope=owners[-1].group(1))
                    out.append(table)
                elif include_external_mux and parse is _parse_kmap:
                    out.extend(_parse_mux_kmap(lines, i, request))
                i = nxt
                break
        else:
            i += 1
    if include_state_graphs:
        from .state_tables import parse_state_tables
        out.extend(parse_state_tables(request))
    return out


def _port_groups(inputs: tuple[TableVar, ...]) -> list[tuple[str, tuple[tuple[int, TableVar], ...]]]:
    """`inputs` regrouped per port, ports in order of first appearance, bits descending.

    Each member carries its index into `inputs`, because a row's values are positional.
    """
    order: list[str] = []
    for v in inputs:
        if v.port not in order:
            order.append(v.port)
    groups = []
    for port in order:
        members = [(i, v) for i, v in enumerate(inputs) if v.port == port]
        members.sort(key=lambda iv: -(iv[1].bit if iv[1].bit is not None else 0))
        groups.append((port, tuple(members)))
    return groups


def _packed(members: tuple[tuple[int, TableVar], ...], values: tuple[int, ...]) -> int | None:
    """The integer a port's bits form on a row, or None unless the table pins bits 0..n-1 once each.

    Bit k carries weight 2**k, which is how `verification/tablecheck.bind` builds the vector the
    reference is evaluated on. Rendering and checking must not be able to disagree, so the two
    decline on the same inputs: a repeated bit would silently OR two cells together here while
    `bind` rejects it outright.
    """
    bits = {v.bit for _, v in members}
    if None in bits or len(bits) != len(members) or bits != set(range(len(bits))):
        return None
    n = 0
    for i, v in members:
        n |= (values[i] & 1) << (v.bit or 0)
    return n


def _slice_name(port: str, members: tuple[tuple[int, TableVar], ...]) -> str:
    """`x[3:0]` — the bits the table actually pins, which need not be the whole port."""
    return f"{port}[{max(v.bit or 0 for _, v in members)}:0]"


def render_table(table: RequestTable) -> str:
    """A plain-text expansion of `table`, for pasting into a prompt.

    Reading the grid is only half of what a model gets wrong. Measured (ADR 0010): given rows
    labelled `x[2] x[3] x[0] x[1]`, a model transcribed every row correctly and then read that
    *listing* order as a bit ordering, packing `0 0 1 0` as `0b0010` instead of `0b0001` and
    arriving at exactly the wrong function it produced with no table at all. So bit significance is
    stated here explicitly, bits are listed descending within a port, and every row carries the
    packed integer the port actually takes.
    """
    kind = {"kmap": "Karnaugh map", "truth_table": "truth table", "waveform": "waveform table"}.get(table.kind, table.kind)
    groups = _port_groups(table.inputs)
    display = [iv for _, members in groups for iv in members]
    names = " ".join(v.name for _, v in display)
    vectors = [(port, members) for port, members in groups if members[0][1].bit is not None]
    out = [f"Truth table read mechanically from the {kind} printed in the request.",
           "Every cell was read at the position printed: the axis labels decide which variable each "
           "character of a printed code belongs to, and neither an MSB-first nor a Gray-code "
           "ordering was assumed."]
    if table.submodule_scope:
        out.insert(0, f"Scope: submodule {table.submodule_scope} only. Its local output is NOT the composed top-level output, even when the port names match. Apply the request's stated interconnections to derive the top-level behavior.")
    if vectors:
        out.append("`s[k]` below preserves the request's declared bit label. For a descending bus [H:L], "
                   "it contributes 2**(k-L) to the packed integer. A nonzero L must be recorded in "
                   "the contract as lsb; do not shift by k or wrap labels modulo the width. The request's axis labels group the bits; they are "
                   "not a significance order, and neither is the order anything is listed in below.")
    # The decimal value set first and labelled authoritative: it is the only form that needs no
    # bit-packing decision, and a wrong packing decision is the measured failure (ADR 0010).
    summary: list[str] = []
    if len(groups) == 1 and vectors:
        port, members = groups[0]
        packed_rows = [(_packed(members, values), value) for values, value in table.rows]
        if all(n is not None for n, _ in packed_rows):
            sliced = _slice_name(port, members)
            # "exactly" would be a claim about the don't-care cells, which this table does not make.
            scope = "these" if table.dont_care else "exactly these"
            for wanted in (1, 0):
                vals = sorted(n for n, value in packed_rows if value == wanted)
                summary.append(f"  {table.output.name} = {wanted} for {scope} values of {sliced}: "
                               f"{', '.join(str(n) for n in vals)}")
    if summary:
        out.append("The function, stated as the values the input takes. Use this form; it is the same "
                   "table as the rows below, already packed:")
        out.extend(summary)
        out.append("The same cells one at a time, as evidence for the lines above — bits most "
                   "significant first, each row followed by the value it packs to:")
    out.append(f"Inputs: {names}. Output: {table.output.name}.")
    for values, value in table.rows:
        assignment = " ".join(f"{v.name}={values[i]}" for i, v in display)
        packed = [(_slice_name(port, members), _packed(members, values)) for port, members in vectors]
        shown = ", ".join(f"{sliced} = {n}" for sliced, n in packed if n is not None)
        suffix = f"  [{shown}]" if shown else ""
        out.append(f"  {assignment}{suffix} -> {table.output.name}={value}")
    if table.dont_care:
        out.append(f"{table.dont_care} cell(s) were printed as don't-care and are omitted above; "
                   "any output is acceptable for those inputs.")
    return "\n".join(out)


# -- variable lists ------------------------------------------------------------------------------

def _parse_var_list(text: str) -> tuple[TableVar, ...] | None:
    """`x[0]x[1]` -> two subscripted vars; `ab` -> two single-letter vars. Mixed shapes decline."""
    s = "".join(text.split())
    if not s:
        return None
    if "[" in s or "]" in s:
        vars_: list[TableVar] = []
        pos = 0
        while pos < len(s):
            m = SUBSCRIPT_RE.match(s, pos)
            if not m:
                return None
            vars_.append(TableVar(name=m.group(0), port=m.group(1), bit=int(m.group(2))))
            pos = m.end()
        return tuple(vars_)
    if not s.isalpha():
        return None
    return tuple(TableVar(name=c, port=c, bit=None) for c in s)


def _declared_output(request: str) -> TableVar | None:
    """The request's single declared 1-bit output, from its interface bullet list."""
    declared = OUTPUT_BULLET_RE.findall(request)
    if len(declared) != 1:
        return None
    name, width = declared[0]
    if width and int(width) != 1:
        return None
    return TableVar(name=name, port=name, bit=None)


def _cell(token: str) -> int | None:
    """Cell value, or None for a don't-care. Raises ValueError on anything else."""
    t = token.strip().lower()
    if t in ("0", "1"):
        return int(t)
    if t in DONT_CARE:
        return None
    raise ValueError(t)


# -- Karnaugh map --------------------------------------------------------------------------------

def _parse_kmap(lines: list[str], i: int, request: str,
                output_override: TableVar | None = None) -> tuple[RequestTable | None, int]:
    """A column-axis line, a row-axis line carrying the column codes, then `| cell |` rows."""
    if not CELL_ROW_RE.match(lines[i]):
        return None, i
    end = i
    while end < len(lines) and CELL_ROW_RE.match(lines[end]):
        end += 1
    if i < 2:
        return None, end
    header = _split_header(lines[i - 1].split())
    if header is None:
        return None, end
    row_tokens, col_codes = header
    col_vars = _parse_var_list(" ".join(lines[i - 2].split()))
    row_vars = _parse_var_list(" ".join(row_tokens))
    if not col_vars or not row_vars or not col_codes:
        return None, end
    if {v.name for v in col_vars} & {v.name for v in row_vars}:
        return None, end
    output = output_override or _declared_output(request)
    if output is None:
        return None, end
    if len(set(col_codes)) != len(col_codes) or any(len(c) != len(col_vars) for c in col_codes):
        return None, end

    row_codes: list[str] = []
    cells: list[list[str]] = []
    for line in lines[i:end]:
        m = CELL_ROW_RE.match(line)
        assert m is not None
        row_codes.append(m.group(1))
        cells.append(m.group(2).split("|"))
    if len(set(row_codes)) != len(row_codes) or any(len(c) != len(row_vars) for c in row_codes):
        return None, end
    if any(len(row) != len(col_codes) for row in cells):
        return None, end
    if len(row_codes) * len(col_codes) != 2 ** (len(row_vars) + len(col_vars)):
        return None, end  # an incomplete map: the request does not define the whole function

    rows: list[tuple[tuple[int, ...], int]] = []
    dont_care = 0
    for row_code, row in zip(row_codes, cells):
        for col_code, token in zip(col_codes, row):
            try:
                value = _cell(token)
            except ValueError:
                return None, end
            if value is None:
                dont_care += 1
                continue
            values = tuple(int(ch) for ch in row_code) + tuple(int(ch) for ch in col_code)
            rows.append((values, value))
    source = "\n".join(lines[i - 2:end])
    return RequestTable(kind="kmap", inputs=row_vars + col_vars, output=output,
                        rows=tuple(rows), dont_care=dont_care, source=source), end


def _parse_mux_kmap(lines: list[str], i: int, request: str) -> list[RequestTable]:
    """Project an explicitly wired external mux's K-map onto its data bus.

    Selector concatenation establishes bit significance; explicit connections
    establish numeric bus indexing. Gray-code display position has no significance.
    Ambiguous or nonstandard wiring is declined rather than inferred.
    """
    outputs = OUTPUT_BULLET_RE.findall(request)
    if len(outputs) != 1 or not outputs[0][1]:
        return []
    output, width_text = outputs[0]
    width = int(width_text)
    selectors = re.findall(r"\bmux\s+takes\s+as\s+input\s*\{([^{}]+)\}", request, re.I)
    if len(selectors) != 1:
        return []
    names = [s.strip() for s in selectors[0].split(",")]
    if not names or len(set(names)) != len(names) or any(not IDENT_RE.fullmatch(s) for s in names):
        return []
    if width != 2 ** len(names) or width > 16:
        return []
    selector_label = "".join(names)
    connections = re.findall(r"\b" + re.escape(selector_label) + r"\s*=\s*([01]+)\s+(?:is\s+)?connected\s+to\s+"
                             + re.escape(output) + r"\[(\d+)\]", request, re.I)
    if not connections or any(len(code) != len(names) or int(code, 2) != int(bit)
                              for code, bit in connections):
        return []
    if not {0, 1}.issubset({int(code, 2) for code, _ in connections}):
        return []
    declared = re.findall(r"^\s*-\s+input\s+([A-Za-z_]\w*)\s*(?:\(\s*(\d+)\s*bits?\s*\))?\s*$", request, re.M)
    if not declared or any(w and int(w) != 1 for _, w in declared):
        return []
    physical = {n for n, _ in declared}
    if physical & set(names):
        return []  # selectors must belong to the external mux, not this module
    raw, _ = _parse_kmap(lines, i, request, TableVar("__mux_function", "__mux_function", None))
    if raw is None or any(v.bit is not None for v in raw.inputs):
        return []
    by_name = {v.name: j for j, v in enumerate(raw.inputs)}
    if len(by_name) != len(raw.inputs) or set(by_name) != physical | set(names):
        return []
    inputs = tuple(v for v in raw.inputs if v.name in physical)
    buckets: list[list] = [[] for _ in range(width)]
    for values, value in raw.rows:
        index = int("".join(str(values[by_name[n]]) for n in names), 2)
        buckets[index].append((tuple(values[by_name[v.name]] for v in inputs), value))
    return [RequestTable(kind="external_mux_kmap", inputs=inputs,
                         output=TableVar(f"{output}[{bit}]", output, bit), rows=tuple(rows),
                         dont_care=2 ** len(inputs) - len(rows), source=raw.source)
            for bit, rows in enumerate(buckets) if rows]


def _split_header(tokens: list[str]) -> tuple[list[str], list[str]] | None:
    """Leading variable tokens, then the column codes. A variable after a code declines."""
    var_tokens: list[str] = []
    codes: list[str] = []
    for token in tokens:
        if BINARY_RE.match(token):
            codes.append(token)
        elif codes:
            return None
        else:
            var_tokens.append(token)
    return (var_tokens, codes) if var_tokens else None


# -- truth table ---------------------------------------------------------------------------------

def _parse_truth_table(lines: list[str], i: int, request: str) -> tuple[RequestTable | None, int]:
    """A `|`-separated header of names, then `|`-separated rows of values."""
    names = _pipe_fields(lines[i])
    if names is None or len(names) < 2 or not all(IDENT_RE.match(n) for n in names):
        return None, i
    end = i + 1
    while end < len(lines):
        fields = _pipe_fields(lines[end])
        if fields is None or len(fields) != len(names):
            break
        end += 1
    if end - i - 1 < 2:
        return None, i
    return _rows_to_table("truth_table", names, [_pipe_fields(l) or [] for l in lines[i + 1:end]],
                          "\n".join(lines[i:end]), allow_dont_care=True), end


def _pipe_fields(line: str) -> list[str] | None:
    """Fields of a `a | b | c` line. None when the line has no pipes or an empty outer field."""
    if "|" not in line:
        return None
    fields = [f.strip() for f in line.split("|")]
    if any(f == "" for f in fields):
        return None  # a leading or trailing pipe: that is a Karnaugh map row, not a truth table
    return fields


# -- waveform ------------------------------------------------------------------------------------

def _parse_waveform(lines: list[str], i: int, request: str) -> tuple[RequestTable | None, int]:
    """A whitespace-separated `time ...` header, then rows beginning with a timestamp.

    Only sound for a combinational circuit, so anything hinting at state declines: a clock column,
    a cell that is not 0/1 (an `x` means the output was undefined), or one input assignment that
    maps to two different outputs.
    """
    header = lines[i].split()
    if len(header) < 3 or header[0].lower() != "time" or "|" in lines[i]:
        return None, i
    names = header[1:]
    if not all(IDENT_RE.match(n) for n in names) or any(CLOCKISH_RE.match(n) for n in names):
        return None, i
    end = i + 1
    rows: list[list[str]] = []
    while end < len(lines):
        fields = lines[end].split()
        if len(fields) != len(header) or not TIME_RE.match(fields[0]):
            break
        rows.append(fields[1:])
        end += 1
    if len(rows) < 2:
        return None, i
    if any(cell not in ("0", "1") for row in rows for cell in row):
        return None, end  # an `x` or a multi-bit value: not a combinational 0/1 table
    return _rows_to_table("waveform", names, rows, "\n".join(lines[i:end]), allow_dont_care=False), end


# -- shared row handling -------------------------------------------------------------------------

def _rows_to_table(kind: str, names: list[str], raw: list[list[str]], source: str,
                   allow_dont_care: bool) -> RequestTable | None:
    """Last column is the output. Duplicate assignments must agree; conflicts decline."""
    inputs = tuple(TableVar(name=n, port=n, bit=None) for n in names[:-1])
    output = TableVar(name=names[-1], port=names[-1], bit=None)
    seen: dict[tuple[int, ...], int] = {}
    rows: list[tuple[tuple[int, ...], int]] = []
    dont_care = 0
    for row in raw:
        try:
            values = [_cell(c) for c in row]
        except ValueError:
            return None
        if not allow_dont_care and any(v is None for v in values):
            return None
        if any(v is None for v in values[:-1]):
            return None  # a don't-care input does not name a row
        key = tuple(int(v) for v in values[:-1])  # type: ignore[arg-type]
        if values[-1] is None:
            dont_care += 1
            continue
        if key in seen:
            if seen[key] != values[-1]:
                return None  # the same inputs with two different outputs: evidence of state
            continue
        seen[key] = values[-1]
        rows.append((key, values[-1]))
    if not rows:
        return None
    return RequestTable(kind=kind, inputs=inputs, output=output, rows=tuple(rows),
                        dont_care=dont_care, source=source)

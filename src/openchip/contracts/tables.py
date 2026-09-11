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
from dataclasses import dataclass

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
    kind: str  # "kmap" | "truth_table" | "waveform"
    inputs: tuple[TableVar, ...]  # row-axis variables first, then column-axis variables
    output: TableVar
    rows: tuple[tuple[tuple[int, ...], int], ...]  # ((value per entry of `inputs`), output)
    dont_care: int  # cells dropped because they were printed as don't-care
    source: str  # the verbatim block of request text this came from


def parse_request_tables(request: str) -> list[RequestTable]:
    """Every table in `request` that can be read without guessing. `[]` when none can."""
    lines = request.splitlines()
    out: list[RequestTable] = []
    i = 0
    while i < len(lines):
        for parse in (_parse_kmap, _parse_truth_table, _parse_waveform):
            table, nxt = parse(lines, i, request)
            if nxt > i:
                if table is not None:
                    out.append(table)
                i = nxt
                break
        else:
            i += 1
    return out


def render_table(table: RequestTable) -> str:
    """A plain-text expansion of `table`, for pasting into a prompt."""
    kind = {"kmap": "Karnaugh map", "truth_table": "truth table", "waveform": "waveform table"}.get(table.kind, table.kind)
    names = " ".join(v.name for v in table.inputs)
    out = [f"Truth table read mechanically from the {kind} printed in the request.",
           "The axis labels were parsed literally, in the order printed; no MSB-first convention was applied.",
           f"Inputs, in this order: {names}. Output: {table.output.name}."]
    for values, value in table.rows:
        assignment = " ".join(f"{v.name}={n}" for v, n in zip(table.inputs, values))
        out.append(f"  {assignment} -> {table.output.name}={value}")
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

def _parse_kmap(lines: list[str], i: int, request: str) -> tuple[RequestTable | None, int]:
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
    output = _declared_output(request)
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

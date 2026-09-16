"""Select complete revisions while retaining the original request's check scope."""
from collections.abc import Callable
import re


def revision_scope(request: str, bind: Callable[[str], dict | None]) -> tuple[dict | None, bool]:
    """Return the latest complete binding, or the original with an incomplete flag."""
    parts = re.split(r"\n\nChange request \(v\d+\): ", request)
    latest = bind(parts[-1])
    return (latest, False) if latest else (bind(parts[0]), len(parts) > 1)

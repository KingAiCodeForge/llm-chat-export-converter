"""Spreadsheet-safe CSV exports for untrusted conversation and asset metadata.

CSV quoting protects row structure but does not stop spreadsheet applications
from evaluating cells beginning with formula-triggering characters. Preserve
non-string values and prefix hazardous text with a literal apostrophe.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FORMULA_LEADERS = ("=", "+", "-", "@")
HIDDEN_LEADERS = ("\t", "\r", "\n")
LEADING_IGNORABLE = " \t\r\n\ufeff"


def spreadsheet_safe_cell(value: Any) -> Any:
    """Neutralise untrusted formulas while retaining the original text."""
    if not isinstance(value, str):
        return value
    checked = value.lstrip(LEADING_IGNORABLE)
    if value.startswith(HIDDEN_LEADERS) or checked.startswith(FORMULA_LEADERS):
        return "'" + value
    return value


def spreadsheet_safe_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: spreadsheet_safe_cell(value) for key, value in row.items()}

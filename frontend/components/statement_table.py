"""Financial statement / DuPont tables — built on `st.components.v2.component()`.

Four approaches were tried before this one; see project memory for the full
account of why each earlier one was rejected:
1. Raw `st.markdown` HTML/CSS — guaranteed "no sort" (static markup) but
   needed three tries to get theming right, and even the correct one
   (`st.context.theme.type`) only updated on the *next* script rerun, not
   instantly, since colors were baked in at Python execution time and a
   manual in-app theme switch is client-side-only.
2. Native `st.dataframe` + `pandas.Styler` + `column_config.Column(pinned=
   True)` + `on_select`/`selection_mode` — live-tested and found NOT to
   actually block sorting (the header's dropdown menu still offers "Sort
   ascending/descending" regardless of `selection_mode`). Confirmed via web
   search this is a known, open Streamlit gap (streamlit/streamlit#10015).
3. `st.components.v1.declare_component` (iframe + the `streamlit:render`/
   `streamlit:componentReady` postMessage protocol, reverse-engineered from
   the installed package's compiled JS) — registered and served correctly
   (direct `curl` on the component's `/component/<name>/index.html` route
   returned 200 with the right content) but the handshake never completed
   in the real browser — `componentReady` timeout every time, cause not
   fully root-caused before moving on.
4. This version — `st.components.v2.component()`, a newer, simpler API:
   mounts directly into the app's DOM (a shadow root by default), no
   iframe, no manual postMessage handshake at all. Theming is handled by
   Streamlit itself via CSS custom properties on the `--st-<dash-case theme
   option>` convention (`--st-background-color`, `--st-text-color`,
   `--st-border-color`, `--st-font`, confirmed via the official docs at
   docs.streamlit.io/develop/concepts/custom-components/components-v2/
   theming) — plain `var(--st-background-color, ...)` in the component's
   CSS, no JS theme-detection logic needed, and it updates live since CSS
   custom properties are simply part of the DOM Streamlit already re-themes
   on every switch.
"""

from pathlib import Path

import streamlit as st

_COMPONENT_DIR = Path(__file__).resolve().parent / "statement_table_component"
_CSS = (_COMPONENT_DIR / "table.css").read_text(encoding="utf-8")
_JS = (_COMPONENT_DIR / "table.js").read_text(encoding="utf-8")

_component = st.components.v2.component(
    "statement_table",
    html='<div id="fs-root"></div>',
    css=_CSS,
    js=_JS,
)


def _format_value(value: float | None, format_type: str) -> str:
    if value is None:
        return ""
    if format_type == "percentage":
        return f"{value * 100:.1f}%"
    if format_type == "millions":
        return f"{value / 1_000_000:,.1f}"
    return f"{value:,.2f}"


def render_statement_table(table: dict, max_height: int = 600, key: str | None = None) -> None:
    """`table`: the dict shape `get_statement_table` returns — `fiscal_years`
    (list of `{"label", "date", "is_estimate"}`) and `rows` (list of
    `{"label", "is_bold", "is_subheader", "indent", "format_type",
    "tooltip", "values"}`). Value formatting happens here in Python (not in
    JS) so the component's JS stays a dumb renderer with no business logic.
    """
    columns = table["fiscal_years"]
    rows_out = [
        {
            "label": row["label"],
            "is_bold": row["is_bold"],
            "is_subheader": row["is_subheader"],
            "indent": row["indent"],
            "tooltip": row.get("tooltip"),
            "values": [_format_value(v, row["format_type"]) for v in row["values"]],
        }
        for row in table["rows"]
    ]
    _component(
        data={"mode": "statement", "columns": columns, "rows": rows_out, "max_height": max_height},
        key=key,
    )


def render_simple_table(columns: list[str], rows: list[dict], key: str | None = None) -> None:
    """A small, non-scrolling table (e.g. DuPont) — `rows`:
    `[{"label", "values": [...already-formatted strings...], "is_bold", "tooltip"}]`.
    """
    _component(data={"mode": "simple", "columns": columns, "rows": rows}, key=key)

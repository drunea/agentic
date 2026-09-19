def escape_dollars(text: str) -> str:
    """Streamlit's markdown renderer treats text between two `$` as inline
    LaTeX — financial summaries routinely have two+ dollar amounts in one
    paragraph (e.g. "$113.42 ... $174 ...") which triggers it by accident,
    garbling the text. Escaping neutralizes that without losing real markdown
    like **bold**.
    """
    return text.replace("$", "\\$")


def format_money(value: float | None) -> str | None:
    """$109,417,000,000.0 means nothing at a glance — show $109.4B instead."""
    if value is None:
        return None
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"${value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"${value / 1e6:.2f}M"
    if magnitude >= 1e3:
        return f"${value / 1e3:.2f}K"
    return f"${value:.2f}"

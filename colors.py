# colors.py
def color_for_value(v: float) -> str:
    """
    0.0–0.3  → зелёный
    0.3–0.7  → жёлтый
    0.7–1.0  → красный
    """
    if v < 0.3:
        return "\033[32m"  # green
    if v < 0.7:
        return "\033[33m"  # yellow
    return "\033[31m"  # red


RESET = "\033[0m"


def fmt_risk(v: float) -> str:
    c = color_for_value(v)
    return f"{c}{v:0.2f}{RESET}"


def fmt_conf(v: float) -> str:
    c = color_for_value(v)
    return f"{c}{v:0.2f}{RESET}"

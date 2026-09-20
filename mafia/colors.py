"""Zero-dependency ANSI color helpers for the terminal UI."""
import os


def _enable_windows_ansi():
    if os.name == "nt":
        # Enabling VT100 processing on the classic Windows console.
        os.system("")


_enable_windows_ansi()

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

COLOR_MAP = {
    "red": RED,
    "green": GREEN,
    "yellow": YELLOW,
    "blue": BLUE,
    "magenta": MAGENTA,
    "cyan": CYAN,
    "white": WHITE,
    "bold": BOLD,
    "dim": DIM,
}


def colorize(text, color=None):
    if not color:
        return text
    code = COLOR_MAP.get(color)
    if not code:
        return text
    return f"{code}{text}{RESET}"

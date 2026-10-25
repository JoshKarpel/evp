"""
Shared workloads and timing for the benchmark scripts in this directory.

Run the scripts against a release build (`just bench-build`),
since a debug build's timings say nothing about what users see.
"""

import itertools
import math
import timeit
from collections.abc import Callable, Iterator
from dataclasses import dataclass

COLUMNS = 120
ROWS = 40

WORDS = b"the quick brown fox jumps over the lazy dog".split()


def colored(words: list[bytes]) -> bytes:
    """Words each in one of seven colors, reset after each, as a syntax highlighter writes them."""
    return b" ".join(
        b"\x1b[3%dm%s\x1b[0m" % (1 + index % 7, word) for index, word in enumerate(words)
    )


PLAIN_LINE = b" ".join(WORDS * 2) + b"\r\n"
COLORED_LINE = colored(WORDS * 2) + b"\r\n"
WIDE_LINE = "日本語のテキスト".encode() * 7 + b"\r\n"
PROGRESS_BAR = b"\r[" + b"#" * 50 + b" " * 50 + b"] 50%"


def numbered_line(number: int) -> bytes:
    """A line that differs from the last, so no row of the last frame matches it by its cells."""
    return (b"line %d of the program's output " % number * 4)[: COLUMNS - 1] + b"\r\n"


def tui_screen(number: int) -> bytes:
    """
    A full-screen program's redraw on the alternate screen: every row addressed and rewritten,
    a status bar in reverse video, and a highlighted row that moves each redraw.
    """
    rows = []
    for row in range(ROWS - 1):
        style = b"\x1b[1;44m" if row == number % (ROWS - 1) else b"\x1b[0m"
        text = (b"%4d  %s" % (row, b" ".join(WORDS)))[:COLUMNS].ljust(COLUMNS)
        rows.append(b"\x1b[%d;1H%s%s" % (row + 1, style, text))
    status = (b" frame %d " % number).ljust(COLUMNS)
    return b"".join(rows) + b"\x1b[%d;1H\x1b[0;7m%s\x1b[0m" % (ROWS, status)


TUI_SETUP = b"\x1b[?1049h\x1b[?25l"


@dataclass(frozen=True, slots=True)
class Scenario:
    """A program's output: what it writes once, then what it writes before each frame."""

    setup: bytes
    steps: Callable[[], Iterator[bytes]]
    """A fresh, endless supply of what's fed before each frame."""
    max_scrollback_bytes: int = 0


def repeat(step: bytes) -> Callable[[], Iterator[bytes]]:
    return lambda: itertools.repeat(step)


def numbered(make: Callable[[int], bytes]) -> Callable[[], Iterator[bytes]]:
    return lambda: map(make, itertools.count())


SCENARIOS: dict[str, Scenario] = {
    "unchanged": Scenario(setup=PLAIN_LINE * ROWS, steps=repeat(b"")),
    "progress bar": Scenario(setup=PLAIN_LINE * ROWS, steps=repeat(PROGRESS_BAR)),
    "plain line": Scenario(setup=PLAIN_LINE * ROWS, steps=repeat(PLAIN_LINE)),
    "colored line": Scenario(setup=COLORED_LINE * ROWS, steps=repeat(COLORED_LINE)),
    "wide line": Scenario(setup=WIDE_LINE * ROWS, steps=repeat(WIDE_LINE)),
    "numbered line": Scenario(
        setup=b"".join(map(numbered_line, range(-ROWS, 0))), steps=numbered(numbered_line)
    ),
    "numbered line, 10 MB scrollback": Scenario(
        setup=b"".join(map(numbered_line, range(-10_000, 0))),
        steps=numbered(numbered_line),
        max_scrollback_bytes=10_000_000,
    ),
    "tui redraw": Scenario(setup=TUI_SETUP + tui_screen(-1), steps=numbered(tui_screen)),
}
"""
What a program writes on a 120x40 terminal. counterweight's `benchmarks snapshot` scenarios
(`unchanged` through `wide line`) scroll identical lines, which flatters finding a moved row by its
cells, so `numbered line` scrolls lines that each differ from the last.
"""


def best_of(fn: Callable[[], object], repeat: int = 5) -> float:
    """Best per-call time of `fn` in seconds, over `repeat` runs each long enough to calibrate."""
    timer = timeit.Timer(fn)
    number, _ = timer.autorange()
    return min(timer.repeat(repeat=repeat, number=number)) / number


def format_time(seconds: float) -> str:
    """A duration in the largest unit that keeps it at least 1, to three significant figures."""
    for unit, scale in (("s", 1.0), ("ms", 1e-3), ("µs", 1e-6)):
        if seconds >= scale:
            return f"{seconds / scale:.3g} {unit}"
    return f"{seconds / 1e-9:.3g} ns"


def geometric_mean(ratios: list[float]) -> float:
    return math.exp(sum(map(math.log, ratios)) / len(ratios))

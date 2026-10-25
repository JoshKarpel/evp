"""
Measure the ratios behind each claim on the docs' performance page.

Each section prints both sides of a comparison and the ratio between them,
since the ratio is what the page states. The consumer they model converts each row into runs of
text in its own style type, as counterweight's emulator does.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from evp import RenderState, Row, Style, Terminal
from workloads import (
    COLORED_LINE,
    COLUMNS,
    PLAIN_LINE,
    PROGRESS_BAR,
    ROWS,
    best_of,
    format_time,
    numbered_line,
)

# The stub's `evp.Color`, which exists only for type checkers.
type Color = int | tuple[int, int, int] | None


@dataclass(frozen=True, slots=True)
class ConsumerStyle:
    """A consumer's own style type, built from an evp `Style`."""

    foreground: Color
    background: Color
    bold: bool
    italic: bool
    underline: int

    @classmethod
    def from_style(cls, style: Style) -> ConsumerStyle:
        return cls(
            foreground=style.foreground,
            background=style.background,
            bold=style.bold,
            italic=style.italic,
            underline=style.underline,
        )


type Runs = list[tuple[str, ConsumerStyle]]


def runs(row: Row, style: Callable[[int], ConsumerStyle]) -> Runs:
    """A row as runs of text in one style each, looking each cell's style up with `style`."""
    return [
        ("".join(grapheme for grapheme, _ in run), style(index))
        for index, run in itertools.groupby(
            zip(row.graphemes, row.styles, strict=True), key=lambda cell: cell[1]
        )
    ]


@dataclass(frozen=True, slots=True)
class Reader:
    """A render state, and the consumer's styles converted so far, by index."""

    state: RenderState
    styles: list[Style]
    converted: list[ConsumerStyle]

    @classmethod
    def of(cls, terminal: Terminal) -> Reader:
        return cls(RenderState(terminal), [], [])

    def deliver(self, new_styles: Iterable[Style]) -> None:
        for style in new_styles:
            self.styles.append(style)
            self.converted.append(ConsumerStyle.from_style(style))


def compare(label: str, slow: float, fast: float) -> list[tuple[str, str]]:
    """Rows for one comparison: each side's time and the ratio of the fast to the slow."""
    return [
        (f"{label}: slow", format_time(slow)),
        (f"{label}: fast", format_time(fast)),
        (f"{label}: fast / slow", f"{fast / slow:.2g}"),
    ]


def reuse_rows(name: str, setup: bytes, steps: Iterable[bytes]) -> list[tuple[str, str]]:
    """Converting every row of every frame against reusing a row's runs while it's one `Row`."""
    sides = []
    for is_reused in (False, True):
        terminal = Terminal(COLUMNS, ROWS)
        terminal.feed(setup)
        reader = Reader.of(terminal)
        cache: dict[Row, Runs] = {}
        feed = iter(steps)

        def frame(
            terminal: Terminal = terminal,
            reader: Reader = reader,
            cache: dict[Row, Runs] = cache,
            feed: Iterable[bytes] = feed,
            is_reused: bool = is_reused,
        ) -> None:
            terminal.feed(next(iter(feed)))
            frame = reader.state.frame()
            reader.deliver(frame.new_styles)
            style = reader.converted.__getitem__
            if not is_reused:
                [runs(row, style) for row in frame.rows]
                return
            # Keeping only this frame's rows lets the cache forget rows that left the screen.
            fresh = {row: cache[row] if row in cache else runs(row, style) for row in frame.rows}
            cache.clear()
            cache.update(fresh)

        sides.append(best_of(frame))
    return compare(f"convert every row vs reuse by Row, {name}", *sides)


def convert_styles_once() -> list[tuple[str, str]]:
    """Converting each cell's style against converting each style once, looked up by index."""
    terminal = Terminal(COLUMNS, ROWS)
    terminal.feed(COLORED_LINE * ROWS)
    reader = Reader.of(terminal)
    frame = reader.state.frame()
    reader.deliver(frame.new_styles)

    def per_cell() -> None:
        styles = reader.styles
        for row in frame.rows:
            runs(row, lambda index: ConsumerStyle.from_style(styles[index]))

    def per_style() -> None:
        style = reader.converted.__getitem__
        for row in frame.rows:
            runs(row, style)

    return compare(
        "convert each cell's style vs each style once", best_of(per_cell), best_of(per_style)
    )


def scrolled_off_vs_history() -> list[tuple[str, str]]:
    """Reading the rows a line scrolled off against reading the whole scrollback after it."""
    sides = []
    for read in (RenderState.history, RenderState.scrolled_off):
        terminal = Terminal(COLUMNS, ROWS, max_scrollback_bytes=10_000_000)
        terminal.feed(b"".join(map(numbered_line, range(1_000 + ROWS))))
        state = RenderState(terminal)
        state.scrolled_off()
        lines = map(numbered_line, itertools.count())

        def step(
            terminal: Terminal = terminal,
            state: RenderState = state,
            read: Callable[[RenderState], object] = read,
            lines: Iterable[bytes] = lines,
        ) -> None:
            terminal.feed(next(iter(lines)))
            read(state)

        sides.append(best_of(step))
    return compare("history vs scrolled_off, 1,000-row scrollback", *sides)


def unchanged_frame() -> list[tuple[str, str]]:
    """Reading a frame after a line scrolled the screen against reading one after no output."""
    scrolled = Terminal(COLUMNS, ROWS)
    scrolled.feed(PLAIN_LINE * ROWS)
    scrolled_state = RenderState(scrolled)
    unchanged = Terminal(COLUMNS, ROWS)
    unchanged.feed(PLAIN_LINE * ROWS)
    unchanged_state = RenderState(unchanged)

    def scroll() -> None:
        scrolled.feed(PLAIN_LINE)
        scrolled_state.frame()

    return compare(
        "frame after a scroll vs after nothing",
        best_of(scroll),
        best_of(unchanged_state.frame),
    )


def report(rows: list[tuple[str, str]]) -> None:
    """Print `(label, value)` rows as an aligned table."""
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"{label:<{width}}  {value}", flush=True)


if __name__ == "__main__":
    report(
        reuse_rows("progress bar", PLAIN_LINE * ROWS, itertools.repeat(PROGRESS_BAR))
        + reuse_rows("scrolling", PLAIN_LINE * ROWS, itertools.repeat(PLAIN_LINE))
        + reuse_rows("colored, scrolling", COLORED_LINE * ROWS, itertools.repeat(COLORED_LINE))
        + convert_styles_once()
        + scrolled_off_vs_history()
        + unchanged_frame()
    )

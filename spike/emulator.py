"""
A prototype of counterweight's `Emulator` on evp, for the spike's measurements.

It has `Emulator`'s whole API and returns the same values, reusing counterweight's own conversions
(`cells_for`, `cell_style`, the palette rules), so counterweight's `tests/test_emulator.py` can run against it
and its time per snapshot is what `counterweight.emulator` would take on evp.
"""

from collections.abc import Callable
from types import TracebackType
from typing import Self

from counterweight.elements import Rows, StyledGrapheme
from counterweight.emulator import (
    BLACK,
    DEFAULT_PALETTE_BYTES,
    INDEXED_COLORS,
    MAX_SCROLLBACK,
    UNSTYLED,
    WHITE,
    Modes,
    MouseTracking,
    Screen,
    cell_style,
    cells_for,
    is_unchanged,
)
from counterweight.geometry import Position
from counterweight.styles._styles import AnyColor, CellStyle, Color

from evp import Frame, RenderState, Row, Style, Terminal

type Line = tuple[StyledGrapheme, ...]

# What a scrollback cell costs libghostty, generously: plain text takes about 10 bytes,
# and styles and grapheme clusters take more of a page.
SCROLLBACK_BYTES_PER_CELL = 32
# libghostty frees its scrollback a page, a few hundred KB, at a time.
SCROLLBACK_SLACK_BYTES = 2**21
# The scrollback's bytes are fixed when the terminal is made, and a wider terminal fits fewer rows in them,
# so budget for at least this many columns, for terminals that are resized wider.
SCROLLBACK_MIN_COLUMNS = 256


def scrollback_bytes(columns: int, rows: int, scrollback: int) -> int:
    """
    A byte budget for libghostty-vt 0.2.2's scrollback that holds at least `scrollback` rows,
    which an emulator trims to exactly `scrollback` itself.
    """
    if not scrollback:
        return 0
    cells = (scrollback + rows) * max(columns, SCROLLBACK_MIN_COLUMNS)
    return cells * SCROLLBACK_BYTES_PER_CELL + SCROLLBACK_SLACK_BYTES


class EvpEmulator:
    """counterweight's `Emulator`, on evp."""

    def __init__(
        self,
        columns: int,
        rows: int,
        on_reply: Callable[[bytes], None],
        foreground: Color = WHITE,
        background: Color = BLACK,
        scrollback: int = 0,
    ) -> None:
        if not 0 <= scrollback <= MAX_SCROLLBACK:
            msg = f"An emulator's scrollback must be from 0 to {MAX_SCROLLBACK:_}, but got {scrollback:_}"
            raise ValueError(msg)
        self.scrollback = scrollback
        self.terminal = Terminal(
            columns,
            rows,
            max_scrollback_bytes=scrollback_bytes(columns, rows, scrollback),
            on_write_pty=on_reply,
        )
        self.terminal.set_default_palette(DEFAULT_PALETTE_BYTES)
        self.terminal.set_default_colors(
            (foreground.red, foreground.green, foreground.blue),
            (background.red, background.green, background.blue),
        )
        self.state = RenderState(self.terminal)
        # evp's styles by index, and each as a `CellStyle` for the current default colors and palette.
        self.styles: list[Style] = []
        self.cell_styles: list[CellStyle] = []
        self.colors: tuple[tuple[int, int, int], tuple[int, int, int], bytes] | None = None
        self.foreground = foreground
        self.background = background
        self.palette = DEFAULT_PALETTE_BYTES
        # Each row's cells, by the `Row` evp handed back, which is the same object while the row is unchanged.
        self.lines: dict[Row, Line] = {}
        self.last: Screen | None = None
        # The rows that scrolled off the screen that `scrolled_off` hasn't returned yet, oldest first.
        self.pending: list[Line] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """evp frees the terminal when its last reference goes, so there's nothing to free early."""

    def feed(self, data: bytes) -> None:
        self.terminal.feed(data)

    def resize(self, columns: int, rows: int) -> None:
        self.terminal.resize(columns, rows)

    def set_default_colors(self, foreground: Color, background: Color) -> None:
        self.terminal.set_default_colors(
            (foreground.red, foreground.green, foreground.blue),
            (background.red, background.green, background.blue),
        )

    def snapshot(self) -> Screen:
        frame = self.state.frame()
        self.update_colors(frame)
        self.add_styles(frame.new_styles)
        # Set the rows that scrolled off aside now, as counterweight does, before the scrollback can free them.
        self.set_aside_scrolled_off()

        previous = self.lines
        lines: dict[Row, Line] = {}
        for row in frame.rows:
            line = previous.get(row)
            if line is None:
                line = convert_row(row, self.cell_styles)
            lines[row] = line
        self.lines = lines

        columns, row_count = frame.size
        screen = Screen(
            columns=columns,
            rows=row_count,
            lines=tuple(lines[row] for row in frame.rows),
            cursor=None
            if frame.cursor is None
            else Position(frame.cursor[0] - frame.cursor[2], frame.cursor[1]),
            modes=self.modes(),
            title=self.terminal.title(),
            foreground=self.foreground,
            background=self.background,
        )
        if self.last is not None and is_unchanged(self.last, screen):
            return self.last
        self.last = screen
        return screen

    def scrolled_off(self) -> Rows:
        self.set_aside_scrolled_off()
        scrolled_off = tuple(self.pending)
        self.pending = []
        return scrolled_off

    def history(self) -> Rows:
        if not self.scrollback:
            return ()
        self.set_aside_scrolled_off()
        history = self.state.history()
        self.add_styles(history.new_styles)
        return tuple(convert_row(row, self.cell_styles) for row in history.rows[-self.scrollback :])

    def set_aside_scrolled_off(self) -> None:
        if not self.scrollback:
            return
        scrolled_off = self.state.scrolled_off()
        self.add_styles(scrolled_off.new_styles)
        self.pending.extend(convert_row(row, self.cell_styles) for row in scrolled_off.rows)
        del self.pending[: -self.scrollback]

    def add_styles(self, styles: tuple[Style, ...]) -> None:
        """Take the styles evp delivered, and convert every style not yet converted for the current colors."""
        self.styles.extend(styles)
        cell_styles = self.cell_styles
        for style in self.styles[len(cell_styles) :]:
            # evp's first style is that of a cell with no styling, which counterweight leaves entirely unset.
            cell_styles.append(self.cell_style(style) if cell_styles else UNSTYLED)

    def update_colors(self, frame: Frame) -> None:
        """Start converting styles and rows over when the default colors or the palette changed, which they name."""
        colors = (frame.foreground, frame.background, frame.palette)
        if colors == self.colors:
            return
        self.colors = colors
        self.foreground = Color(*frame.foreground)
        self.background = Color(*frame.background)
        self.palette = frame.palette
        self.cell_styles = []
        self.lines = {}

    def cell_style(self, style: Style) -> CellStyle:
        foreground = self.color(style.foreground)
        background = self.color(style.background)
        if style.inverse:
            foreground, background = (
                self.background if background is None else background,
                self.foreground if foreground is None else foreground,
            )
        if style.invisible:
            foreground = self.background if background is None else background
        return cell_style(
            foreground,
            background,
            style.bold,
            style.faint,
            style.italic,
            style.underline != 0,
            style.strikethrough,
        )

    def color(self, color: int | tuple[int, int, int] | None) -> AnyColor | None:
        if color is None:
            return None
        if isinstance(color, tuple):
            return Color(*color)
        start = 3 * color
        entry = self.palette[start : start + 3]
        if entry == DEFAULT_PALETTE_BYTES[start : start + 3]:
            return INDEXED_COLORS[color]
        return Color(*entry)

    def modes(self) -> Modes:
        mode = self.terminal.mode
        tracking: MouseTracking
        if mode(1003):
            tracking = "any"
        elif mode(1002):
            tracking = "button"
        elif mode(1000):
            tracking = "normal"
        elif mode(9):
            tracking = "x10"
        else:
            tracking = "none"
        return Modes(
            application_cursor_keys=mode(1),
            bracketed_paste=mode(2004),
            mouse_tracking=tracking,
            sgr_mouse=mode(1006),
            focus_events=mode(1004),
            alternate_screen=mode(1049) or mode(1047) or mode(47),
        )


def convert_row(row: Row, cell_styles: list[CellStyle]) -> Line:
    """
    A row's cells in counterweight's terms. A column of width 0 follows a wide character, which drew it.

    A cell repeated in the row is the same objects wherever it recurs, which `cells_for`'s cache alone
    doesn't promise once a row holds more distinct cells than it keeps.
    """
    cells: list[StyledGrapheme] = []
    seen: dict[tuple[str, int, int], Line] = {}
    for key in zip(row.graphemes, row.widths, row.styles, strict=True):
        grapheme, width, index = key
        if not width:
            continue
        known = seen.get(key)
        if known is None:
            known = seen[key] = cells_for(grapheme, width, cell_styles[index])
        cells.extend(known)
    return tuple(cells)

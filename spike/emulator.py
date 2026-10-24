"""
A prototype of counterweight's `Emulator.snapshot` on evp, for the spike's measurements.

It returns the same `Screen` as counterweight's pyghostty-based `Emulator` for a terminal with no scrollback,
reusing counterweight's own conversions (`cells_for`, `cell_style`, the palette rules),
so its time per snapshot is what `counterweight.emulator` would take on evp.
Scrollback (`scrolled_off`, `history`) waits for evp's `scrolled_off`, which the spike doesn't build.
"""

from collections.abc import Callable

from counterweight.elements import StyledGrapheme
from counterweight.emulator import (
    BLACK,
    DEFAULT_PALETTE_BYTES,
    INDEXED_COLORS,
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


class EvpEmulator:
    """counterweight's `Emulator`, as far as `snapshot` goes, on evp."""

    def __init__(
        self,
        columns: int,
        rows: int,
        on_reply: Callable[[bytes], None],
        foreground: Color = WHITE,
        background: Color = BLACK,
    ) -> None:
        self.terminal = Terminal(columns, rows, on_write_pty=on_reply)
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

    def feed(self, data: bytes) -> None:
        self.terminal.feed(data)

    def snapshot(self) -> Screen:
        frame = self.state.frame()
        self.styles.extend(frame.new_styles)
        self.update_colors(frame)
        cell_styles = self.cell_styles
        for style in self.styles[len(cell_styles) :]:
            # evp's first style is that of a cell with no styling, which counterweight leaves entirely unset.
            cell_styles.append(self.cell_style(style) if cell_styles else UNSTYLED)

        previous = self.lines
        lines: dict[Row, Line] = {}
        for row in frame.rows:
            line = previous.get(row)
            if line is None:
                line = convert_row(row, cell_styles)
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
    """A row's cells in counterweight's terms. A column of width 0 follows a wide character, which drew it."""
    cells: list[StyledGrapheme] = []
    for grapheme, width, index in zip(row.graphemes, row.widths, row.styles, strict=True):
        if width:
            cells.extend(cells_for(grapheme, width, cell_styles[index]))
    return tuple(cells)

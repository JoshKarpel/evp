from collections.abc import Callable

type Color = int | tuple[int, int, int] | None
"""A style's color: `None` for the terminal's default, a palette index (0 to 255), or RGB."""

type RGB = tuple[int, int, int]
"""A color as its red, green and blue channels, each from 0 to 255."""

class GhosttyError(Exception):
    """An error libghostty-vt returned."""

class Style:
    """
    How a cell is drawn: its colors and attributes, as libghostty-vt's `GhosttyStyle`.

    Styles compare and hash by value. A render state delivers each distinct style once,
    and rows name styles by their index among those delivered, so convert each style once, by index.
    """

    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    @property
    def foreground(self) -> Color:
        """The text's color."""
    @property
    def background(self) -> Color:
        """The cell's background color."""
    @property
    def underline_color(self) -> Color:
        """The underline's color, `None` for the text's color."""
    @property
    def bold(self) -> bool: ...
    @property
    def italic(self) -> bool: ...
    @property
    def faint(self) -> bool: ...
    @property
    def blink(self) -> bool: ...
    @property
    def inverse(self) -> bool:
        """Whether the cell swaps its foreground and background colors."""
    @property
    def invisible(self) -> bool:
        """Whether the cell's text is drawn in its background color."""
    @property
    def strikethrough(self) -> bool: ...
    @property
    def overline(self) -> bool: ...
    @property
    def underline(self) -> int:
        """The SGR underline kind: 0 for none, then single, double, curly, dotted and dashed."""

class Terminal:
    """
    A terminal emulator, fed the bytes a program writes.

    `max_scrollback_bytes` bounds the scrollback, the rows that scrolled off the top of the screen,
    in bytes rather than rows, and is fixed when the terminal is made.
    libghostty frees the scrollback a page, a few hundred KB, at a time,
    so any limit above zero keeps at least a page or two of rows.
    Plain text takes about 10 bytes a cell; styles and grapheme clusters take more.
    The default, 0, keeps no scrollback.

    `on_write_pty` receives the bytes the terminal answers the program's queries with
    (cursor position reports, device attributes), which belong on the program's input.
    """

    def __init__(
        self,
        columns: int,
        rows: int,
        *,
        max_scrollback_bytes: int = 0,
        on_write_pty: Callable[[bytes], object] | None = None,
    ) -> None: ...
    @property
    def is_rendered(self) -> bool:
        """Whether a `RenderState` reads this terminal now."""
    def feed(self, data: bytes) -> None:
        """Feed the terminal what the program wrote, raising whatever `on_write_pty` raised."""
    def resize(self, columns: int, rows: int) -> None:
        """Resize the terminal, rewrapping its screen and scrollback, as resizing a window does."""
    def size(self) -> tuple[int, int]:
        """The terminal's `(columns, rows)`."""
    def mode(self, number: int, *, ansi: bool = False) -> bool:
        """Whether a DEC private mode (`ESC [ ? n h`) is set, or with `ansi`, an ANSI one."""
    def title(self) -> str:
        """The title the program set (with OSC 0 or 2), or an empty one."""
    def set_default_colors(self, foreground: RGB, background: RGB) -> None:
        """
        Set the colors the program's default foreground and background stand for,
        as a user choosing their terminal's theme does.
        A color the program set (with OSC 10 or 11) stays.
        """
    def set_default_palette(self, palette: bytes) -> None:
        """
        Set the 256-color palette, as 768 bytes of RGB, one triple per color.
        An entry the program changed (with OSC 4) stays.
        """

class Row:
    """
    One row of cells, as parallel sequences with one entry per column.

    A wide character's grapheme takes its first column, with width 2, and its second column
    holds an empty grapheme with width 0.
    """

    @property
    def graphemes(self) -> tuple[str, ...]:
        """Each column's grapheme cluster, a space where the column is blank."""
    @property
    def widths(self) -> bytes:
        """How many columns each grapheme cluster takes: 1, 2 if wide, or 0 after a wide one."""
    @property
    def styles(self) -> tuple[int, ...]:
        """Each column's style, as an index into the styles the render state has delivered."""

class Frame:
    """What a terminal shows at one moment, as `RenderState.frame` reads it."""

    @property
    def size(self) -> tuple[int, int]:
        """The terminal's `(columns, rows)`."""
    @property
    def rows(self) -> tuple[Row, ...]:
        """
        Every row, top to bottom.

        A row that shows what a row of the last frame showed is the same `Row` object,
        including a row a scroll moved, so derived data kept by row can be reused by identity.
        """
    @property
    def new_styles(self) -> tuple[Style, ...]:
        """The styles first used since the render state last delivered any, in index order."""
    @property
    def cursor(self) -> tuple[int, int, bool] | None:
        """
        The cursor's `(x, y, at_wide_tail)`, or `None` when it's hidden or off the screen.
        `at_wide_tail` is whether it's on the second column of a wide character.
        """
    @property
    def foreground(self) -> RGB:
        """What the program's default foreground stands for."""
    @property
    def background(self) -> RGB:
        """What the program's default background stands for."""
    @property
    def palette(self) -> bytes:
        """The 256-color palette as the program left it, as 768 bytes of RGB."""

class ScrolledOff:
    """The rows that scrolled off the screen since the last `RenderState.scrolled_off`."""

    @property
    def rows(self) -> tuple[Row, ...]:
        """The rows, oldest first, as the scrollback holds them now."""
    @property
    def new_styles(self) -> tuple[Style, ...]:
        """The styles first used since the render state last delivered any, in index order."""
    @property
    def has_gap(self) -> bool:
        """
        Whether rows may have been lost since the last call:
        more scrolled off than the scrollback holds,
        the program erased the scrollback (`ESC [ 3 J`), or a resize rewrapped it.

        An erase is missed when the last call found the scrollback empty.
        """

class History:
    """Every row the scrollback holds, as `RenderState.history` reads it."""

    @property
    def rows(self) -> tuple[Row, ...]:
        """The rows, oldest first."""
    @property
    def new_styles(self) -> tuple[Style, ...]:
        """The styles first used since the render state last delivered any, in index order."""

class RenderState:
    """
    Reads what a terminal shows, a frame at a time, and what scrolls off it.

    A terminal has at most one render state at a time, since a second would take the first's record
    of which rows changed: making a second raises `RuntimeError` until the first is gone.

    `frame`, `scrolled_off` and `history` share one table of styles.
    Each delivers the styles first used since any of them last delivered,
    so a style always arrives no later than the first row that uses it.
    """

    def __init__(self, terminal: Terminal) -> None: ...
    def frame(self) -> Frame:
        """Bring the render state up to date with the terminal and read what it shows."""
    def scrolled_off(self) -> ScrolledOff:
        """
        Read the rows that scrolled off the top of the screen since the last call,
        or since the render state was made.

        Each row is returned once, as the scrollback holds it at the call.
        A program drawing on the alternate screen scrolls nothing off.
        Call it often enough that the scrollback can't free rows before it returns them.
        """
    def history(self) -> History:
        """
        Read every row the scrollback holds now, oldest first,
        rewrapped by every resize since it scrolled off.
        It reads every row each call, so it's for now and then, not every frame.
        """

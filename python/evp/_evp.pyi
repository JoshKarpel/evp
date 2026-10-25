from collections.abc import Callable, Sequence
from enum import IntEnum, IntFlag

type Color = int | tuple[int, int, int] | None
"""A style's color: `None` for the terminal's default, a palette index (0 to 255), or RGB."""

type RGB = tuple[int, int, int]
"""A color as its red, green and blue channels, each from 0 to 255."""

class GhosttyError(Exception):
    """An error libghostty-vt returned."""

class Key(IntEnum):
    """
    A physical key, independent of the keyboard layout,
    as the W3C UI Events `KeyboardEvent.code` names it.
    """

    UNIDENTIFIED = 0
    BACKQUOTE = 1
    BACKSLASH = 2
    BRACKET_LEFT = 3
    BRACKET_RIGHT = 4
    COMMA = 5
    DIGIT_0 = 6
    DIGIT_1 = 7
    DIGIT_2 = 8
    DIGIT_3 = 9
    DIGIT_4 = 10
    DIGIT_5 = 11
    DIGIT_6 = 12
    DIGIT_7 = 13
    DIGIT_8 = 14
    DIGIT_9 = 15
    EQUAL = 16
    INTL_BACKSLASH = 17
    INTL_RO = 18
    INTL_YEN = 19
    A = 20
    B = 21
    C = 22
    D = 23
    E = 24
    F = 25
    G = 26
    H = 27
    I = 28
    J = 29
    K = 30
    L = 31
    M = 32
    N = 33
    O = 34
    P = 35
    Q = 36
    R = 37
    S = 38
    T = 39
    U = 40
    V = 41
    W = 42
    X = 43
    Y = 44
    Z = 45
    MINUS = 46
    PERIOD = 47
    QUOTE = 48
    SEMICOLON = 49
    SLASH = 50
    ALT_LEFT = 51
    ALT_RIGHT = 52
    BACKSPACE = 53
    CAPS_LOCK = 54
    CONTEXT_MENU = 55
    CONTROL_LEFT = 56
    CONTROL_RIGHT = 57
    ENTER = 58
    META_LEFT = 59
    META_RIGHT = 60
    SHIFT_LEFT = 61
    SHIFT_RIGHT = 62
    SPACE = 63
    TAB = 64
    CONVERT = 65
    KANA_MODE = 66
    NON_CONVERT = 67
    DELETE = 68
    END = 69
    HELP = 70
    HOME = 71
    INSERT = 72
    PAGE_DOWN = 73
    PAGE_UP = 74
    ARROW_DOWN = 75
    ARROW_LEFT = 76
    ARROW_RIGHT = 77
    ARROW_UP = 78
    NUM_LOCK = 79
    NUMPAD_0 = 80
    NUMPAD_1 = 81
    NUMPAD_2 = 82
    NUMPAD_3 = 83
    NUMPAD_4 = 84
    NUMPAD_5 = 85
    NUMPAD_6 = 86
    NUMPAD_7 = 87
    NUMPAD_8 = 88
    NUMPAD_9 = 89
    NUMPAD_ADD = 90
    NUMPAD_BACKSPACE = 91
    NUMPAD_CLEAR = 92
    NUMPAD_CLEAR_ENTRY = 93
    NUMPAD_COMMA = 94
    NUMPAD_DECIMAL = 95
    NUMPAD_DIVIDE = 96
    NUMPAD_ENTER = 97
    NUMPAD_EQUAL = 98
    NUMPAD_MEMORY_ADD = 99
    NUMPAD_MEMORY_CLEAR = 100
    NUMPAD_MEMORY_RECALL = 101
    NUMPAD_MEMORY_STORE = 102
    NUMPAD_MEMORY_SUBTRACT = 103
    NUMPAD_MULTIPLY = 104
    NUMPAD_PAREN_LEFT = 105
    NUMPAD_PAREN_RIGHT = 106
    NUMPAD_SUBTRACT = 107
    NUMPAD_SEPARATOR = 108
    NUMPAD_UP = 109
    NUMPAD_DOWN = 110
    NUMPAD_RIGHT = 111
    NUMPAD_LEFT = 112
    NUMPAD_BEGIN = 113
    NUMPAD_HOME = 114
    NUMPAD_END = 115
    NUMPAD_INSERT = 116
    NUMPAD_DELETE = 117
    NUMPAD_PAGE_UP = 118
    NUMPAD_PAGE_DOWN = 119
    ESCAPE = 120
    F1 = 121
    F2 = 122
    F3 = 123
    F4 = 124
    F5 = 125
    F6 = 126
    F7 = 127
    F8 = 128
    F9 = 129
    F10 = 130
    F11 = 131
    F12 = 132
    F13 = 133
    F14 = 134
    F15 = 135
    F16 = 136
    F17 = 137
    F18 = 138
    F19 = 139
    F20 = 140
    F21 = 141
    F22 = 142
    F23 = 143
    F24 = 144
    F25 = 145
    FN = 146
    FN_LOCK = 147
    PRINT_SCREEN = 148
    SCROLL_LOCK = 149
    PAUSE = 150
    BROWSER_BACK = 151
    BROWSER_FAVORITES = 152
    BROWSER_FORWARD = 153
    BROWSER_HOME = 154
    BROWSER_REFRESH = 155
    BROWSER_SEARCH = 156
    BROWSER_STOP = 157
    EJECT = 158
    LAUNCH_APP_1 = 159
    LAUNCH_APP_2 = 160
    LAUNCH_MAIL = 161
    MEDIA_PLAY_PAUSE = 162
    MEDIA_SELECT = 163
    MEDIA_STOP = 164
    MEDIA_TRACK_NEXT = 165
    MEDIA_TRACK_PREVIOUS = 166
    POWER = 167
    SLEEP = 168
    AUDIO_VOLUME_DOWN = 169
    AUDIO_VOLUME_MUTE = 170
    AUDIO_VOLUME_UP = 171
    WAKE_UP = 172
    COPY = 173
    CUT = 174
    PASTE = 175

class KeyAction(IntEnum):
    """What a key did: pressed, released, or repeated while held."""

    RELEASE = 0
    PRESS = 1
    REPEAT = 2

class Mods(IntFlag):
    """
    Modifier keys held during a key or mouse event.
    A `_SIDE` flag means the right-hand key of its modifier.
    """

    SHIFT = 1
    CTRL = 2
    ALT = 4
    SUPER = 8
    CAPS_LOCK = 16
    NUM_LOCK = 32
    SHIFT_SIDE = 64
    CTRL_SIDE = 128
    ALT_SIDE = 256
    SUPER_SIDE = 512

class OptionAsAlt(IntEnum):
    """Which of macOS's option keys a key encoder treats as alt."""

    FALSE = 0
    TRUE = 1
    LEFT = 2
    RIGHT = 3

class MouseAction(IntEnum):
    """What the mouse did: pressed a button, released one, or moved."""

    PRESS = 0
    RELEASE = 1
    MOTION = 2

class MouseButton(IntEnum):
    """
    A mouse button.
    Buttons four and five are the scroll wheel's up and down, six and seven its left and right.
    """

    UNKNOWN = 0
    LEFT = 1
    RIGHT = 2
    MIDDLE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    ELEVEN = 11

class FocusEvent(IntEnum):
    """Whether the terminal gained or lost focus."""

    GAINED = 0
    LOST = 1

class ColorScheme(IntEnum):
    """Whether the terminal's colors are light or dark."""

    LIGHT = 0
    DARK = 1

class SizeReportStyle(IntEnum):
    """
    Which size report to encode: an in-band report (mode 2048),
    or the reply to XTWINOPS 14, 16 or 18
    (the text area in pixels, a cell in pixels, the text area in cells).
    """

    MODE_2048 = 0
    CSI_14_T = 1
    CSI_16_T = 2
    CSI_18_T = 3

class ClipboardLocation(IntEnum):
    """Which clipboard a program wrote to."""

    STANDARD = 0
    SELECTION = 1
    PRIMARY = 2

class FormatterFormat(IntEnum):
    """What a formatter writes: plain text, VT sequences that redraw the screen, or HTML."""

    PLAIN = 0
    VT = 1
    HTML = 2

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

class DeviceAttributes:
    """
    What a terminal answers a program's device attributes queries with:
    the primary attributes (`ESC [ c`), the secondary (`ESC [ > c`) and the tertiary (`ESC [ = c`).

    The defaults answer as Ghostty does: a VT220-level terminal with ANSI color.
    """

    def __init__(
        self,
        *,
        conformance_level: int = 62,
        features: Sequence[int] = (22,),
        device_type: int = 1,
        firmware_version: int = 0,
        unit_id: int = 0,
    ) -> None: ...
    @property
    def conformance_level(self) -> int:
        """The primary attributes' conformance level: 62 for a VT220, up to 65 for a VT525."""
    @property
    def features(self) -> list[int]:
        """
        The primary attributes' features, at most 64, as DEC numbers them:
        22 for ANSI color, 52 for the clipboard.
        """
    @property
    def device_type(self) -> int:
        """The secondary attributes' terminal type: 1 for a VT220."""
    @property
    def firmware_version(self) -> int:
        """The secondary attributes' firmware version."""
    @property
    def unit_id(self) -> int:
        """The tertiary attributes' unit id, which the reply writes as 8 hexadecimal digits."""

class Terminal:
    """
    A terminal emulator, fed the bytes a program writes.

    `max_scrollback_bytes` bounds the scrollback, the rows that scrolled off the top of the screen,
    in bytes rather than rows, and is fixed when the terminal is made.
    libghostty frees the scrollback a page, a few hundred KB, at a time,
    so any limit above zero keeps at least a page or two of rows.
    Plain text takes about 10 bytes a cell; styles and grapheme clusters take more.
    The default, 0, keeps no scrollback.

    The callbacks run while the terminal reads what the program wrote,
    so they can't call the terminal's methods; each is passed what it needs instead.
    Whatever one raises, the call that fed the terminal raises once it's done
    (the first exception, if several do).
    A callback left unset ignores what it would have been called for,
    except that device attributes get Ghostty's.

    - `on_write_pty` receives the bytes the terminal answers the program's queries with
      (cursor position and size reports, device attributes), which belong on the program's input.
    - `on_bell` is called for each BEL.
    - `on_title_changed` receives the title the program set (with OSC 0 or 2).
    - `on_pwd_changed` receives the working directory the program reported (with OSC 7).
    - `on_clipboard_write` receives a clipboard the program wrote to (with OSC 52)
      and what it wrote, as `(mime_type, data)` pairs: none means clear it.
      Data that isn't UTF-8 arrives as an empty string.
    - `on_size` returns a cell's `(width, height)` in pixels, for the size reports XTWINOPS asks for
      (`ESC [ 14 t`, `16 t` and `18 t`),
      or `None` to send none.
    - `on_color_scheme` returns the color scheme to report when the program asks (`ESC [ ? 996 n`),
      or `None` to send none.
    - `on_device_attributes` returns the device attributes to report
      when the program asks (`ESC [ c`),
      or `None` for Ghostty's own, which `DeviceAttributes()` also gives.

    The terminal answers XTVERSION (`ESC [ > q`) with `libghostty`, sends nothing for ENQ,
    and ignores sequences it doesn't recognize, with no callback for any of them.
    """

    def __init__(
        self,
        columns: int,
        rows: int,
        *,
        max_scrollback_bytes: int = 0,
        on_write_pty: Callable[[bytes], object] | None = None,
        on_bell: Callable[[], object] | None = None,
        on_title_changed: Callable[[str], object] | None = None,
        on_pwd_changed: Callable[[str], object] | None = None,
        on_clipboard_write: Callable[[ClipboardLocation, list[tuple[str, str]]], object]
        | None = None,
        on_size: Callable[[], tuple[int, int] | None] | None = None,
        on_color_scheme: Callable[[], ColorScheme | None] | None = None,
        on_device_attributes: Callable[[], DeviceAttributes | None] | None = None,
    ) -> None: ...
    @property
    def is_rendered(self) -> bool:
        """Whether a `RenderState` reads this terminal now."""
    def feed(self, data: bytes) -> None:
        """Feed the terminal what the program wrote, raising whatever `on_write_pty` raised."""
    def resize(self, columns: int, rows: int, *, cell_width: int = 0, cell_height: int = 0) -> None:
        """
        Resize the terminal, rewrapping its screen and scrollback, as resizing a window does.
        A cell's size in pixels is for the in-band size report (mode 2048) and images.
        """
    def reset(self) -> None:
        """Reset the terminal, as a program's `ESC c` does, keeping its size."""
    def scroll_viewport(self, delta: int) -> None:
        """
        Scroll the viewport, what a `RenderState` frame shows, by `delta` rows:
        up into the scrollback for negative.
        """
    def scroll_viewport_to_top(self) -> None:
        """Scroll the viewport to the oldest row of the scrollback."""
    def scroll_viewport_to_bottom(self) -> None:
        """Scroll the viewport back to the screen the program draws on."""
    def size(self) -> tuple[int, int]:
        """The terminal's `(columns, rows)`."""
    def mode(self, number: int, *, ansi: bool = False) -> bool:
        """Whether a DEC private mode (`ESC [ ? n h`) is set, or with `ansi`, an ANSI one."""
    def set_mode(self, number: int, value: bool, *, ansi: bool = False) -> None:
        """
        Set or reset a DEC private mode, as the program's `ESC [ ? n h` or `l` does,
        or with `ansi`, an ANSI one.
        """
    def title(self) -> str:
        """The title the program set (with OSC 0 or 2), or an empty one."""
    def pwd(self) -> str:
        """The working directory the program reported (with OSC 7), or an empty one."""
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

class KeyEncoder:
    """
    Encodes key events as the bytes a program reads from its terminal,
    as the terminal's modes say: cursor and keypad application modes, modifyOtherKeys,
    and the kitty keyboard protocol's flags, read again for each event.
    """

    def __init__(
        self, terminal: Terminal, *, macos_option_as_alt: OptionAsAlt = OptionAsAlt.FALSE
    ) -> None: ...
    def encode(
        self,
        key: Key,
        *,
        action: KeyAction = KeyAction.PRESS,
        mods: Mods = Mods(0),
        consumed_mods: Mods = Mods(0),
        text: str | None = None,
        unshifted_codepoint: str | None = None,
        composing: bool = False,
    ) -> bytes:
        """
        The bytes a key event sends the program,
        which are empty for an event that sends none, like a modifier's press.

        `text` is what the key types in the keyboard's layout, before control or alt change it,
        and is what a printable key sends: `Key.A` with no text sends nothing.
        Leave it `None` for a key that types no text, such as an arrow.
        `consumed_mods` are the modifiers that went into `text`, like shift for an uppercase letter.
        `unshifted_codepoint` is the character the key types with no modifiers,
        which the kitty protocol reports.
        `composing` is whether the key is part of an input method's composition,
        which sends nothing.
        """

class MouseEncoder:
    """
    Encodes mouse events as the bytes a program reads from its terminal,
    as the terminal's mouse modes say: which events it reports (modes 9, 1000, 1002 and 1003),
    and in which format (modes 1005, 1006, 1015 and 1016).

    Positions are in pixels from the screen's top left corner,
    and a cell is `cell_width` by `cell_height` pixels.
    The defaults, 1 by 1, make positions cells: `(3, 1)` is the fourth column of the second row.
    With `track_last_cell`, motion within the cell the last motion was reported in
    isn't reported again.
    """

    def __init__(
        self,
        terminal: Terminal,
        *,
        cell_width: int = 1,
        cell_height: int = 1,
        track_last_cell: bool = False,
    ) -> None: ...
    def encode(
        self,
        action: MouseAction,
        x: float,
        y: float,
        *,
        button: MouseButton | None = None,
        mods: Mods = Mods(0),
        any_button_pressed: bool = False,
    ) -> bytes:
        """
        The bytes a mouse event sends the program, which are empty when its modes don't report it.

        `button` is the button pressed or released, or for motion, the one held, if any.
        `any_button_pressed` is whether any button is held, which decides whether motion is reported
        when the program asked for motion only while a button is held (mode 1002).
        """
    def reset(self) -> None:
        """
        Forget the cell the last motion was reported in,
        so the next motion is reported even in the same cell.
        """

class Formatter:
    """
    Writes what a terminal's active screen shows:
    as plain text, as VT sequences that draw it again, or as HTML.

    `unwrap` joins rows the terminal wrapped, and `trim` drops the spaces ending rows of plain text.
    The rest add the terminal's state to VT output, as the sequences that set it:
    the palette, modes, scrolling region, tab stops, working directory and keyboard modes,
    and the cursor's position, style, hyperlink, protection, kitty keyboard flags
    and character sets.
    """

    def __init__(
        self,
        terminal: Terminal,
        *,
        format: FormatterFormat = FormatterFormat.PLAIN,
        unwrap: bool = False,
        trim: bool = False,
        palette: bool = False,
        modes: bool = False,
        scrolling_region: bool = False,
        tabstops: bool = False,
        pwd: bool = False,
        keyboard: bool = False,
        cursor: bool = False,
        style: bool = False,
        hyperlink: bool = False,
        protection: bool = False,
        kitty_keyboard: bool = False,
        charsets: bool = False,
    ) -> None: ...
    def format(self) -> str:
        """Format what the terminal shows now."""

def encode_focus(event: FocusEvent) -> bytes:
    """
    The bytes that tell a program the terminal gained or lost focus,
    while it has focus reports (mode 1004) on.
    """

def encode_paste(text: str, *, bracketed: bool) -> bytes:
    """
    The bytes that paste `text` into a program.
    Control characters that would act on the terminal become spaces.
    With `bracketed`, for a program that has bracketed paste (mode 2004) on,
    the text is wrapped in its markers;
    without, newlines become carriage returns, as typing them would send.
    """

def is_paste_safe(text: str) -> bool:
    """
    Whether `text` is safe to paste without asking:
    it has no newline, which could run a command,
    and no bracketed paste end marker, which could end the paste early.
    """

def encode_color_scheme(scheme: ColorScheme) -> bytes:
    """
    The bytes that report the terminal's color scheme, as the reply to `ESC [ ? 996 n` does.
    Send them unasked when the scheme changes only while the program has mode 2031 on.
    """

def encode_size_report(
    style: SizeReportStyle, *, columns: int, rows: int, cell_width: int, cell_height: int
) -> bytes:
    """
    The bytes of a size report in the given style,
    for a terminal of `columns` by `rows` cells of the given pixels.
    """

def codepoint_width(codepoint: str) -> int:
    """
    How many columns a single codepoint takes as the terminal lays it out:
    0, 1, or 2 for a wide character.
    Summing these over a string is right only while grapheme clustering (mode 2027) is off.
    """

def grapheme_width(text: str) -> tuple[int, int]:
    """
    The first grapheme cluster of `text`,
    as the terminal lays it out with grapheme clustering (mode 2027) on:
    how many codepoints it takes, and how many columns. `(0, 0)` only for empty text.
    """

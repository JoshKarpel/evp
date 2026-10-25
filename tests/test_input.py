import pytest

from evp import (
    Key,
    KeyAction,
    KeyEncoder,
    Mods,
    MouseAction,
    MouseButton,
    MouseEncoder,
    OptionAsAlt,
    Terminal,
)


@pytest.mark.parametrize(
    ("key", "text", "mods", "encoded"),
    [
        (Key.ENTER, None, Mods(0), b"\r"),
        (Key.A, "a", Mods(0), b"a"),
        (Key.C, "c", Mods.CTRL, b"\x03"),
        (Key.ARROW_UP, None, Mods(0), b"\x1b[A"),
        (Key.ARROW_LEFT, None, Mods.SHIFT, b"\x1b[1;2D"),
        (Key.F5, None, Mods(0), b"\x1b[15~"),
        (Key.SHIFT_LEFT, None, Mods.SHIFT, b""),
    ],
)
def test_key_encoder_encodes_legacy_keys(
    key: Key, text: str | None, mods: Mods, encoded: bytes
) -> None:
    keys = KeyEncoder(Terminal(20, 5))
    assert keys.encode(key, text=text, mods=mods) == encoded


def test_key_encoder_sends_nothing_for_a_printable_key_without_text() -> None:
    keys = KeyEncoder(Terminal(20, 5))
    assert keys.encode(Key.A) == b""


def test_key_encoder_follows_cursor_key_application_mode() -> None:
    terminal = Terminal(20, 5)
    keys = KeyEncoder(terminal)
    terminal.feed(b"\x1b[?1h")
    assert keys.encode(Key.ARROW_UP) == b"\x1bOA"


def test_key_encoder_follows_the_kitty_keyboard_protocol() -> None:
    terminal = Terminal(20, 5)
    keys = KeyEncoder(terminal)
    terminal.feed(b"\x1b[>1u")
    assert keys.encode(Key.ESCAPE) == b"\x1b[27u"
    assert keys.encode(Key.A, text="a", mods=Mods.CTRL, unshifted_codepoint="a") == b"\x1b[97;5u"


def test_key_encoder_reports_releases_only_when_the_kitty_protocol_asks() -> None:
    terminal = Terminal(20, 5)
    keys = KeyEncoder(terminal)
    assert keys.encode(Key.A, text="a", action=KeyAction.RELEASE) == b""
    terminal.feed(b"\x1b[>3u")
    assert (
        keys.encode(Key.A, text="a", action=KeyAction.RELEASE, unshifted_codepoint="a")
        == b"\x1b[97;1:3u"
    )


def test_key_encoder_without_option_as_alt_sends_macos_option_text() -> None:
    keys = KeyEncoder(Terminal(20, 5))
    assert keys.encode(Key.F, text="ƒ", mods=Mods.ALT) == "ƒ".encode()


def test_key_encoder_with_option_as_alt_sends_escape_prefixed_keys() -> None:
    keys = KeyEncoder(Terminal(20, 5), macos_option_as_alt=OptionAsAlt.TRUE)
    assert keys.encode(Key.F, text="ƒ", mods=Mods.ALT, unshifted_codepoint="f") == b"\x1bf"


def test_key_encoder_rejects_an_unknown_key() -> None:
    keys = KeyEncoder(Terminal(20, 5))
    with pytest.raises(ValueError, match="not a valid Key"):
        keys.encode(999)  # type: ignore[arg-type]


def test_mouse_encoder_sends_nothing_until_the_program_asks() -> None:
    mouse = MouseEncoder(Terminal(20, 5))
    assert mouse.encode(MouseAction.PRESS, 3, 1, button=MouseButton.LEFT) == b""


@pytest.mark.parametrize(
    ("action", "encoded"),
    [(MouseAction.PRESS, b"\x1b[<0;4;2M"), (MouseAction.RELEASE, b"\x1b[<0;4;2m")],
)
def test_mouse_encoder_encodes_sgr_reports_in_cells(action: MouseAction, encoded: bytes) -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?1000h\x1b[?1006h")
    mouse = MouseEncoder(terminal)
    assert mouse.encode(action, 3.5, 1.2, button=MouseButton.LEFT) == encoded


def test_mouse_encoder_converts_pixels_to_cells() -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?1000h\x1b[?1006h")
    mouse = MouseEncoder(terminal, cell_width=10, cell_height=20)
    assert mouse.encode(MouseAction.PRESS, 35, 25, button=MouseButton.RIGHT) == b"\x1b[<2;4;2M"


def test_mouse_encoder_reports_held_button_motion_only_while_a_button_is_held() -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?1002h\x1b[?1006h")
    mouse = MouseEncoder(terminal)
    assert mouse.encode(MouseAction.MOTION, 5, 2) == b""
    assert (
        mouse.encode(MouseAction.MOTION, 5, 2, button=MouseButton.LEFT, any_button_pressed=True)
        == b"\x1b[<32;6;3M"
    )


def test_mouse_encoder_tracking_the_last_cell_reports_motion_once_per_cell() -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?1003h\x1b[?1006h")
    mouse = MouseEncoder(terminal, track_last_cell=True)
    assert mouse.encode(MouseAction.MOTION, 5.1, 2) == b"\x1b[<35;6;3M"
    assert mouse.encode(MouseAction.MOTION, 5.6, 2) == b""
    mouse.reset()
    assert mouse.encode(MouseAction.MOTION, 5.6, 2) == b"\x1b[<35;6;3M"


def test_mouse_encoder_rejects_an_empty_cell() -> None:
    with pytest.raises(ValueError, match="above zero"):
        MouseEncoder(Terminal(20, 5), cell_width=0)


def test_mouse_encoder_follows_modes_the_program_sets_later() -> None:
    terminal = Terminal(20, 5)
    mouse = MouseEncoder(terminal)
    assert mouse.encode(MouseAction.PRESS, 3, 1, button=MouseButton.LEFT) == b""
    terminal.feed(b"\x1b[?1000h\x1b[?1006h")
    assert mouse.encode(MouseAction.PRESS, 3, 1, button=MouseButton.LEFT) == b"\x1b[<0;4;2M"
    terminal.feed(b"\x1b[?1006l")
    assert mouse.encode(MouseAction.PRESS, 3, 1, button=MouseButton.LEFT) == b'\x1b[M $"'


@pytest.mark.parametrize(
    ("x", "y"),
    [(float("nan"), 0.0), (0.0, float("inf")), (65_536.0, 0.0), (0.0, -(2.0**31) - 256)],
)
def test_mouse_encoder_rejects_a_position_libghostty_cannot_convert(x: float, y: float) -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?1003h\x1b[?1016h")
    mouse = MouseEncoder(terminal)
    with pytest.raises(ValueError, match="must be at least"):
        mouse.encode(MouseAction.RELEASE, x, y, button=MouseButton.LEFT)


def test_mouse_encoder_reports_a_release_far_off_the_screen_in_the_edge_cell() -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?1003h\x1b[?1006h")
    mouse = MouseEncoder(terminal)
    assert mouse.encode(MouseAction.RELEASE, 65_535.0, -1e9, button=MouseButton.LEFT) == (
        b"\x1b[<0;20;1m"
    )

"""
Property tests of the encoders and the formatter: whatever a caller passes within the types,
whatever modes a program set, they answer or raise a Python exception, and what they answer
keeps the promises their docstrings make.
"""

from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evp import (
    ColorScheme,
    FocusEvent,
    Formatter,
    FormatterFormat,
    Key,
    KeyAction,
    KeyEncoder,
    Mods,
    MouseAction,
    MouseButton,
    MouseEncoder,
    OptionAsAlt,
    SizeReportStyle,
    Terminal,
    codepoint_width,
    encode_color_scheme,
    encode_focus,
    encode_paste,
    encode_size_report,
    grapheme_width,
    is_paste_safe,
)
from strategies import COLUMNS, ROWS, writes

mods = st.integers(0, max(Mods)).map(Mods)

# What sets the modes the encoders read: cursor and keypad application modes, modifyOtherKeys,
# the kitty keyboard protocol's flags, and the mouse's reporting modes and formats.
input_modes = st.lists(
    st.sampled_from(
        [
            b"\x1b[?1h",
            b"\x1b=",
            b"\x1b[>4;1m",
            b"\x1b[>4;2m",
            b"\x1b[?9h",
            b"\x1b[?1000h",
            b"\x1b[?1002h",
            b"\x1b[?1003h",
            b"\x1b[?1005h",
            b"\x1b[?1006h",
            b"\x1b[?1015h",
            b"\x1b[?1016h",
        ]
    )
    | st.integers(0, 31).map(lambda flags: b"\x1b[>%du" % flags),
    max_size=4,
).map(b"".join)


def terminal_in(modes: bytes) -> Terminal:
    terminal = Terminal(20, 5)
    terminal.feed(modes)
    return terminal


# The keys the kitty keyboard protocol still reports while an input method composes.
MODIFIER_KEYS = {
    Key.SHIFT_LEFT,
    Key.SHIFT_RIGHT,
    Key.CONTROL_LEFT,
    Key.CONTROL_RIGHT,
    Key.ALT_LEFT,
    Key.ALT_RIGHT,
    Key.META_LEFT,
    Key.META_RIGHT,
    Key.CAPS_LOCK,
    Key.NUM_LOCK,
}


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """The arguments to one `KeyEncoder.encode` call."""

    key: Key
    action: KeyAction
    mods: Mods
    consumed_mods: Mods
    text: str | None
    unshifted_codepoint: str | None
    composing: bool


key_events = st.builds(
    KeyEvent,
    key=st.sampled_from(Key),
    action=st.sampled_from(KeyAction),
    mods=mods,
    consumed_mods=mods,
    text=st.none() | st.text(max_size=3),
    unshifted_codepoint=st.none() | st.characters(),
    composing=st.booleans(),
)


@settings(max_examples=300, deadline=None)
@given(modes=input_modes, option_as_alt=st.sampled_from(OptionAsAlt), event=key_events)
def test_key_encoder_encodes_any_key_event(
    modes: bytes, option_as_alt: OptionAsAlt, event: KeyEvent
) -> None:
    encoder = KeyEncoder(terminal_in(modes), macos_option_as_alt=option_as_alt)
    encoded = encoder.encode(
        event.key,
        action=event.action,
        mods=event.mods,
        consumed_mods=event.consumed_mods,
        text=event.text,
        unshifted_codepoint=event.unshifted_codepoint,
        composing=event.composing,
    )
    if event.composing and event.key not in MODIFIER_KEYS:
        assert encoded == b""


# Mostly near the screen, where events are reported, and sometimes anywhere at all.
positions = st.floats(-50, 1_000, width=32) | st.floats(width=32)


@settings(max_examples=300, deadline=None)
@given(
    modes=input_modes,
    cell=st.tuples(st.integers(1, 40), st.integers(1, 40)),
    track_last_cell=st.booleans(),
    events=st.lists(
        st.tuples(
            st.sampled_from(MouseAction),
            positions,
            positions,
            st.none() | st.sampled_from(MouseButton),
            mods,
            st.booleans(),
        ),
        min_size=1,
        max_size=4,
    ),
)
def test_mouse_encoder_encodes_any_mouse_event(
    modes: bytes,
    cell: tuple[int, int],
    track_last_cell: bool,
    events: list[tuple[MouseAction, float, float, MouseButton | None, Mods, bool]],
) -> None:
    terminal = terminal_in(modes)
    encoder = MouseEncoder(
        terminal, cell_width=cell[0], cell_height=cell[1], track_last_cell=track_last_cell
    )
    is_reporting = any(terminal.mode(number) for number in (9, 1000, 1002, 1003))
    for action, x, y, button, held, any_button_pressed in events:
        if not (is_position(x, cell[0]) and is_position(y, cell[1])):
            with pytest.raises(ValueError, match="must be at least"):
                encoder.encode(action, x, y, button=button, mods=held)
            continue
        encoded = encoder.encode(
            action, x, y, button=button, mods=held, any_button_pressed=any_button_pressed
        )
        if not is_reporting:
            assert encoded == b""


def is_position(pixels: float, cell: int) -> bool:
    """Whether `MouseEncoder.encode` takes `pixels` as a position, for cells `cell` pixels wide."""
    return -(2**31) <= pixels < min(2**31, 65_536 * cell)


@given(text=st.text())
def test_bracketed_paste_wraps_the_text_in_markers(text: str) -> None:
    encoded = encode_paste(text, bracketed=True)
    assert encoded.startswith(b"\x1b[200~")
    assert encoded.endswith(b"\x1b[201~")


@given(text=st.text())
def test_unbracketed_paste_sends_no_newline(text: str) -> None:
    assert b"\n" not in encode_paste(text, bracketed=False)


@given(text=st.text(st.sampled_from(["a", "\n", "\x1b", "[", "2", "0", "1", "~"])))
def test_paste_is_unsafe_with_a_newline_or_an_end_marker(text: str) -> None:
    if "\n" in text or "\x1b[201~" in text:
        assert not is_paste_safe(text)


@given(codepoint=st.characters())
def test_codepoint_width_is_at_most_two_columns(codepoint: str) -> None:
    assert codepoint_width(codepoint) in {0, 1, 2}


@given(text=st.text())
def test_grapheme_width_measures_a_prefix(text: str) -> None:
    codepoints, columns = grapheme_width(text)
    assert 0 <= codepoints <= len(text)
    assert columns in {0, 1, 2}
    assert (codepoints == 0) == (text == "")


@given(event=st.sampled_from(FocusEvent), scheme=st.sampled_from(ColorScheme))
def test_focus_and_color_scheme_encode_as_sequences(event: FocusEvent, scheme: ColorScheme) -> None:
    assert encode_focus(event).startswith(b"\x1b[")
    assert encode_color_scheme(scheme).startswith(b"\x1b[")


@given(
    style=st.sampled_from(SizeReportStyle),
    columns=st.integers(0, 2**16 - 1),
    rows=st.integers(0, 2**16 - 1),
    cell_width=st.integers(0, 2**32 - 1),
    cell_height=st.integers(0, 2**32 - 1),
)
def test_size_reports_encode_any_size(
    style: SizeReportStyle, columns: int, rows: int, cell_width: int, cell_height: int
) -> None:
    encoded = encode_size_report(
        style, columns=columns, rows=rows, cell_width=cell_width, cell_height=cell_height
    )
    assert encoded.startswith(b"\x1b[")
    assert encoded.endswith(b"t")


formatter_options = st.fixed_dictionaries(
    {
        name: st.booleans()
        for name in [
            "unwrap",
            "trim",
            "palette",
            "modes",
            "scrolling_region",
            "tabstops",
            "pwd",
            "keyboard",
            "cursor",
            "style",
            "hyperlink",
            "protection",
            "kitty_keyboard",
            "charsets",
        ]
    }
)


@settings(max_examples=200, deadline=None)
@given(
    columns=COLUMNS,
    rows=ROWS,
    data=writes,
    format=st.sampled_from(FormatterFormat),
    options=formatter_options,
)
def test_formatter_formats_any_screen(
    columns: int, rows: int, data: bytes, format: FormatterFormat, options: dict[str, bool]
) -> None:
    terminal = Terminal(columns, rows)
    terminal.feed(data)
    formatter = Formatter(terminal, format=format, **options)
    assert formatter.format() == formatter.format()


@settings(max_examples=200, deadline=None)
@given(columns=COLUMNS, rows=ROWS, data=writes, options=formatter_options)
def test_formatter_vt_output_redraws_the_same_screen(
    columns: int, rows: int, data: bytes, options: dict[str, bool]
) -> None:
    terminal = Terminal(columns, rows)
    terminal.feed(data)
    redrawn = Terminal(columns, rows)
    # Unwrapped rows are joined, so they'd redraw wrapped wherever the cursor reached the margin.
    options["unwrap"] = False
    redrawn.feed(Formatter(terminal, format=FormatterFormat.VT, **options).format().encode())
    assert Formatter(redrawn, trim=True).format() == Formatter(terminal, trim=True).format()

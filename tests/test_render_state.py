import gc

import pytest

from evp import Frame, RenderState, Row, Style, Terminal


def text(row: Row) -> str:
    return "".join(row.graphemes).rstrip()


def rendered(scrollback_lines: int = 0) -> tuple[Terminal, RenderState]:
    terminal = Terminal(12, 4, scrollback_lines=scrollback_lines)
    return terminal, RenderState(terminal)


def test_a_terminal_refuses_a_second_render_state() -> None:
    terminal, _state = rendered()
    with pytest.raises(RuntimeError, match="already has a RenderState"):
        RenderState(terminal)


def test_a_terminal_takes_a_new_render_state_once_the_last_is_gone() -> None:
    terminal, state = rendered()
    del state
    gc.collect()
    assert not terminal.is_rendered
    RenderState(terminal)


def test_frame_reads_each_rows_graphemes() -> None:
    terminal, state = rendered()
    terminal.feed(b"one\r\ntwo")
    assert [text(row) for row in state.frame().rows] == ["one", "two", "", ""]


def test_frame_reads_a_wide_character_as_one_grapheme_two_columns_wide() -> None:
    terminal, state = rendered()
    terminal.feed("日x".encode())
    row = state.frame().rows[0]
    assert row.graphemes[:3] == ("日", "", "x")
    assert list(row.widths[:3]) == [2, 0, 1]


def test_frame_reads_as_much_of_a_long_grapheme_cluster_as_libghostty_keeps() -> None:
    terminal, state = rendered()
    # libghostty keeps a cluster's first 65 codepoints and drops the rest.
    terminal.feed(("e" + "́" * 200).encode())
    assert state.frame().rows[0].graphemes[0] == "e" + "́" * 64


def test_frame_delivers_each_style_once_with_the_default_first() -> None:
    terminal, state = rendered()
    terminal.feed(b"a\x1b[1;31mb\x1b[0mc\x1b[1;31md")
    first = state.frame()
    default, bold_red = first.new_styles
    assert (default.bold, default.foreground) == (False, None)
    assert (bold_red.bold, bold_red.foreground) == (True, 1)
    assert first.rows[0].styles[:4] == (0, 1, 0, 1)

    terminal.feed(b"\r\n\x1b[1;31me")
    assert state.frame().new_styles == ()


def test_frame_reads_an_erased_background_as_a_style() -> None:
    terminal, state = rendered()
    terminal.feed(b"\x1b[48;2;1;2;3m\x1b[K")
    frame = state.frame()
    styles = frame.new_styles
    erased = styles[frame.rows[0].styles[0]]
    assert erased.background == (1, 2, 3)


def unchanged(before: Frame, after: Frame) -> list[bool]:
    return [a is b for a, b in zip(before.rows, after.rows, strict=True)]


def test_frame_returns_the_same_row_for_a_row_that_did_not_change() -> None:
    terminal, state = rendered()
    terminal.feed(b"one\r\ntwo")
    before = state.frame()
    terminal.feed(b"\r\nthree")
    assert unchanged(before, state.frame()) == [True, True, False, True]


@pytest.mark.parametrize("scrollback_lines", [0, 100])
def test_frame_returns_the_same_rows_for_rows_a_scroll_moved(scrollback_lines: int) -> None:
    terminal, state = rendered(scrollback_lines=scrollback_lines)
    terminal.feed(b"a\r\n\x1b[32mb\x1b[0m\r\nc\r\nd")
    before = state.frame()
    terminal.feed(b"\r\ne")
    after = state.frame()
    assert [a is b for a, b in zip(before.rows[1:], after.rows[:3], strict=True)] == [
        True,
        True,
        True,
    ]
    assert text(after.rows[3]) == "e"


def test_frame_reads_a_row_rewritten_with_the_same_text_in_a_reused_style_id() -> None:
    terminal, state = rendered()
    terminal.feed(b"\x1b[31mdone")
    before = state.frame()
    # Erasing frees the row's only style, so the next style can take its id within the page.
    terminal.feed(b"\x1b[2K\r\x1b[32mdone")
    after = state.frame()
    assert after.rows[0] is not before.rows[0]
    green: Style = after.new_styles[-1]
    assert green.foreground == 2
    assert after.rows[0].styles[0] == len(before.new_styles)


def test_frame_reads_a_grapheme_cluster_rewritten_with_the_same_first_codepoint() -> None:
    terminal, state = rendered()
    terminal.feed("é".encode())
    state.frame()
    terminal.feed("\rè".encode())
    assert state.frame().rows[0].graphemes[0] == "è"


def test_frame_reports_the_cursor_and_hides_it_when_the_program_does() -> None:
    terminal, state = rendered()
    terminal.feed(b"ab\r\nc")
    assert state.frame().cursor == (1, 1, False)
    terminal.feed(b"\x1b[?25l")
    assert state.frame().cursor is None


def test_frame_reports_the_palette_the_program_changed() -> None:
    terminal, state = rendered()
    terminal.feed(b"\x1b]4;1;rgb:11/22/33\x07")
    assert state.frame().palette[3:6] == bytes([0x11, 0x22, 0x33])

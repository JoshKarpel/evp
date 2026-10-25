import gc

import pytest

from evp import Frame, RenderState, Row, Style, Terminal


def text(row: Row) -> str:
    return "".join(row.graphemes).rstrip()


# Enough for the scrollback to hold every row these tests write, and to free rows after many more.
SCROLLBACK_BYTES = 1_000_000


def rendered(max_scrollback_bytes: int = 0) -> tuple[Terminal, RenderState]:
    terminal = Terminal(12, 4, max_scrollback_bytes=max_scrollback_bytes)
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


def test_frame_reads_a_long_grapheme_cluster_as_libghostty_keeps_it() -> None:
    terminal, state = rendered()
    cluster = "e" + "\u0301" * 200
    terminal.feed(cluster.encode())
    read = state.frame().rows[0].graphemes[0]
    # libghostty-vt 0.2.2's Ghostty keeps all of it; newer ones keep its first 65 codepoints.
    assert len(read) >= 65
    assert cluster.startswith(read)


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
    terminal.feed(b"one\r\ntwo\r\n")
    before = state.frame()
    terminal.feed(b"three")
    assert unchanged(before, state.frame()) == [True, True, False, True]


@pytest.mark.parametrize("max_scrollback_bytes", [0, SCROLLBACK_BYTES])
def test_frame_returns_the_same_rows_for_rows_a_scroll_moved(max_scrollback_bytes: int) -> None:
    terminal, state = rendered(max_scrollback_bytes)
    terminal.feed(b"a\r\n\x1b[32mb\x1b[0m\r\nc\r\nd")
    before = state.frame()
    terminal.feed(b"\r\ne")
    after = state.frame()
    assert [a is b for a, b in zip(before.rows[1:], after.rows[:3], strict=True)] == [True] * 3
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


def history_text(rows: tuple[Row, ...]) -> list[str]:
    return [text(row) for row in rows]


def test_scrolled_off_returns_the_rows_that_scrolled_off_since_the_render_state_was_made() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne\r\nf")
    scrolled = state.scrolled_off()
    assert history_text(scrolled.rows) == ["a", "b"]
    assert not scrolled.has_gap


def test_scrolled_off_returns_each_row_once() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne")
    state.scrolled_off()
    assert state.scrolled_off().rows == ()
    terminal.feed(b"\r\nf\r\ng")
    assert history_text(state.scrolled_off().rows) == ["b", "c"]


def test_scrolled_off_delivers_the_styles_its_rows_use() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    state.frame()
    terminal.feed(b"\x1b[35ma\x1b[0m\r\nb\r\nc\r\nd\r\ne")
    scrolled = state.scrolled_off()
    (magenta,) = scrolled.new_styles
    assert magenta.foreground == 5
    assert scrolled.rows[0].styles[0] == 1


def test_scrolled_off_reports_a_gap_when_the_scrollback_freed_rows_it_had_not_returned() -> None:
    # A wide terminal fills the scrollback's pages in fewer rows.
    terminal = Terminal(1000, 4, max_scrollback_bytes=1)
    state = RenderState(terminal)
    terminal.feed((b"x" * 999 + b"\r\n") * 2_000)
    assert state.scrolled_off().has_gap


def test_scrolled_off_reports_a_gap_when_the_program_erased_the_scrollback() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne")
    state.scrolled_off()
    terminal.feed(b"\r\nf\x1b[3J")
    scrolled = state.scrolled_off()
    assert scrolled.has_gap
    assert scrolled.rows == ()


def test_scrolled_off_misses_an_erase_of_rows_scrolled_since_it_found_the_scrollback_empty() -> (
    None
):
    # A limit of libghostty-vt 0.2.2: the erase leaves no trace an anchor can see.
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne\x1b[3J")
    scrolled = state.scrolled_off()
    assert not scrolled.has_gap
    assert scrolled.rows == ()


def test_scrolled_off_reports_a_gap_after_a_resize() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne")
    terminal.resize(10, 4)
    assert state.scrolled_off().has_gap
    assert not state.scrolled_off().has_gap


def test_scrolled_off_returns_nothing_from_the_alternate_screen() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"\x1b[?1049h" + b"line\r\n" * 10)
    assert state.scrolled_off().rows == ()
    terminal.feed(b"\x1b[?1049l\x1b[4;1H\r\nafter")
    assert len(state.scrolled_off().rows) == 1


def test_history_returns_every_row_the_scrollback_holds() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne\r\nf")
    state.scrolled_off()
    assert history_text(state.history().rows) == ["a", "b"]


def test_history_reads_wide_characters_and_grapheme_clusters() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed("日e\u0301\r\n\r\n\r\n\r\n".encode())
    row = state.history().rows[0]
    assert row.graphemes[:3] == ("日", "", "e\u0301")
    assert list(row.widths[:3]) == [2, 0, 1]


def test_the_scrollback_limit_is_bytes_not_rows() -> None:
    # libghostty-rs documents the limit as lines, but a limit of 1 keeps a page of rows.
    terminal = Terminal(12, 4, max_scrollback_bytes=1)
    state = RenderState(terminal)
    terminal.feed(b"row\r\n" * 20)
    assert len(state.history().rows) > 1


def test_frame_reads_a_wide_character_cut_off_by_a_resize() -> None:
    # libghostty truncates the alternate screen rather than rewrapping it, and leaves a wide
    # character it cuts in half in place, with no second column, even once the screen widens again.
    terminal, state = rendered()
    terminal.resize(2, 1)
    terminal.feed("\x1b[?1049h日".encode())
    terminal.resize(1, 1)
    cut = state.frame().rows[0]
    assert (cut.graphemes, list(cut.widths)) == (("日",), [2])
    terminal.resize(2, 1)
    widened = state.frame().rows[0]
    assert (widened.graphemes, list(widened.widths)) == (("日", " "), [2, 1])


def test_scrolled_off_reports_a_gap_after_a_resize_on_the_alternate_screen() -> None:
    terminal, state = rendered(SCROLLBACK_BYTES)
    terminal.feed(b"a\r\nb\r\nc\r\nd\r\ne\x1b[?1049h")
    state.scrolled_off()
    terminal.resize(10, 4)
    assert state.scrolled_off().has_gap
    assert not state.scrolled_off().has_gap


def test_frame_reads_c0_controls_libghostty_prints() -> None:
    # Ghostty prints these into cells where other terminals ignore them, so a consumer sees them.
    terminal, state = rendered()
    terminal.feed(b"a\x1cb\x7f")
    assert state.frame().rows[0].graphemes[:4] == ("a", "\x1c", "b", "\x7f")

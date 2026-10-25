import pytest

from evp import ClipboardLocation, ColorScheme, DeviceAttributes, RenderState, Terminal


def test_feed_sends_replies_to_on_write_pty() -> None:
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append)
    terminal.feed(b"ab\x1b[6n")
    assert replies == [b"\x1b[1;3R"]


def test_feed_raises_what_on_write_pty_raised() -> None:
    def fail(_: bytes) -> None:
        raise ValueError("no pty")

    terminal = Terminal(20, 5, on_write_pty=fail)
    with pytest.raises(ValueError, match="no pty"):
        terminal.feed(b"\x1b[6n")


def test_feed_raises_nothing_after_a_failed_feed() -> None:
    calls: list[bytes] = []

    def fail_once(data: bytes) -> None:
        calls.append(data)
        if len(calls) == 1:
            raise ValueError("no pty")

    terminal = Terminal(20, 5, on_write_pty=fail_once)
    with pytest.raises(ValueError, match="no pty"):
        terminal.feed(b"\x1b[6n")
    terminal.feed(b"\x1b[6n")
    assert len(calls) == 2


def test_resize_changes_size() -> None:
    terminal = Terminal(20, 5)
    terminal.resize(31, 7)
    assert terminal.size() == (31, 7)


@pytest.mark.parametrize(
    ("number", "sequence"), [(1, b"\x1b[?1h"), (2004, b"\x1b[?2004h"), (1049, b"\x1b[?1049h")]
)
def test_mode_reads_dec_modes_the_program_set(number: int, sequence: bytes) -> None:
    terminal = Terminal(20, 5)
    assert not terminal.mode(number)
    terminal.feed(sequence)
    assert terminal.mode(number)


def test_title_is_what_the_program_set() -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b]2;a title\x07")
    assert terminal.title() == "a title"


def test_set_default_palette_rejects_the_wrong_length() -> None:
    with pytest.raises(ValueError, match="768 bytes"):
        Terminal(20, 5).set_default_palette(bytes(767))


def test_on_bell_is_called_for_each_bel() -> None:
    bells: list[None] = []
    terminal = Terminal(20, 5, on_bell=lambda: bells.append(None))
    terminal.feed(b"a\x07b\x07")
    assert len(bells) == 2


def test_on_title_changed_receives_the_new_title() -> None:
    titles: list[str] = []
    terminal = Terminal(20, 5, on_title_changed=titles.append)
    terminal.feed(b"\x1b]0;first\x07\x1b]2;second\x07")
    assert titles == ["first", "second"]


def test_on_pwd_changed_receives_the_reported_directory() -> None:
    directories: list[str] = []
    terminal = Terminal(20, 5, on_pwd_changed=directories.append)
    terminal.feed(b"\x1b]7;file://host/srv/project\x07")
    assert directories == ["file://host/srv/project"]
    assert terminal.pwd() == "file://host/srv/project"


def test_on_clipboard_write_receives_the_decoded_contents() -> None:
    writes: list[tuple[ClipboardLocation, list[tuple[str, str]]]] = []
    terminal = Terminal(
        20, 5, on_clipboard_write=lambda location, contents: writes.append((location, contents))
    )
    terminal.feed(b"\x1b]52;p;Y29waWVk\x07")
    assert writes == [(ClipboardLocation.PRIMARY, [("text/plain", "copied")])]


def test_a_raising_callback_raises_from_feed() -> None:
    def fail(_: str) -> None:
        raise KeyError("no title")

    terminal = Terminal(20, 5, on_title_changed=fail)
    with pytest.raises(KeyError, match="no title"):
        terminal.feed(b"\x1b]2;a title\x07")


def test_a_callback_calling_the_terminal_raises_from_feed() -> None:
    # A lambda, since `terminal.title` doesn't exist until the terminal does.
    terminal = Terminal(20, 5, on_bell=lambda: terminal.title())  # noqa: PLW0108
    with pytest.raises(RuntimeError, match="borrow"):
        terminal.feed(b"\x07")


@pytest.mark.parametrize(
    ("query", "reply"),
    [
        (b"\x1b[14t", b"\x1b[4;80;140t"),
        (b"\x1b[16t", b"\x1b[6;16;7t"),
        (b"\x1b[18t", b"\x1b[8;5;20t"),
    ],
)
def test_on_size_answers_size_reports(query: bytes, reply: bytes) -> None:
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append, on_size=lambda: (7, 16))
    terminal.feed(query)
    assert replies == [reply]


def test_on_size_returning_none_sends_no_size_report() -> None:
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append, on_size=lambda: None)
    terminal.feed(b"\x1b[18t")
    assert replies == []


@pytest.mark.parametrize(
    ("scheme", "reply"), [(ColorScheme.DARK, b"\x1b[?997;1n"), (ColorScheme.LIGHT, b"\x1b[?997;2n")]
)
def test_on_color_scheme_answers_the_color_scheme_query(scheme: ColorScheme, reply: bytes) -> None:
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append, on_color_scheme=lambda: scheme)
    terminal.feed(b"\x1b[?996n")
    assert replies == [reply]


@pytest.mark.parametrize(
    ("query", "reply"),
    [
        (b"\x1b[c", b"\x1b[?64;4;22c"),
        (b"\x1b[>c", b"\x1b[>41;7;0c"),
        (b"\x1b[=c", b"\x1bP!|0000ABCD\x1b\\"),
    ],
)
def test_on_device_attributes_answers_device_attributes_queries(query: bytes, reply: bytes) -> None:
    attributes = DeviceAttributes(
        conformance_level=64, features=[4, 22], device_type=41, firmware_version=7, unit_id=0xABCD
    )
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append, on_device_attributes=lambda: attributes)
    terminal.feed(query)
    assert replies == [reply]


@pytest.mark.parametrize("query", [b"\x1b[c", b"\x1b[>c", b"\x1b[=c"])
def test_default_device_attributes_answer_as_ghostty_does(query: bytes) -> None:
    ghosttys: list[bytes] = []
    Terminal(20, 5, on_write_pty=ghosttys.append).feed(query)
    replies: list[bytes] = []
    Terminal(20, 5, on_write_pty=replies.append, on_device_attributes=DeviceAttributes).feed(query)
    assert replies == ghosttys


def test_on_device_attributes_returning_none_sends_ghosttys_reply() -> None:
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append, on_device_attributes=lambda: None)
    terminal.feed(b"\x1b[c")
    assert replies == [b"\x1b[?62;22c"]


@pytest.mark.parametrize(
    ("query", "replies"), [(b"\x05", []), (b"\x1b[>q", [b"\x1bP>|libghostty\x1b\\"])]
)
def test_enquiry_and_xtversion_get_ghosttys_replies(query: bytes, replies: list[bytes]) -> None:
    sent: list[bytes] = []
    Terminal(20, 5, on_write_pty=sent.append).feed(query)
    assert sent == replies


def test_device_attributes_reject_more_than_64_features() -> None:
    with pytest.raises(ValueError, match="at most 64"):
        DeviceAttributes(features=range(65))


def test_set_mode_sets_a_dec_mode() -> None:
    terminal = Terminal(20, 5)
    terminal.set_mode(2004, True)
    assert terminal.mode(2004)


def test_set_mode_sets_an_ansi_mode() -> None:
    terminal = Terminal(20, 5)
    terminal.set_mode(4, True, ansi=True)
    assert terminal.mode(4, ansi=True)
    assert not terminal.mode(4)


def test_reset_clears_modes_and_title() -> None:
    terminal = Terminal(20, 5)
    terminal.feed(b"\x1b[?2004h\x1b]2;a title\x07")
    terminal.reset()
    assert not terminal.mode(2004)
    assert terminal.title() == ""


def test_resize_with_a_cell_size_reports_it_in_band() -> None:
    replies: list[bytes] = []
    terminal = Terminal(20, 5, on_write_pty=replies.append)
    terminal.feed(b"\x1b[?2048h")
    replies.clear()
    terminal.resize(30, 6, cell_width=9, cell_height=18)
    assert replies == [b"\x1b[48;6;30;108;270t"]


def viewport(terminal: Terminal, state: RenderState) -> list[str]:
    return ["".join(row.graphemes).rstrip() for row in state.frame().rows]


def test_scroll_viewport_moves_the_frame_into_the_scrollback() -> None:
    terminal = Terminal(10, 2, max_scrollback_bytes=1_000_000)
    state = RenderState(terminal)
    terminal.feed(b"1\r\n2\r\n3\r\n4")
    assert viewport(terminal, state) == ["3", "4"]

    terminal.scroll_viewport(-1)
    assert viewport(terminal, state) == ["2", "3"]

    terminal.scroll_viewport_to_top()
    assert viewport(terminal, state) == ["1", "2"]

    terminal.scroll_viewport_to_bottom()
    assert viewport(terminal, state) == ["3", "4"]

import pytest

from evp import Terminal


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

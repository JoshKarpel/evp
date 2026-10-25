from evp import Formatter, FormatterFormat, Terminal


def colored_terminal() -> Terminal:
    terminal = Terminal(12, 3)
    terminal.feed(b"plain \x1b[31mred\x1b[0m   \r\nsecond")
    return terminal


def test_formatter_writes_plain_text_by_default() -> None:
    assert Formatter(colored_terminal()).format() == "plain red   \nsecond"


def test_formatter_trim_drops_the_spaces_ending_a_row() -> None:
    assert Formatter(colored_terminal(), trim=True).format() == "plain red\nsecond"


def test_formatter_writes_an_empty_screen_as_nothing() -> None:
    assert Formatter(Terminal(12, 3)).format() == ""


def test_formatter_writes_vt_sequences_that_redraw_the_screen() -> None:
    formatted = Formatter(colored_terminal(), format=FormatterFormat.VT).format()
    assert formatted == "plain \x1b[0m\x1b[38;5;1mred\x1b[0m   \r\nsecond"


def test_formatter_writes_html() -> None:
    formatted = Formatter(colored_terminal(), format=FormatterFormat.HTML).format()
    assert formatted.startswith('<div style="font-family: monospace; white-space: pre;">plain ')
    assert 'var(--vt-palette-1);">red</div>' in formatted


def test_formatter_unwrap_joins_wrapped_rows() -> None:
    terminal = Terminal(5, 3)
    terminal.feed(b"abcdefgh")
    assert Formatter(terminal).format() == "abcde\nfgh"
    assert Formatter(terminal, unwrap=True).format() == "abcdefgh"


def test_formatter_reads_the_terminal_at_each_call() -> None:
    terminal = Terminal(12, 3)
    formatter = Formatter(terminal)
    terminal.feed(b"first")
    assert formatter.format() == "first"
    terminal.feed(b" second")
    assert formatter.format() == "first second"


def test_formatter_adds_the_cursor_position() -> None:
    terminal = Terminal(12, 3)
    terminal.feed(b"ab\r\ncd")
    formatted = Formatter(terminal, format=FormatterFormat.VT, cursor=True).format()
    assert formatted.endswith("\x1b[2;3H")


def test_formatter_trim_leaves_vt_output_alone() -> None:
    formatted = Formatter(colored_terminal(), format=FormatterFormat.VT, trim=True).format()
    assert formatted == Formatter(colored_terminal(), format=FormatterFormat.VT).format()
    assert "red\x1b[0m   \r\n" in formatted

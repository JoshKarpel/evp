"""
Property tests of `RenderState` over generated programs' output.

The oracle for a long-lived render state is a fresh one: a twin terminal is fed exactly what the
terminal is, and read by a new render state each time, which has no last frame to reuse rows from
and no style table to have kept stale. So whatever `frame` reuses (rows libghostty left clean, rows
a scroll moved, styles interned earlier) must read as the fresh one reads from scratch, and the
rows `scrolled_off` returns must be what the scrollback holds.

Rows are compared resolved: each style index replaced by the `Style` it names in the table that
render state delivered, since the two number their styles in different orders.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from evp import Formatter, Frame, History, RenderState, Row, ScrolledOff, Style, Terminal
from strategies import COLUMNS, ROWS, lines, rewrites, writes

type Resolved = tuple[tuple[str, ...], bytes, tuple[Style, ...]]

# Enough that no generated program fills it, so the scrollback never frees a row.
UNBOUNDED_SCROLLBACK_BYTES = 100_000_000


@dataclass(frozen=True, slots=True)
class Reader:
    """A render state, and the style table its reads have delivered so far."""

    state: RenderState
    styles: list[Style] = field(default_factory=list)

    def resolve(self, read: Frame | ScrolledOff | History) -> list[Resolved]:
        """A read's rows, with styles resolved, checking each row's shape on the way."""
        self.styles.extend(read.new_styles)
        return [self.resolve_row(row) for row in read.rows]

    def resolve_row(self, row: Row) -> Resolved:
        assert len(row.graphemes) == len(row.widths) == len(row.styles)
        assert all(index < len(self.styles) for index in row.styles)
        # Only a wide character's second column has width 0. libghostty doesn't promise the
        # converse: resizing the alternate screen, which it truncates rather than rewraps, can cut
        # a wide character's second column off, and widening it again leaves a blank there
        # (`test_frame_reads_a_wide_character_cut_off_by_a_resize`).
        for before, width in itertools.pairwise(b"\x01" + row.widths):
            assert width in {0, 1, 2}
            assert width != 0 or before == 2
        for grapheme, width in zip(row.graphemes, row.widths, strict=True):
            assert (width == 0) == (grapheme == "")
        return row.graphemes, row.widths, tuple(self.styles[index] for index in row.styles)


def fresh_frame(terminal: Terminal) -> tuple[Frame, list[Resolved]]:
    """What a new render state reads from `terminal`, which keeps no render state of its own."""
    reader = Reader(RenderState(terminal))
    frame = reader.state.frame()
    return frame, reader.resolve(frame)


def fresh_history(terminal: Terminal) -> list[Resolved]:
    reader = Reader(RenderState(terminal))
    return reader.resolve(reader.state.history())


class ReadTerminal(RuleBasedStateMachine):
    """
    A terminal fed a program's output, resized and scrolled, and read now and then.

    Every call that changes the terminal is made on its twin too.
    """

    terminal: Terminal
    twin: Terminal
    reader: Reader

    def __init__(self) -> None:
        super().__init__()
        self.delivered: list[Resolved] = []
        """The rows `scrolled_off` returned since the last call that reported a gap."""
        self.scrolled_off_size: tuple[int, int]
        """The size at the last `scrolled_off`, or when the render state was made."""

    @initialize(columns=COLUMNS, rows=ROWS, has_scrollback=st.booleans())
    def make(self, columns: int, rows: int, has_scrollback: bool) -> None:
        scrollback = UNBOUNDED_SCROLLBACK_BYTES if has_scrollback else 0
        self.terminal = Terminal(columns, rows, max_scrollback_bytes=scrollback)
        self.twin = Terminal(columns, rows, max_scrollback_bytes=scrollback)
        self.reader = Reader(RenderState(self.terminal))
        self.scrolled_off_size = (columns, rows)

    def both(self) -> tuple[Terminal, Terminal]:
        return self.terminal, self.twin

    @rule(data=st.one_of(writes, lines, rewrites), is_read=st.booleans())
    def feed(self, data: bytes, is_read: bool) -> None:
        """
        Feed both terminals, and maybe read a frame: rows reused from one frame to the next
        are what's at stake, and feeds that a frame doesn't follow pile up dirty rows.
        """
        for terminal in self.both():
            terminal.feed(data)
        if is_read:
            self.frame()

    @rule(columns=COLUMNS, rows=ROWS)
    def resize(self, columns: int, rows: int) -> None:
        for terminal in self.both():
            # TODO: drop this once Ghostty resizes with the viewport in the scrollback without
            # failing its page list's integrity check (`ViewportPinInsufficientRows`, a variant of
            # ghostty#12300 that libghostty-vt 0.2.2's Ghostty still has). A debug build aborts on
            # `Terminal(1, 1, max_scrollback_bytes=10**8)`, then `resize(7, 5)`,
            # `scroll_viewport_to_top()`, `feed(b"abcdefghijklmn")`, `resize(5, 1)`,
            # `scroll_viewport(1)` and `resize(3, 6)`; a release build carries on.
            terminal.scroll_viewport_to_bottom()
            terminal.resize(columns, rows)

    @rule(delta=st.one_of(st.integers(-3, 3), st.sampled_from(["top", "bottom"])))
    def scroll_viewport(self, delta: int | str) -> None:
        for terminal in self.both():
            match delta:
                case "top":
                    terminal.scroll_viewport_to_top()
                case "bottom":
                    terminal.scroll_viewport_to_bottom()
                case int():
                    terminal.scroll_viewport(delta)
                case _:
                    raise AssertionError(delta)

    @rule()
    def reset(self) -> None:
        for terminal in self.both():
            terminal.reset()

    @rule()
    def frame(self) -> None:
        frame = self.reader.state.frame()
        rows = self.reader.resolve(frame)
        fresh, fresh_rows = fresh_frame(self.twin)
        assert rows == fresh_rows
        assert frame.size == fresh.size == self.terminal.size()
        assert len(rows) == frame.size[1]
        assert (frame.cursor, frame.foreground, frame.background, frame.palette) == (
            fresh.cursor,
            fresh.foreground,
            fresh.background,
            fresh.palette,
        )

    @rule()
    def scrolled_off(self) -> None:
        scrolled = self.reader.state.scrolled_off()
        rows = self.reader.resolve(scrolled)
        if self.terminal.size() != self.scrolled_off_size:
            assert scrolled.has_gap
        self.scrolled_off_size = self.terminal.size()
        if scrolled.has_gap:
            self.delivered = []
        self.delivered.extend(rows)
        # Rows returned since the last gap are the scrollback's newest, as it now holds them.
        # `history` reads the screen showing, and the alternate screen has no scrollback.
        if self.delivered and not self.is_alternate_screen():
            assert fresh_history(self.twin)[-len(self.delivered) :] == self.delivered

    def is_alternate_screen(self) -> bool:
        return any(self.terminal.mode(number) for number in (47, 1047, 1049))

    @rule()
    def history(self) -> None:
        assert self.reader.resolve(self.reader.state.history()) == fresh_history(self.twin)


ReadTerminal.TestCase.settings = settings(max_examples=500, stateful_step_count=30, deadline=None)
test_render_state_reads_as_a_fresh_one = ReadTerminal.TestCase


def plain_text(frame: Frame) -> str:
    """
    A frame's rows as `Formatter`'s trimmed plain text writes them, but for trailing blank rows.

    The formatter writes a cell whose cluster starts with a space as a space, combining marks
    dropped, and trims trailing spaces only: libghostty-vt 0.2.2 prints the C0 controls 0x1c to
    0x1f and DEL into cells, which `str.rstrip` would count as whitespace.
    """
    rows = ["".join(" " if g.startswith(" ") else g for g in row.graphemes) for row in frame.rows]
    return "\n".join(row.rstrip(" ") for row in rows).rstrip("\n")


@settings(max_examples=200, deadline=None)
@given(columns=COLUMNS, rows=ROWS, data=writes)
def test_frame_reads_the_text_formatter_writes(columns: int, rows: int, data: bytes) -> None:
    terminal = Terminal(columns, rows)
    terminal.feed(data)
    frame, _ = fresh_frame(terminal)
    # The formatter ends with a blank row when the program wrote spaces to it, which a frame
    # can't tell from a row it never wrote to.
    assert plain_text(frame) == Formatter(terminal, trim=True).format().rstrip("\n")


@settings(max_examples=200, deadline=None)
@given(columns=COLUMNS, rows=ROWS, data=writes, cuts=st.lists(st.integers(0, 200)))
def test_feeding_in_pieces_reads_as_feeding_at_once(
    columns: int, rows: int, data: bytes, cuts: list[int]
) -> None:
    whole = Terminal(columns, rows)
    whole.feed(data)
    pieces = Terminal(columns, rows)
    bounds = sorted({0, len(data), *(cut for cut in cuts if cut < len(data))})
    for start, end in itertools.pairwise(bounds):
        pieces.feed(data[start:end])
    assert fresh_frame(pieces)[1] == fresh_frame(whole)[1]
    assert pieces.title() == whole.title()

"""
Hypothesis strategies for what a program writes to its terminal, shared by the property tests.

The bytes are mostly well-formed VT sequences, weighted toward what moves and restyles rows
(scrolling, erasing, inserting and deleting, few distinct styles), since that is what a render
state's reuse of rows has to get right, with some arbitrary bytes for the parser's sake.
Terminals are small, so a few lines scroll and a few columns wrap.
"""

from hypothesis import strategies as st

COLUMNS = st.integers(1, 12)
ROWS = st.integers(1, 6)

# Few colors, so styles repeat across rows and a page has freed style ids to reuse.
COLORS = st.sampled_from([1, 2, 4, 196])
BASIC_COLORS = st.sampled_from([1, 2, 4])


def csi(*params: int, final: str, private: str = "") -> bytes:
    return f"\x1b[{private}{';'.join(map(str, params))}{final}".encode()


sgr_params = st.one_of(
    st.sampled_from([0, 1, 2, 3, 4, 5, 7, 8, 9, 21, 22, 23, 24, 27, 29, 39, 49, 53, 55, 59]),
    BASIC_COLORS.map(lambda color: 30 + color),
    BASIC_COLORS.map(lambda color: 40 + color),
    COLORS.map(lambda color: f"38;5;{color}"),
    COLORS.map(lambda color: f"48;5;{color}"),
    COLORS.map(lambda color: f"58;5;{color}"),
    COLORS.map(lambda color: f"38;2;{color};0;9"),
    COLORS.map(lambda color: f"48;2;9;{color};0"),
    st.sampled_from(["4:2", "4:3", "4:4", "4:5"]),
)
sgr = st.lists(sgr_params, min_size=1, max_size=3).map(
    lambda params: f"\x1b[{';'.join(map(str, params))}m".encode()
)

# Wide characters, combining marks and emoji sequences make multi-column and multi-codepoint
# cells, which `read_row` reads apart from plain codepoints.
text = st.text(
    st.sampled_from(
        # A combining acute accent, a zero-width joiner, an emoji presentation selector,
        # and a soft hyphen.
        [*"abc xyz日本é🙂👩💻", "\u0301", "\u200d", "\ufe0f", "\u00ad"]
    ),
    min_size=1,
    max_size=14,
).map(str.encode)

small = st.integers(0, 8)
controls = st.sampled_from([b"\r", b"\n", b"\r\n", b"\r\n", b"\b", b"\t", b"\x07"])
cursor_moves = st.one_of(
    st.builds(lambda y, x: csi(y, x, final="H"), small, small),
    st.builds(lambda n, final: csi(n, final=final), small, st.sampled_from("ABCDEFG")),
    st.sampled_from([b"\x1b7", b"\x1b8", b"\x1bM", b"\x1bD", b"\x1bE"]),
)
edits = st.one_of(
    st.builds(lambda n, final: csi(n, final=final), st.integers(0, 3), st.sampled_from("JK")),
    st.builds(lambda n, final: csi(n, final=final), small, st.sampled_from("XP@LMSTb")),
)
regions = st.one_of(
    st.builds(lambda top, bottom: csi(top, bottom, final="r"), small, small),
    st.just(b"\x1b[r"),
    st.builds(lambda left, right: csi(left, right, final="s"), small, small),
)
modes = st.builds(
    lambda number, is_set, private: csi(number, final="h" if is_set else "l", private=private),
    st.sampled_from([1049, 47, 1047, 7, 6, 25, 69, 2027]),
    st.booleans(),
    st.just("?"),
) | st.builds(lambda is_set: csi(4, final="h" if is_set else "l"), st.booleans())
oscs = st.one_of(
    st.builds(lambda title: f"\x1b]2;{title}\x07".encode(), st.text("ab ", max_size=3)),
    st.builds(lambda color: f"\x1b]4;{color};rgb:12/34/56\x07".encode(), COLORS),
    st.builds(lambda uri: f"\x1b]8;;{uri}\x1b\\".encode(), st.sampled_from(["", "http://a"])),
)
protection = st.sampled_from([b'\x1b[1"q', b'\x1b[0"q'])
# Erasing a row and writing the same text in another style, as a progress bar redraws itself:
# the erase frees the row's styles, so a page can reuse a style id for a different style.
rewrites = st.builds(
    lambda erase, style, text: erase + style + text,
    st.sampled_from([b"\r\x1b[2K", b"\r\x1b[K", b"\x1b[2K", b"\r"]),
    sgr,
    # Few texts, so a rewrite often matches a row of the last frame cell for cell.
    st.sampled_from([b"ab", b"ab", b"x"]),
)

chunks = st.one_of(
    text,
    text,
    text,
    controls,
    controls,
    sgr,
    sgr,
    cursor_moves,
    edits,
    regions,
    modes,
    oscs,
    protection,
    rewrites,
    rewrites,
    st.binary(max_size=6),
)
writes = st.lists(chunks, max_size=12).map(b"".join)
"""What a program writes between two reads of its terminal."""

lines = st.lists(st.tuples(st.one_of(st.just(b""), sgr), text), min_size=1, max_size=8).map(
    lambda parts: b"".join(style + line + b"\r\n" for style, line in parts)
)
"""Styled lines, which scroll the screen once they reach the bottom."""

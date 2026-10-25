import pytest

from evp import (
    ColorScheme,
    FocusEvent,
    SizeReportStyle,
    codepoint_width,
    encode_color_scheme,
    encode_focus,
    encode_paste,
    encode_size_report,
    grapheme_width,
    is_paste_safe,
)


@pytest.mark.parametrize(
    ("event", "encoded"), [(FocusEvent.GAINED, b"\x1b[I"), (FocusEvent.LOST, b"\x1b[O")]
)
def test_encode_focus(event: FocusEvent, encoded: bytes) -> None:
    assert encode_focus(event) == encoded


def test_encode_paste_bracketed_wraps_the_text() -> None:
    assert encode_paste("one\ntwo", bracketed=True) == b"\x1b[200~one\ntwo\x1b[201~"


def test_encode_paste_unbracketed_sends_newlines_as_carriage_returns() -> None:
    assert encode_paste("one\ntwo", bracketed=False) == b"one\rtwo"


def test_encode_paste_replaces_control_characters() -> None:
    assert encode_paste("a\x1b[2Jb", bracketed=True) == b"\x1b[200~a [2Jb\x1b[201~"


@pytest.mark.parametrize(
    ("text", "is_safe"), [("plain text", True), ("rm -rf /\n", False), ("a\x1b[201~b", False)]
)
def test_is_paste_safe(text: str, is_safe: bool) -> None:
    assert is_paste_safe(text) is is_safe


@pytest.mark.parametrize(
    ("scheme", "encoded"),
    [(ColorScheme.DARK, b"\x1b[?997;1n"), (ColorScheme.LIGHT, b"\x1b[?997;2n")],
)
def test_encode_color_scheme(scheme: ColorScheme, encoded: bytes) -> None:
    assert encode_color_scheme(scheme) == encoded


@pytest.mark.parametrize(
    ("style", "encoded"),
    [
        (SizeReportStyle.MODE_2048, b"\x1b[48;24;80;384;640t"),
        (SizeReportStyle.CSI_14_T, b"\x1b[4;384;640t"),
        (SizeReportStyle.CSI_16_T, b"\x1b[6;16;8t"),
        (SizeReportStyle.CSI_18_T, b"\x1b[8;24;80t"),
    ],
)
def test_encode_size_report(style: SizeReportStyle, encoded: bytes) -> None:
    assert encode_size_report(style, columns=80, rows=24, cell_width=8, cell_height=16) == encoded


def test_encode_size_report_rejects_an_unknown_style() -> None:
    with pytest.raises(ValueError, match="not a valid SizeReportStyle"):
        encode_size_report(4, columns=80, rows=24, cell_width=8, cell_height=16)  # type: ignore[arg-type]


@pytest.mark.parametrize(("codepoint", "width"), [("a", 1), ("中", 2), ("́", 0)])
def test_codepoint_width(codepoint: str, width: int) -> None:
    assert codepoint_width(codepoint) == width


@pytest.mark.parametrize(
    ("text", "measured"),
    [
        ("", (0, 0)),
        ("ab", (1, 1)),
        ("éx", (2, 1)),
        ("👍🏽!", (2, 2)),
        ("👩‍💻", (3, 2)),
    ],
)
def test_grapheme_width_measures_the_first_cluster(text: str, measured: tuple[int, int]) -> None:
    assert grapheme_width(text) == measured

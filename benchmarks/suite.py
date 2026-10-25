# Every case calls its operation through one lambda, even where the lambda could be dropped,
# so each case pays the same call overhead and the cases compare on equal footing.
# ruff: noqa: PLW0108

"""
Time every operation a consumer of evp performs, and compare runs against a baseline.

Run against a release build (`just bench` builds one first):

```text
just bench                                      # every case
just bench-args="-k frame" bench                # cases whose name contains "frame"
just bench-args="--save /tmp/before.json" bench # also write the results
just bench-args="--compare /tmp/before.json" bench
```

Each case reports the best per-call time over several runs,
each run long enough for `timeit` to calibrate.
A case that reads a frame feeds the next piece of its scenario's output first, as a consumer
does between frames, and the matching `feed` case times that feed alone.
A comparison against results saved earlier also absorbs whatever else the machine was doing in
between; `ab.py` alternates two builds instead.
"""

import argparse
import itertools
import json
from collections.abc import Callable
from pathlib import Path

from evp import (
    Formatter,
    FormatterFormat,
    Key,
    KeyEncoder,
    Mods,
    MouseAction,
    MouseButton,
    MouseEncoder,
    RenderState,
    Terminal,
    codepoint_width,
    encode_paste,
    grapheme_width,
    is_paste_safe,
)
from workloads import (
    COLORED_LINE,
    COLUMNS,
    PLAIN_LINE,
    ROWS,
    SCENARIOS,
    Scenario,
    best_of,
    format_time,
    geometric_mean,
    numbered_line,
)

type Case = tuple[str, Callable[[], object]]


def fed(scenario: Scenario) -> tuple[Terminal, Callable[[], None]]:
    """A terminal after the scenario's setup, and a function that feeds it the next step."""
    terminal = Terminal(COLUMNS, ROWS, max_scrollback_bytes=scenario.max_scrollback_bytes)
    terminal.feed(scenario.setup)
    steps = scenario.steps()
    return terminal, lambda: terminal.feed(next(steps))


def terminal_cases() -> list[Case]:
    """Making terminals and render states, and the terminal's own calls."""
    terminal = Terminal(COLUMNS, ROWS)
    terminal.feed(PLAIN_LINE * ROWS)
    sizes = itertools.cycle([(COLUMNS - 20, ROWS), (COLUMNS, ROWS)])

    def resize() -> None:
        terminal.resize(*next(sizes))

    return [
        ("terminal: Terminal(120, 40)", lambda: Terminal(COLUMNS, ROWS)),
        (
            "terminal: Terminal(120, 40) + RenderState",
            lambda: RenderState(Terminal(COLUMNS, ROWS)),
        ),
        ("terminal: resize, rewrapping 40 rows", resize),
        ("terminal: size", lambda: terminal.size()),
        ("terminal: mode", lambda: terminal.mode(2004)),
        ("terminal: title", lambda: terminal.title()),
    ]


def feed_cases() -> list[Case]:
    """Feeding each scenario's next piece of output, with no frame read."""
    cases: list[Case] = []
    for name, scenario in SCENARIOS.items():
        _, feed = fed(scenario)
        cases.append((f"feed: {name}", feed))
    return cases


def frame_cases() -> list[Case]:
    """Feeding each scenario's next piece of output and reading the frame after it."""
    cases: list[Case] = []
    for name, scenario in SCENARIOS.items():
        terminal, feed = fed(scenario)
        state = RenderState(terminal)
        state.frame()

        def step(feed: Callable[[], None] = feed, state: RenderState = state) -> None:
            feed()
            state.frame()

        cases.append((f"frame: {name}", step))
    return cases


def scrollback_cases() -> list[Case]:
    """Reading what scrolled off, every frame and all at once."""
    scenario = SCENARIOS["numbered line, 10 MB scrollback"]
    terminal, feed = fed(scenario)
    state = RenderState(terminal)
    state.scrolled_off()

    def scrolled_off() -> None:
        feed()
        state.scrolled_off()

    history = Terminal(COLUMNS, ROWS, max_scrollback_bytes=10_000_000)
    history.feed(b"".join(map(numbered_line, range(1_000 + ROWS))))
    history_state = RenderState(history)
    return [
        ("scrollback: scrolled_off, one line", scrolled_off),
        ("scrollback: history, 1,000 rows", lambda: history_state.history()),
    ]


def row_cases() -> list[Case]:
    """Reading a frame's rows and styles from Python, as a consumer converts them."""
    terminal = Terminal(COLUMNS, ROWS)
    terminal.feed(COLORED_LINE * ROWS)
    frame = RenderState(terminal).frame()
    rows = frame.rows
    row = rows[0]
    style = frame.new_styles[1]

    def join_every_row() -> None:
        for each in rows:
            "".join(each.graphemes)

    def resolve_every_style() -> None:
        styles = frame.new_styles
        for each in rows:
            [styles[index] for index in each.styles]

    return [
        ("rows: frame.rows", lambda: frame.rows),
        ("rows: row.graphemes", lambda: row.graphemes),
        ("rows: row.styles", lambda: row.styles),
        ("rows: row.widths", lambda: row.widths),
        ("rows: join every row's graphemes", join_every_row),
        ("rows: resolve every cell's style", resolve_every_style),
        ("rows: style.foreground", lambda: style.foreground),
        ("rows: hash(style)", lambda: hash(style)),
    ]


def input_cases() -> list[Case]:
    """Encoding key and mouse events in the legacy and current protocols."""
    legacy = KeyEncoder(Terminal(COLUMNS, ROWS))
    kitty_terminal = Terminal(COLUMNS, ROWS)
    kitty_terminal.feed(b"\x1b[>31u")
    kitty = KeyEncoder(kitty_terminal)
    mouse_terminal = Terminal(COLUMNS, ROWS)
    mouse_terminal.feed(b"\x1b[?1003h\x1b[?1006h")
    mouse = MouseEncoder(mouse_terminal)
    positions = itertools.cycle([(3.0, 4.0), (5.0, 4.0)])

    def motion() -> None:
        mouse.encode(MouseAction.MOTION, *next(positions))

    return [
        ("input: key, letter", lambda: legacy.encode(Key.A, text="a")),
        ("input: key, ctrl+c", lambda: legacy.encode(Key.C, text="c", mods=Mods.CTRL)),
        ("input: key, arrow", lambda: legacy.encode(Key.ARROW_UP)),
        ("input: key, letter, kitty protocol", lambda: kitty.encode(Key.A, text="a")),
        (
            "input: mouse, press",
            lambda: mouse.encode(MouseAction.PRESS, 3.0, 4.0, button=MouseButton.LEFT),
        ),
        ("input: mouse, motion to another cell", motion),
    ]


def encode_cases() -> list[Case]:
    """The stateless encoders and width functions."""
    paste = "some pasted text\n" * 60
    return [
        ("encode: encode_paste, 1 KB, bracketed", lambda: encode_paste(paste, bracketed=True)),
        ("encode: is_paste_safe, 1 KB", lambda: is_paste_safe(paste)),
        ("encode: codepoint_width", lambda: codepoint_width("日")),
        ("encode: grapheme_width", lambda: grapheme_width("👩‍💻 typing")),
    ]


def format_cases() -> list[Case]:
    """Formatting a full screen of colored text."""
    terminal = Terminal(COLUMNS, ROWS)
    terminal.feed(COLORED_LINE * ROWS)
    formatters = {kind: Formatter(terminal, format=kind, trim=True) for kind in FormatterFormat}
    return [
        (f"format: {kind.name.lower()}, colored screen", formatter.format)
        for kind, formatter in formatters.items()
    ]


def all_cases() -> list[Case]:
    """Every case, grouped by area."""
    return (
        terminal_cases()
        + feed_cases()
        + frame_cases()
        + scrollback_cases()
        + row_cases()
        + input_cases()
        + encode_cases()
        + format_cases()
    )


def format_ratio(ratio: float) -> str:
    """Format a current-to-baseline time ratio, marking changes beyond noise."""
    if ratio <= 0.95:
        marker = "  faster"
    elif ratio >= 1.05:
        marker = "  SLOWER"
    else:
        marker = ""
    return f"{ratio:.2f}x{marker}"


def main() -> None:
    """Run the selected cases, print them, and optionally save or compare the results."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-k", "--filter", default="", help="only run cases whose name contains this"
    )
    parser.add_argument("--repeat", type=int, default=5, help="calibrated runs per case")
    parser.add_argument("--save", type=Path, help="write the results to this JSON file")
    parser.add_argument("--compare", type=Path, help="compare against results saved with --save")
    args = parser.parse_args()

    baseline: dict[str, float] = json.loads(args.compare.read_text()) if args.compare else {}
    cases = [(name, fn) for name, fn in all_cases() if args.filter in name]
    width = max(len(name) for name, _ in cases)

    results: dict[str, float] = {}
    ratios: list[float] = []
    for name, fn in cases:
        seconds = best_of(fn, args.repeat)
        results[name] = seconds
        line = f"{name:<{width}}  {format_time(seconds):>10}"
        if (before := baseline.get(name)) is not None:
            ratio = seconds / before
            ratios.append(ratio)
            line += f"  {format_time(before):>10}  {format_ratio(ratio)}"
        print(line, flush=True)

    if ratios:
        print(f"\ngeometric mean of {len(ratios)} ratios: {geometric_mean(ratios):.2f}x")
    if args.save:
        args.save.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()

"""
The spike's measurements against counterweight's pyghostty-based emulator.

Run it with a Python that has evp and counterweight (from a checkout) installed:

- `snapshot`: counterweight's `benchmarks snapshot` scenarios, timed as it times them,
  for counterweight's `Emulator`, the evp prototype in `spike/emulator.py`, and evp's `frame()` alone.
  Their lines are all alike, so two more scroll lines that each differ from the last,
  one of them with a 10,000-row scrollback, which counterweight sets aside at each snapshot.
  Before timing, it checks that both emulators return the same rows and scrolled-off rows.
- `startup`: in fresh processes, the time from importing the binding through the first terminal
  and the first snapshot, the best of several runs.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from benchmarks.snapshots import COLUMNS, ROWS, SCENARIOS
from counterweight.emulator import Emulator

from evp import RenderState, Terminal

sys.path.insert(0, str(Path(__file__).parent))
from emulator import EvpEmulator

REPEAT = 5
NUMBER = 200
STARTUP_RUNS = 7

STARTUP = {
    "pyghostty": """
from time import perf_counter
start = perf_counter()
from counterweight.emulator import Emulator
imported = perf_counter()
emulator = Emulator(120, 40, on_reply=lambda _: None)
made = perf_counter()
emulator.snapshot()
end = perf_counter()
""",
    "evp": """
from time import perf_counter
start = perf_counter()
from evp import RenderState, Terminal
imported = perf_counter()
state = RenderState(Terminal(120, 40))
made = perf_counter()
state.frame()
end = perf_counter()
""",
}
REPORT = "\nprint((imported - start) * 1e3, (made - start) * 1e3, (end - start) * 1e3)"


@dataclass(frozen=True, slots=True)
class Case:
    setup: bytes
    """Fed once, before any snapshot is timed."""

    step: Callable[[int], bytes]
    """What's fed before the timed snapshot of each number."""

    scrollback: int = 0


def numbered_line(number: int) -> bytes:
    return (b"line %d of the program's output " % number * 4)[: COLUMNS - 1] + b"\r\n"


CASES: dict[str, Case] = {
    **{
        name: Case(setup=scenario.setup, step=lambda _, step=scenario.step: step)
        for name, scenario in SCENARIOS.items()
    },
    "numbered-line": Case(setup=b"".join(map(numbered_line, range(-ROWS, 0))), step=numbered_line),
    "numbered-line-scrollback": Case(
        setup=b"".join(map(numbered_line, range(-10_000, 0))),
        step=numbered_line,
        scrollback=10_000,
    ),
}


def check_equivalence() -> None:
    """Fail unless both emulators show the same rows, cursor, modes and scrolled-off rows after every case."""
    for name, case in CASES.items():
        with Emulator(
            COLUMNS, ROWS, on_reply=lambda _: None, scrollback=case.scrollback
        ) as pyghostty:
            evp = EvpEmulator(COLUMNS, ROWS, on_reply=lambda _: None, scrollback=case.scrollback)
            for data in (case.setup, *map(case.step, range(3))):
                pyghostty.feed(data)
                evp.feed(data)
                expected, actual = pyghostty.snapshot(), evp.snapshot()
                if (expected.lines, expected.cursor, expected.modes) != (
                    actual.lines,
                    actual.cursor,
                    actual.modes,
                ) or pyghostty.scrolled_off() != evp.scrolled_off():
                    raise SystemExit(
                        f"{name}: the evp prototype's screen differs from counterweight's"
                    )


def best_us(feed: Callable[[bytes], None], snapshot: Callable[[], object], case: Case) -> float:
    """The best mean time per snapshot over `REPEAT` rounds of `NUMBER`, each after one more step."""
    feed(case.setup)
    snapshot()
    rounds = []
    number = 0
    for _ in range(REPEAT):
        elapsed = 0.0
        for _ in range(NUMBER):
            feed(case.step(number))
            number += 1
            start = perf_counter()
            snapshot()
            elapsed += perf_counter() - start
        rounds.append(elapsed / NUMBER)
    return min(rounds) * 1e6


def snapshots() -> dict[str, dict[str, float]]:
    timings: dict[str, dict[str, float]] = {}
    for name, case in CASES.items():
        with Emulator(
            COLUMNS, ROWS, on_reply=lambda _: None, scrollback=case.scrollback
        ) as pyghostty:
            timings.setdefault("pyghostty", {})[name] = best_us(
                pyghostty.feed, pyghostty.snapshot, case
            )
        evp = EvpEmulator(COLUMNS, ROWS, on_reply=lambda _: None, scrollback=case.scrollback)
        timings.setdefault("evp prototype", {})[name] = best_us(evp.feed, evp.snapshot, case)
        if case.scrollback:
            continue
        terminal = Terminal(COLUMNS, ROWS)
        state = RenderState(terminal)
        timings.setdefault("evp frame()", {})[name] = best_us(terminal.feed, state.frame, case)
    return timings


def startup() -> dict[str, list[float]]:
    """Each binding's best (import, first terminal, first snapshot) milliseconds, each from the start."""
    timings = {}
    for name, script in STARTUP.items():
        runs = [
            [
                float(part)
                for part in subprocess.check_output([sys.executable, "-c", script + REPORT]).split()
            ]
            for _ in range(STARTUP_RUNS)
        ]
        timings[name] = [min(run[index] for run in runs) for index in range(3)]
    return timings


def main() -> None:
    check_equivalence()
    print(json.dumps({"snapshot_us": snapshots(), "startup_ms": startup()}, indent=2))


if __name__ == "__main__":
    main()

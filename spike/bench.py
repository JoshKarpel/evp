"""
The spike's measurements against counterweight's pyghostty-based emulator.

Run it with a Python that has evp and counterweight (from a checkout) installed:

- `snapshot`: counterweight's `benchmarks snapshot` scenarios, timed as it times them,
  for counterweight's `Emulator`, the evp prototype in `spike/emulator.py`, and evp's `frame()` alone.
  Before timing, it checks that both emulators return the same rows.
- `startup`: in fresh processes, the time from importing the binding through the first terminal
  and the first snapshot, the best of several runs.
"""

import json
import subprocess
import sys
from collections.abc import Callable
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


def check_equivalence() -> None:
    """Fail unless both emulators show the same rows, cursor and modes after every scenario."""
    for name, scenario in SCENARIOS.items():
        with Emulator(COLUMNS, ROWS, on_reply=lambda _: None) as pyghostty:
            evp = EvpEmulator(COLUMNS, ROWS, on_reply=lambda _: None)
            for data in (scenario.setup, *(scenario.step,) * 3):
                pyghostty.feed(data)
                evp.feed(data)
                expected, actual = pyghostty.snapshot(), evp.snapshot()
                if (expected.lines, expected.cursor, expected.modes) != (
                    actual.lines,
                    actual.cursor,
                    actual.modes,
                ):
                    raise SystemExit(
                        f"{name}: the evp prototype's screen differs from counterweight's"
                    )


def best_us(
    feed: Callable[[bytes], None], snapshot: Callable[[], object], setup: bytes, step: bytes
) -> float:
    """The best mean time per snapshot over `REPEAT` rounds of `NUMBER`, each after one more `step`."""
    feed(setup)
    snapshot()
    rounds = []
    for _ in range(REPEAT):
        elapsed = 0.0
        for _ in range(NUMBER):
            feed(step)
            start = perf_counter()
            snapshot()
            elapsed += perf_counter() - start
        rounds.append(elapsed / NUMBER)
    return min(rounds) * 1e6


def snapshots() -> dict[str, dict[str, float]]:
    timings: dict[str, dict[str, float]] = {}
    for name, scenario in SCENARIOS.items():
        with Emulator(COLUMNS, ROWS, on_reply=lambda _: None) as pyghostty:
            timings.setdefault("pyghostty", {})[name] = best_us(
                pyghostty.feed, pyghostty.snapshot, scenario.setup, scenario.step
            )
        evp = EvpEmulator(COLUMNS, ROWS, on_reply=lambda _: None)
        timings.setdefault("evp prototype", {})[name] = best_us(
            evp.feed, evp.snapshot, scenario.setup, scenario.step
        )
        terminal = Terminal(COLUMNS, ROWS)
        state = RenderState(terminal)
        timings.setdefault("evp frame()", {})[name] = best_us(
            terminal.feed, state.frame, scenario.setup, scenario.step
        )
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

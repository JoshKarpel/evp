# Benchmarks

Scripts for measuring evp's per-call costs, for anyone changing a hot path.
They time the Python-facing API end to end, binding overhead included,
since that's what callers pay.
They don't benchmark Ghostty's parser or screen on their own.

- `suite.py` times every operation a consumer performs, and saves or compares results.
- `ab.py` compares two builds of the extension module by alternating them.
- `tips.py` measures the ratios that [`docs/performance.md`](../docs/performance.md) states.
- `workloads.py` holds the scenarios and timing helpers the others share.

`spike/bench.py` is separate: it measures evp against counterweight's current emulator,
and needs counterweight installed.

## Run against a release build

A debug build's timings say nothing about what users see:
it compiles Ghostty unoptimized too.
`just bench` builds with the release profile (fat LTO, so it takes a minute) and runs the suite;
`just bench-build` only builds.
`just build` and `just test` go back to a debug build afterwards.

Run the scripts with the environment's interpreter (`uv run --no-sync`, as `just bench` does),
not a plain `uv run`: a sync after `pyproject.toml` changes rebuilds evp through maturin's build
backend and installs that build over the one you made.

## Compare builds, not runs

A result saved with `--save` and compared later with `--compare` also measures
whatever else the machine was doing in between.
To judge a change, build each side, keep both copies of the extension module,
and let `ab.py` alternate them:

```text
just bench-build && cp python/evp/_evp.abi3.so /tmp/before.so   # at the baseline
just bench-build && cp python/evp/_evp.abi3.so /tmp/after.so    # with the change
cd benchmarks && uv run --no-sync python ab.py /tmp/before.so /tmp/after.so -k frame
```

Read the cases the change can't affect as the control:
if they moved, so did the machine.

## Profile

`perf` needs `kernel.perf_event_paranoid` at 1 or lower to profile user space.
Build with debug info and frame pointers, record a script that loops the workload,
and read the result with `perf report` or [samply](https://github.com/mstange/samply):

```text
LIBGHOSTTY_VT_SYS_OPTIMIZE=ReleaseFast CARGO_PROFILE_RELEASE_DEBUG=true \
  RUSTFLAGS="-Cforce-frame-pointers=yes --cfg pyo3_disable_reference_pool" \
  uv run --no-sync maturin develop --release
perf record --call-graph dwarf --freq 2000 -o /tmp/evp.data -- .venv/bin/python workload.py
perf report -i /tmp/evp.data --no-children --sort symbol
```

Debug info makes cargo tell build scripts `DEBUG=true`, and `libghostty-vt-sys` then builds
Ghostty in Zig's Debug mode, integrity checks and all; `LIBGHOSTTY_VT_SYS_OPTIMIZE` keeps it
optimized. Ghostty's frames carry no frame pointers, so record with DWARF call graphs.
`RUSTFLAGS` replaces the `rustflags` in `.cargo/config.toml`, so the profiling build repeats them.

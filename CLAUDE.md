# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# evp

A Python binding to libghostty-vt, Ghostty's terminal emulator library, built with PyO3/maturin on
[libghostty-rs](https://github.com/Uzaaft/libghostty-rs)'s `libghostty-vt` crate.
It replaces pyghostty as [counterweight](https://github.com/JoshKarpel/counterweight)'s terminal emulator binding,
as [waxy](https://github.com/JoshKarpel/waxy) is counterweight's binding to taffy; waxy is the model for this repo's layout, tooling and habits.

## Key Files

- `PLAN.md`: the design (why own the binding, the API's shape, language, build and release, the work in steps)
  and what the spike measured. `plans/upgrade-libghostty-vt.md`: what moving past libghostty-vt 0.2.2 gains and changes.
- `python/evp/_evp.pyi`: the type stub, and the source of the API reference: mkdocstrings renders `docs/api.md` from its docstrings.
- `spike/`: `emulator.py` is counterweight's `Emulator` rebuilt on evp; `bench.py` times it against counterweight's,
  and `counterweight-tests.sh` runs counterweight's `tests/test_emulator.py` against it.
  Both need a Python with evp and counterweight (from a checkout) installed; their docstrings and header say how to run them.
- `docs/maintaining.md`: building, releasing, upgrading libghostty-vt (and Zig with it), adding a Python version.
- `benchmarks/`: the timing suite and build-against-build comparison for hot-path changes;
  its `README.md` covers the workflow (release builds, comparing builds rather than runs, profiling).
  `tips.py` measures the ratios `docs/performance.md` states; rerun it when a change could move them.
- `tests/test_*_properties.py`: Hypothesis property tests, on the VT output strategies in `tests/strategies.py`.
  The render state's oracle is a twin terminal fed the same calls and read by a fresh `RenderState` each time,
  so whatever `frame` reuses must read as a from-scratch read does.

## Architecture

The Rust source (`src/`) exposes a flat PyO3 module `_evp`, which `python/evp/__init__.py` re-exports.

| File | Contents |
|------|----------|
| `src/lib.rs` | PyO3 module definition, wires each file's `register()`; `Owned`, the `Send` wrapper for libghostty objects |
| `src/errors.rs` | `GhosttyError`, and `ghostty_error` for `map_err` on every libghostty-vt `Result` |
| `src/enums.rs` | The Python `IntEnum`s and `IntFlag`s (`Key`, `Mods`, `MouseButton`, ...), built at import from libghostty's C constants |
| `src/style.rs` | `Style`, a hashable value copy of libghostty's style, with colors as `None`, a palette index or RGB |
| `src/terminal.rs` | `Terminal`: feeding bytes, resizing, modes, title, colors, viewport, its callbacks; `DeviceAttributes` |
| `src/render.rs` | `RenderState` and what it returns (`Frame`, `ScrolledOff`, `History`, `Row`) |
| `src/input.rs` | `KeyEncoder` and `MouseEncoder`, which read the terminal's modes for each event |
| `src/encode.rs` | The stateless encoders (focus, paste, color scheme, size report) and the width functions |
| `src/format.rs` | `Formatter` |

`RenderState` is where the work is. Three reads share one style table:

- **`frame()`** reads the screen. A row libghostty doesn't mark dirty is the last frame's `Row` at that position.
  A dirty row's raw cells are compared with every row of the last frame (`find_unchanged`), so a row a scroll moved
  comes back as the same `Row` object; consumers (counterweight's `Emulator`) reuse derived data by `Row` identity.
- **`scrolled_off()`** keeps an `Anchor`, a tracked grid reference on the row at the top of the screen at its last call.
  The anchor follows that row into the scrollback, so its history position counts the rows that scrolled off since;
  those rows are read through grid references (`HistoryCells`).
- **`history()`** reads the whole scrollback the same way.

`read_row` reads either source through the `Cells` trait (`RenderStateCells`, `HistoryCells`).
Styles are interned terminal-wide in `Styles`, and each of the three reads delivers the styles first used since any of them last did,
so rows name styles by index and a consumer converts each once. Index 0 is always the default style.

## Key Design Decisions

- **libghostty-vt 0.2.2, not a git pin of `master`.** 0.2.2's Ghostty has no row ids, no bulk raw cells (`cells_raw`),
  no overscan and no scrollback limit in lines, in its C API as well as the Rust wrapper. evp works around each;
  `plans/upgrade-libghostty-vt.md` lists the workarounds and what upgrading changes. Don't reach for `master`-only APIs.
- **The scrollback limit is bytes.** libghostty-rs documents 0.2.2's `Options::max_scrollback` as lines, but its Ghostty
  treats it as bytes, frees a page (a few hundred KB) at a time, and keeps at least a page or two above zero.
  So `Terminal` takes `max_scrollback_bytes`, fixed at construction.
- **Equal raw cells don't mean an equal row**, and `find_unchanged` and `read_row`'s `style_probes` guard both cases:
  a page reuses a freed style id for another style, so each style id's style is read again from the dirty row;
  and a cell's codepoints after its first live outside its raw value, so a row with a multi-codepoint grapheme cluster
  (`style_probes: None`) is never reused by its cells. Tests in `tests/test_render_state.py` reproduce both.
- **No mirrored row or cell iterators.** A call from Python into Rust per cell is slower than `frame()` plus a Python loop
  over every cell, so the bulk reads are the only way to read cells; PLAN.md's "Why no iterators?" has the measurements.
  A cell a bulk read lacks (a hyperlink) belongs on `Row`, or in a point lookup for sparse reads, not in an iterator.
- **A terminal has at most one `RenderState`.** A second would take the first's dirty flags, so `RenderState::new`
  refuses it through `Terminal.is_rendered`, an `Arc<AtomicBool>` its `Drop` clears.
- **No `#[pyclass(unsendable)]`**, as in waxy. libghostty's objects hold raw pointers, so `OwnedTerminal` and `Owned<T>`
  carry `unsafe impl Send + Sync`, which rests on every access to them going through a `&mut self` method
  (or `Py::borrow_mut`), so PyO3's borrow checking makes each access exclusive. A `&self` method that touches them breaks that.
- **Callback exceptions** are stored in `Terminal.raised` while libghostty runs the callback, then raised when the call
  (`feed`, `resize`, `reset`) returns, first one wins. A callback runs while the terminal is borrowed,
  so it's passed what it needs (the new title, the clipboard's contents) rather than calling back into the terminal.
- **Enums are Python `IntEnum`s and `IntFlag`s built at import** (`src/enums.rs`) from libghostty-vt-sys's constants,
  so their values have one source. Rust takes them as plain integers and converts with `enums::parse`.
  `tests/test_stub.py` checks the stub's members against them, and that the stub and module name the same things.
- **`MouseEncoder` syncs from the terminal only when its mouse modes or size changed**:
  libghostty's `set_options_from_terminal` and `set_size` both forget the last cell, which breaks `track_last_cell`.
- **libghostty's docs and its behavior differ**, so probe before trusting the C header or libghostty-rs's docs.
  Each of these is pinned by a test: device attributes get Ghostty's own reply with no callback, though the header says none;
  `set_options_from_terminal` resets the mouse encoder's `track_last_cell` state, which no doc mentions;
  `Options::max_scrollback` is bytes, not lines; the formatter's `trim` applies to plain text only;
  a resize truncating the alternate screen can leave a wide character with no second column;
  and the C0 controls 0x1c to 0x1f and DEL print into cells.
- **Ghostty's safety checks abort a debug build, and are undefined behavior in a release one.**
  A value that overflows a conversion inside Ghostty (`@intFromFloat` on a mouse position) panics the whole process,
  so evp bounds what it passes (`input.rs`'s `position`). The property tests are how these turn up:
  a crash kills pytest rather than failing a test, so rerun with `-s -n0` to see Ghostty's panic.
  One remains upstream: resizing with the viewport in the scrollback can fail the page list's integrity check;
  `test_render_state_properties.py`'s `resize` rule works around it.
- **No ENQ or XTVERSION callbacks**: libghostty-rs's types tie the reply's `&str` to the terminal's lifetime,
  so a Python callable can't supply one without leaking it. Ghostty sends nothing for ENQ and `libghostty` for XTVERSION.
- **No pyo3 reference pool**: `.cargo/config.toml` sets `--cfg pyo3_disable_reference_pool`, as waxy does, and CI's
  `RUSTFLAGS` replaces that list, so `ci.yml` repeats the flag; keep the two in sync.
- **`abi3`**: maturin builds one limited-API wheel for CPython 3.13 and newer (`[tool.maturin] features`); the `abi3` Cargo feature is off for plain `cargo`.
- **Ghostty's Zig is pinned.** `libghostty-vt-sys`'s build script clones the Ghostty commit it pins and runs the `zig` on `PATH`,
  and Ghostty refuses any Zig but the one its `build.zig.zon` names, so `zig` in `mise.toml` follows the libghostty-vt version in `Cargo.lock`.

## Commands

Every tool (Rust, Zig, just, uv) comes from `mise.toml`; Python dev tools come from uv's dev group. `just --list` shows the recipes.

- `just check` (alias `c`): fix, test, and a strict docs build. Run it before committing.
- `just test` (alias `t`): `maturin develop`, mypy, pytest, and `cargo test`.
- `just fix` (alias `f`): `git add --update`, then pre-commit (formatters, ruff, clippy, workflow checks).
- `just build`: `uv run maturin develop`, a debug build.
- `just bench`: a release build, then `benchmarks/suite.py`; `just bench-build` only builds.
- `just docs-build` / `just docs-serve`: the mkdocs site.

Override variables pass arguments through:

- `just pytest-args="-k scrolled_off" py-test`, or after `just build`, `uv run pytest tests/test_render_state.py::test_name`
- `just cargo-test-args="tracked_reference" rs-test`
- `just bench-args="-k frame --compare /tmp/before.json" bench`
- `just pre-commit-args="--all-files" fix`

Build and test gotchas:

- A clean build clones and compiles Ghostty (a few minutes), and needs network access.
- A debug build compiles Ghostty unoptimized too, so a test that feeds tens of thousands of lines takes a minute.
  To fill the scrollback's pages quickly, use a wide terminal (1,000 columns) and fewer lines, as the pruning tests do.
- An old per-version extension (`python/evp/_evp.cpython-3XX-*.so`) left beside `_evp.abi3.so` shadows it,
  so Python imports the stale build. Delete it.
- Benchmark only release builds (`just bench-build`); debug numbers say nothing about evp's speed.
- Editing `pyproject.toml` makes the next `uv run` rebuild evp through maturin's build backend, in release,
  over whatever `just build` installed. `just test` rebuilds first; for anything else, `just build` again,
  or run with `uv run --no-sync`.

## Dependencies

Add Python packages with `uv add` and Rust crates with `cargo add`, not by editing `pyproject.toml` or `Cargo.toml`,
so the lockfiles stay in sync. `pyproject.toml`'s `exclude-newer` and mise's `minimum_release_age` apply a 7-day cooldown.

## Changing the API

1. Add or change the Rust in the right `src/*.rs` file and register new classes in its `register()`.
2. Update `python/evp/_evp.pyi`, docstrings included, since they are the API reference, and `python/evp/__init__.py`'s exports.
3. Add the class to `docs/api.md` if it's new, and an entry to `docs/changelog.md`.
4. If counterweight would see the change, update `spike/emulator.py` and rerun `spike/counterweight-tests.sh`.

A new enum goes in `src/enums.rs`'s `ENUMS` and in the stub; `tests/test_stub.py` fails until the two agree.

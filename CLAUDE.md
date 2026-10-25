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
- `docs/maintaining.md`: building, upgrading libghostty-vt (and Zig with it), adding a Python version.

## Architecture

The Rust source (`src/`) exposes a flat PyO3 module `_evp`, which `python/evp/__init__.py` re-exports.

| File | Contents |
|------|----------|
| `src/lib.rs` | PyO3 module definition, wires each file's `register()` |
| `src/errors.rs` | `GhosttyError`, and `ghostty_error` for `map_err` on every libghostty-vt `Result` |
| `src/style.rs` | `Style`, a hashable value copy of libghostty's style, with colors as `None`, a palette index or RGB |
| `src/terminal.rs` | `Terminal`: feeding bytes, resizing, modes, title, default colors and palette, the `on_write_pty` callback |
| `src/render.rs` | `RenderState` and what it returns (`Frame`, `ScrolledOff`, `History`, `Row`) |

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
- **A terminal has at most one `RenderState`.** A second would take the first's dirty flags, so `RenderState::new`
  refuses it through `Terminal.is_rendered`, an `Arc<AtomicBool>` its `Drop` clears.
- **No `#[pyclass(unsendable)]`**, as in waxy. libghostty's objects hold raw pointers, so `OwnedTerminal` and `Owned<T>`
  carry `unsafe impl Send + Sync`, which rests on every access to them going through a `&mut self` method
  (or `Py::borrow_mut`), so PyO3's borrow checking makes each access exclusive. A `&self` method that touches them breaks that.
- **`on_write_pty` exceptions** are stored in `Terminal.raised` while libghostty runs the callback, then raised when the call
  (`feed`, `resize`) returns, first one wins.
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
- `just docs-build` / `just docs-serve`: the mkdocs site.

Override variables pass arguments through:

- `just pytest-args="-k scrolled_off" py-test`, or after `just build`, `uv run pytest tests/test_render_state.py::test_name`
- `just cargo-test-args="tracked_reference" rs-test`
- `just pre-commit-args="--all-files" fix`

Build and test gotchas:

- A clean build clones and compiles Ghostty (a few minutes), and needs network access.
- A debug build compiles Ghostty unoptimized too, so a test that feeds tens of thousands of lines takes a minute.
  To fill the scrollback's pages quickly, use a wide terminal (1,000 columns) and fewer lines, as the pruning tests do.
- An old per-version extension (`python/evp/_evp.cpython-3XX-*.so`) left beside `_evp.abi3.so` shadows it,
  so Python imports the stale build. Delete it.
- Benchmark only release builds (`maturin build --release`); debug numbers say nothing about evp's speed.

## Dependencies

Add Python packages with `uv add` and Rust crates with `cargo add`, not by editing `pyproject.toml` or `Cargo.toml`,
so the lockfiles stay in sync. `pyproject.toml`'s `exclude-newer` and mise's `minimum_release_age` apply a 7-day cooldown.

## Changing the API

1. Add or change the Rust in the right `src/*.rs` file and register new classes in its `register()`.
2. Update `python/evp/_evp.pyi`, docstrings included, since they are the API reference, and `python/evp/__init__.py`'s exports.
3. Add the class to `docs/api.md` if it's new, and an entry to `docs/changelog.md`.
4. If counterweight would see the change, update `spike/emulator.py` and rerun `spike/counterweight-tests.sh`.

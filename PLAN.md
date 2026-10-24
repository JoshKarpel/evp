# Plan: evp, an Owned Binding to libghostty-vt

Artifact: https://claude.ai/code/artifact/ec9acde5-2420-4684-8f2e-1ed974a51fc2

This plan builds evp, a Python binding to libghostty-vt, Ghostty's terminal emulator library,
to replace [pyghostty](https://github.com/AnswerDotAI/pyghostty) as [counterweight](https://github.com/JoshKarpel/counterweight)'s binding to it,
as [waxy](https://github.com/JoshKarpel/waxy) is counterweight's binding to taffy.
It covers why, what the binding's API returns, which language it's written in, how it's built and released,
and how `counterweight.emulator` moves onto it.
It doesn't change counterweight's `Emulator` or `Screen`, the API the rest of counterweight and its users see,
and it doesn't move counterweight onto the kitty keyboard protocol or anything else its emulator doesn't do today,
though evp's first release binds more of libghostty-vt than counterweight uses.
The name is a pun: EVP, electronic voice phenomena,
are the voices ghost hunters claim to record, and evp is how Python hears from Ghostty.
counterweight's copy of this plan is [plans/ghostty-binding.md](https://github.com/JoshKarpel/counterweight/blob/43ad2e1477994716b3254626f245af42407944f4/plans/ghostty-binding.md).

## Why own the binding?

Every cost below comes from the binding, not from libghostty-vt,
and fixing pyghostty upstream would cure only the first.

- **Making the first emulator takes about 190 ms.**
  pyghostty is cffi in in-line ABI mode: importing `pyghostty._ffi` parses its 3,500-line cdef with pycparser (about 94 ms),
  and each type string `Emulator.__init__` passes to `ffi.new` is parsed again on first use,
  after a `typedef` line for every typedef in the cdef (about 4 ms each, about 95 ms for its twenty).
  An inline app makes its emulator before its first frame, so every inline app starts that much later
  (see Run 29 in [counterweight's performance analysis](https://github.com/JoshKarpel/counterweight/blob/43ad2e1477994716b3254626f245af42407944f4/plans/performance-analysis.md)),
  and every test subprocess that imports the emulator pays it too.
  The same cdef built out-of-line imports, loads the library and makes those types in 0.8 ms.
  Since the cost is architectural, an inline app keeps making its emulator unconditionally:
  once the binding loads in a millisecond or two, keeping it costs nothing worth an option.
- **Snapshots read cells through several cffi calls each.**
  `convert_row` reads a row's raw 64-bit cell values in one call, but reads a cell it hasn't seen
  through the cell iterator, since libghostty's header says the raw values' bit positions aren't ABI-stable,
  so they can't be decoded in Python.
  A screen that scrolls marks every row dirty, so a scroll converts the whole screen.
  Best times per snapshot of a 120×40 screen (counterweight's `benchmarks snapshot`):

  | After | µs per snapshot |
  | --- | --- |
  | nothing | 66 |
  | a progress bar rewriting its row | 76 |
  | a plain line, scrolling | 435 |
  | a line of wide characters, scrolling | 515 |
  | a line with every word colored, scrolling | 3,638 |

- **Scrollback is captured in rounds to keep it affordable.**
  Capturing all 10,000 scrollback rows each snapshot cost 17 to 24 ms,
  so `update` asks for about as many rows as scrolled, doubling until it finds the last row it already has.
  That search, and the cache of rows it keeps by id, is a large share of counterweight's `emulator.py`.
- **Raw pointers are counterweight's to get right.**
  A review found `convert_row` reading grapheme clusters into a fixed 32-slot buffer that libghostty overran:
  printing an `e` with 200 combining accents segfaulted the app.
  The buffer grows now, but nothing stops the next mistake of that kind.
- **counterweight reaches into pyghostty's internals.**
  It imports `pyghostty._ffi`'s `ffi`, `lib` and `check`, reads `Terminal._t` (with `# noqa: SLF001`),
  and makes 18 libghostty-vt calls itself; from pyghostty's public API it uses only `Terminal` and `init_sized`.
  So counterweight already is most of a binding, and depends on pyghostty for a built library and a cdef,
  through names pyghostty doesn't promise to keep.
  pyghostty has no type stubs, so none of those calls are type-checked.

## How does the web do it?

The web's embedded terminal is [xterm.js](https://xtermjs.org/), and its buffer API reads a cell at a time:
`buffer.getLine(y)` returns a line, `line.getCell(x, cell)` fills a cell object the caller passes back in
"to avoid costly recreation", and the cell has accessors like `getFgColorMode()` and `isFgRGB()`.
`translateToString()` reads a line's text in one call.

Python's own precedent is [pyte](https://github.com/selectel/pyte), and it reads values:
`screen.display` is each row's text, `screen.buffer[y][x]` is a `Char` named tuple of a cell's text, colors and attributes,
and `screen.dirty` is the set of rows that changed.

A JavaScript engine inlines xterm.js's small calls, so reading cell by cell is cheap there.
A call from Python into native code costs far more than the work it does,
so evp's reads return values, as pyte's do, and its fast helpers read a whole row in one call.
Its low-level layer still reads a cell at a time, as xterm.js does, for code that wants one.

## The binding's API

```mermaid
flowchart TB
    A["counterweight.emulator<br/>Emulator → Screen (unchanged API)"]
    O["other consumers<br/>multiplexers, test harnesses, recorders, other TUI frameworks"]
    B["evp (Python package)<br/>Pythonic classes over libghostty-vt's C API, reads as values"]
    C["libghostty-vt<br/>Ghostty's terminal core, built with Zig and linked in statically"]
    A --> B
    O --> B
    B -->|"natively"| C
```

evp is a general Python API to libghostty-vt, and counterweight's `Emulator` is one consumer of it.
It has two layers, as waxy does.

- **The low-level layer mirrors the C API**, as waxy's `TaffyTree` mirrors taffy's:
  one Python class for each of libghostty-vt's objects (a terminal, a render state, a row iterator, a key encoder),
  a method for each of its functions, enums for its constants, exceptions for its error codes,
  callbacks as Python callables, and reads that return immutable values.
  Anything libghostty-vt can do, a Python program can do through it, one call at a time.
- **Fast helpers do in one call what would be a loop over the low-level layer**, as waxy's `absolute_layouts(root)`
  returns every visible node with its absolute position, where Python would walk `children` and `layout` node by node.
  A helper exists where the loop's calls from Python would cost more than the work they do,
  and returns what the loop would have, so it's never the only way to get something.

```python
terminal = Terminal(columns=120, rows=40, scrollback_lines=10_000, on_write_pty=pty.write)
terminal.feed(output)
terminal.resize(columns=100, rows=30)

state = RenderState(terminal)
state.update()

# Low level: libghostty-vt's iterators, a call per row and per cell.
rows = state.row_iterator()
while rows.next():
    cells = rows.cells()
    while cells.next():
        cells.graphemes(), cells.style()

# A fast helper: every row, each changed one read in one native call, as values.
frame = state.frame()  # the cursor, colors, styles added since the last frame, and the rows
for row in frame.rows:  # a row unchanged since the last frame is the same object
    row.graphemes, row.widths, row.styles

keys = KeyEncoder(terminal)  # encodes as the terminal's modes say
pty.write(keys.encode(Key.ENTER, mods=Mods.CTRL))
```

The first release covers what embedding a terminal needs:

| Area | libghostty-vt | Low level | Fast helpers |
| --- | --- | --- | --- |
| The terminal | `terminal.h`, `modes.h`, `device.h`: write, resize, reset, scroll the viewport, options and callbacks (replies to the program, title, working directory, clipboard, bell, unknown sequences) | `Terminal` | |
| Reading the screen | `render.h`, `screen.h`, `style.h`, `color.h`: render state, dirty rows with stable ids, cells, styles, the palette, overscan into the scrollback | `RenderState`, its row and cell iterators, `Style`, `Color` | `RenderState.frame()`, `RenderState.scrolled_off()` |
| Input to the program | `key/`, `mouse/`, `focus.h`, `paste.h`, `size_report.h`, `modes.h`, `color_scheme.h` encoders | `KeyEncoder`, `MouseEncoder`, `encode_focus`, `encode_paste`, ... | |
| Text out | `formatter.h`: the terminal's contents as plain text or VT | `Formatter` | |
| Widths | `unicode.h`: a codepoint's and a grapheme's width, as libghostty measures them | `codepoint_width`, `grapheme_width` | |

Later releases cover the rest, each of which has its own object lifetimes and callbacks to design,
so each waits for its own design rather than a mirror rushed into the first release:
selection and its gestures (`selection.h`), search (`search.h`), tracked grid references (`grid_ref_tracked.h`),
saving and restoring a terminal (`snapshot.h`), the standalone OSC and SGR parsers,
and kitty graphics (`kitty_graphics.h`), which counterweight's [#441](https://github.com/JoshKarpel/counterweight/issues/441) wants.

**The screen helpers are what replaces `emulator.py`'s cffi loops:**

- **`frame()` returns `Row` values, and an unchanged row is the same object.**
  evp keeps each row it read by libghostty's row id, and hands back the same `Row` for it while the row is unchanged,
  so a consumer that keeps derived data by row (`Emulator` shares unchanged rows by identity) skips them for free.
  The dirty flag alone can't say "unchanged", since a scroll marks every row dirty,
  and the scroll is the case this plan exists to make fast.
  A row's id follows its content through a scroll, with or without scrollback, and through a rewrite in place,
  so `frame()` also reuses a dirty row's `Row` when its raw cells match the ones it read,
  and a scroll reads only the rows that are new.
  Equal raw cells aren't enough on their own, and the spike's tests reproduce both of these:
  libghostty reuses a freed style id within a page, so `frame()` reads each of the row's style ids' styles again,
  and a cell's codepoints after its first live outside its raw value,
  so a row holding a multi-codepoint grapheme cluster is always read again.
  A scroll region gives every row on its page a new id, rows outside the region included,
  so a program that scrolls a region has every row read again.
- **A row's cells come back as parallel sequences**, its grapheme clusters as `str`s, their widths, and their style indices,
  one entry per column, so a row of 120 cells is a handful of objects, not 120.
  A wide character's second column is an empty grapheme of width 0.
- **Styles are indices into the terminal's style table**, with each frame and each `scrolled_off()` result
  carrying the styles added since the last of either, so a style always arrives no later than the first row that uses it.
  libghostty's style ids mean something only within a page, so the helper interns styles itself, terminal-wide,
  and a consumer converts each style once, by index.
- **`scrolled_off()` returns the rows that scrolled into the scrollback since the last call**, captured natively,
  so the doubling search `emulator.py` does to keep capturing affordable moves into evp.
  Its result's `has_gap` is true when rows were lost since the last call:
  more scrolled off than the scrollback holds, the program cleared the scrollback (`ESC[3J`), or a resize reflowed it.
  A consumer keeping its own history then knows to mark the gap or rebuild.
  It's a flag, not an exception, because a gap is the program's doing, not a mistake by evp's caller.
- **A terminal has at most one `RenderState`.**
  libghostty lets a second render state take the first's dirty flags,
  which would make `frame()` hand back cached rows whose content changed.
  So making a second `RenderState` for a terminal raises while the first is alive:
  that's a mistake by the caller, so evp refuses it rather than documenting it.

**What stays in counterweight** is what depends on counterweight: matching libghostty's columns to counterweight's own
`grapheme_width` (see "The screen painter" in [canvas-and-embedding](https://github.com/JoshKarpel/counterweight/blob/43ad2e1477994716b3254626f245af42407944f4/plans/canvas-and-embedding.md)),
colors as `Color` and `IndexedColor`, and the swapped colors of inverse and invisible cells.
It runs once per changed row, as now.
Whether counterweight's `input_encoding` gives way to evp's encoders is a separate decision, after this plan:
its pure functions are tested and work, and swapping them changes nothing this plan fixes.

## Which language?

The binding is native code either way; the question is what it's written in and what it builds Ghostty with.
Ghostty's `main` needs Zig 0.17.0 (`minimum_zig_version` in its `build.zig.zon`), and Ghostty checks the version at build time,
so whichever is chosen builds Ghostty with exactly the Zig its Ghostty commit names.

| | Rust: PyO3 and maturin | Zig: [ziggy-pydust](https://github.com/spiraldb/ziggy-pydust) | C helper: cffi API mode |
| --- | --- | --- | --- |
| Talks to Ghostty through | the C API, via [libghostty-rs](https://github.com/Uzaaft/libghostty-rs) | Ghostty's exported Zig modules (`vt`, `vt_c`), or its C API | the C API |
| Builds Ghostty | libghostty-rs's `build.rs`, at a pinned commit, statically | Ghostty as a Zig dependency, in the same build | Zig, separately, then links |
| Toolchains | Rust and Zig | Zig | a C compiler and Zig |
| Python packaging | maturin, as waxy | pydust's own, built around Poetry | setuptools |
| Precedent | waxy: its build, release workflow, stubs and habits | none | none |
| Status | PyO3 is widely used; libghostty-rs has had 5 releases since March 2026 (0.2.2 in September), about 178,000 downloads, and two main contributors | 0.26.0 in September 2025, the last commit not from a bot in February 2026; supports Zig 0.14 (README) or 0.15 (`pyproject.toml` on `main`) | cffi is mature; the helper is ours to write |

**ziggy-pydust is the closest fit in principle.**
It shares Ghostty's language, so evp could import Ghostty's Zig API directly, with no C ABI between them and no bindgen,
and needs one toolchain instead of two.
Ghostty exports those modules for downstream use (`src/build/GhosttyZig.zig`), and supports being built as a dependency.

**Today it doesn't fit, because of Zig's version.**
Zig doesn't keep source compatibility between minor releases, Ghostty's `main` needs 0.17, and pydust supports 0.15 at newest,
with its last release a year old.
Building the two in one Zig build means porting pydust to 0.17 first, and keeping it ported as Ghostty moves on:
in practice, maintaining a fork of pydust as well as evp.
Building Ghostty separately with 0.17 and pydust with 0.15 works over the C ABI, but gives up the Zig API, which was the reason to choose it.
Ghostty's Zig API is also less stable than its C API, which Ghostty checks against an ABI type manifest (`test-lib-vt-schema`),
so binding to it would tie evp to Ghostty's internal churn.

**Recommendation: Rust, on libghostty-rs's `libghostty-vt` crate.**
It's waxy's toolchain and release flow, and most of what a general binding needs already exists in Rust:

| libghostty-rs | What it is | Lines |
| --- | --- | --- |
| `libghostty-vt` | A safe Rust API over every area of the C API, its ownership and lifetimes worked out, encapsulating 593 uses of `unsafe`, with 117 unit tests and integration tests of lifetimes and allocators | 19,690 |
| `libghostty-vt-sys` | `build.rs`: clone Ghostty at a pinned commit, `zig build`, pkg-config, Windows and Apple specifics | 582 |
| | the bindgen script, and the bindings it generates | 181, 5,712 |

The build logic alone wouldn't be worth a dependency; evp could carry its own in about 800 lines.
The safe API is what's worth it: evp's low layer becomes PyO3 classes over safe Rust types,
with no `unsafe` of its own beyond direct calls into `libghostty-vt-sys` for what the safe API doesn't wrap yet
(in 0.2.2, `size_report.h`'s encoder, which the first release lists),
so raw pointer mistakes like `convert_row`'s overrun can't happen outside those calls,
and a fast helper's loop runs over the same safe types, at native speed.
Its `master` exposes what the screen helpers need: overscan, `next_dirty`, a row's `id`, `dirty` and `viewport_y`,
`cells_raw`, and a cell's `style` and `graphemes`.
The newest release, 0.2.2, has only a row's `dirty` and a cell's `style` and `graphemes`,
so evp builds on a git pin of `master` until libghostty-rs's next release,
at the newest commit outside the cooldown (`d2036ba`, from 2026-10-09, whose Ghostty needs Zig 0.16),
and evp's first release waits for that one rather than releasing on the git pin.
What this costs: two toolchains to build evp (Rust and Zig),
dependence on libghostty-rs's cadence for new Ghostty commits and for wrapping new C APIs
(or overriding its source with `GHOSTTY_SOURCE_DIR`, and calling `libghostty-vt-sys` directly for what isn't wrapped yet),
and an `sdist` that needs network access, since its `build.rs` clones Ghostty.
Revisit pydust if it supports Ghostty's Zig version; evp's Python API wouldn't change.

## How is it built and released?

- **Wheels** for manylinux (x86_64, aarch64), macOS (arm64, x86_64) and Windows (x86_64),
  from `PyO3/maturin-action`.
  waxy builds only on each runner's native architecture (x86_64 Linux and Windows, arm64 macOS),
  so aarch64 Linux and x86_64 macOS are targets waxy doesn't have.
  Each needs Ghostty built for that target.
  `libghostty-vt-sys` cross-compiles: maturin with `--zig` builds an aarch64 Linux wheel on an x86_64 host,
  tagged `manylinux_2_17`, in about 3 minutes 50 seconds cold.
  But a cross-built wheel can't be tested where it's built, and GitHub has a native runner for every target
  (`ubuntu-24.04-arm`, `macos-15-intel`), so each target builds and tests on its own runner,
  and cross-compiling is the way out if a runner goes away.
  counterweight runs only on Linux and macOS (it uses `pty` and `termios`), but evp only feeds bytes
  and reads the screen, so it's useful on Windows too, as waxy is.
  libghostty-rs builds and tests `libghostty-vt` for Windows x86_64 (MSVC and GNU) in CI on every push to `master`,
  so Windows costs one more build target. Windows on ARM waits until libghostty-rs tests it.
- **One wheel per platform, through the limited API.**
  PyO3's `abi3` feature builds one wheel for every Python from the oldest it names;
  waxy instead builds one per Python version.
  Built with `abi3`, `frame()` takes 7 to 22% longer (0.1 to 2.6 µs a frame),
  and the counterweight prototype 1 to 7% longer, since its own Python work dominates.
  That buys one wheel per platform instead of three, and wheels for Pythons not yet released.
  What it costs: those microseconds, and no wheel for free-threaded CPython, which can't load an `abi3` wheel.
- **Zig wherever evp is built**, from mise, pinned in `mise.toml`,
  at the version the Ghostty commit pinned by libghostty-rs requires.
  That's 0.15.2 for `libghostty-vt` 0.2.2, the newest release (its Ghostty is `a887df42`),
  0.16.0 for the `master` commit evp pins, and 0.17.0 for `master` since 2026-10-23,
  so a libghostty-rs bump can bring a Zig bump with it.
  `libghostty-vt-sys` runs `zig` from `PATH` unless its `ZIG` variable names another.
  evp has no Zig of its own and no Ghostty build logic, but `libghostty-vt-sys` has no prebuilt library:
  its `build.rs` clones Ghostty at its pinned commit and runs `zig build` (or builds a local checkout named by `GHOSTTY_SOURCE_DIR`).
  Its opt-in `pkg-config` feature links an installed libghostty-vt instead, which a wheel can't rely on.
  So Zig is needed by the CI that builds wheels and by whoever works on evp,
  not by anyone who installs a wheel, and not by counterweight's contributors.
- **Pinned and locked**: `Cargo.lock` pins libghostty-rs, whose `build.rs` pins Ghostty's commit,
  and the usual cooldown applies to both.
- **Type stubs** ship with the package, checked against the module, as waxy's are.

## What does the repository need?

The same scaffolding as [waxy](https://github.com/JoshKarpel/waxy), copied and then adjusted for Zig and Ghostty.
What evp adds is mostly Zig on every runner that compiles, and a cache for Ghostty's build.

- **Every tool comes from `mise.toml`**, locally and in CI alike: Rust (with clippy and rustfmt), Zig, just and uv,
  with Python's dev tools (ruff, mypy, maturin, pre-commit) in uv's dev group.
  Every workflow job that runs a tool installs them with [`jdx/mise-action`](https://github.com/jdx/mise-action),
  with mise itself pinned by the action's `version` input,
  so CI runs the versions a contributor runs, and a version bump is one reviewable change to `mise.toml`.
  That's a departure from waxy, whose CI installs Rust, just and uv with separate actions.
- **CI** (`.github/workflows/ci.yml`): on pushes to `main`, pull requests, and by hand.
  A matrix of Linux, macOS and Windows by each supported Python
  runs `just fix` (pre-commit over every file) and `just test` (mypy, pytest, and `cargo test`, with `-D warnings`),
  and caches Cargo's target directory, since every cell otherwise builds Ghostty from a clean clone;
  the spike's measurement of that build says how much the cache matters.
- **Release** (`.github/workflows/release.yml`): on a published GitHub release,
  builds a wheel per platform (and per Python, unless `abi3` wins) with `PyO3/maturin-action`, and an sdist,
  then publishes them with `pypa/gh-action-pypi-publish` through
  [trusted publishing](https://docs.pypi.org/trusted-publishers/):
  only the publish job grants `id-token: write`, it runs in a `pypi` environment, and no API token exists.
  evp also needs a pending publisher on PyPI for `evp` (this repository, `release.yml`, the `pypi` environment)
  before the first release.
  On macOS and Windows maturin-action builds on the runner, so `mise-action` ahead of it puts Zig on `PATH`;
  on Linux it builds in a container, which needs mise of its own (see below).
  A pending publisher doesn't reserve the name: if anyone else uploads `evp` first, PyPI discards it,
  so step 2's pre-release follows the pending publisher closely.
- **Linux wheels build in maturin-action's manylinux container**, unlike waxy's.
  maturin-action (v1) builds on the runner itself unless it's given `manylinux`, `container`, or a cross `target`,
  and waxy gives none, so its Linux wheels are tagged `manylinux_2_34`: they need glibc 2.34 or newer.
  With `manylinux: auto`, maturin-action builds in `quay.io/pypa/manylinux2014_x86_64`,
  and a spike wheel on `libghostty-vt` 0.2.2 built there is tagged `manylinux_2_12`
  (its newest glibc symbol is `GLIBC_2.10`), against `manylinux_2_34` for the same crate built on an Ubuntu 24.04 host.
  Ghostty's own code needs no newer glibc, so the container is what decides how old a Linux evp installs on.
  What that costs: Zig has to be installed inside the container, since only the runner's workspace is mounted,
  and maturin-action forwards only variables with prefixes like `CARGO_`, `RUST` and `PYO3_`, so `ZIG` doesn't reach it.
  `before-script-linux` runs in the same shell as `maturin build`, so it installs mise and runs `mise install` from the repository's `mise.toml`:

  ```bash
  curl -fsSL https://mise.run | MISE_VERSION=v2026.10.4 MISE_INSTALL_MUSL=1 sh
  export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"
  mise trust
  mise install
  ```

  `MISE_INSTALL_MUSL=1` matters: mise's default Linux build needs glibc 2.18, and `manylinux2014` has 2.17.
  `MISE_VERSION` pins mise itself, which the installer otherwise takes from whatever was released last, outside any cooldown.
- **Docs** (`.github/workflows/docs.yml`): builds the extension and an mkdocs site with `--strict`,
  and deploys it to GitHub Pages on pushes to `main`.
- **Dependabot** for GitHub Actions, weekly.
- **pre-commit**: `pre-commit-hooks`, `check-jsonschema`'s workflow and Dependabot checks,
  `just --fmt`, and `just fix`'s formatters and linters (ruff, `cargo fmt`, clippy).
- **A justfile** with waxy's recipes, grouped by Python and Rust, including its exports of
  `PYO3_ENVIRONMENT_SIGNATURE` and `PYO3_PYTHON`, which keep maturin and plain `cargo`
  from invalidating each other's builds: with Ghostty in the dependency tree, a spurious rebuild costs far more than it does in waxy.

## Why its own repository?

evp lives here, as waxy lives apart from counterweight, released on its own schedule,
so counterweight's contributors and CI stay pure Python: nothing they run builds Rust or Ghostty.
What that costs: a counterweight change that needs a new libghostty-vt feature is two pull requests,
one here and one there, with a release of evp between them.

## Work

Steps 1 to 3 happen in this repository; steps 4 and 5 in counterweight.

1. **Spike** (decides the open questions below):
   a PyO3 module on `libghostty-vt` from a git pin of libghostty-rs's `master`, with `Terminal.feed` and a bulk `snapshot`,
   built on Linux, macOS and Windows by the CI workflow (see [What does the repository need?](#what-does-the-repository-need)).
   Measure import plus the first terminal (target: a few milliseconds, against 190 ms),
   counterweight's `benchmarks snapshot` scenarios against today's,
   `abi3` against a per-version build, and how long a clean build of Ghostty takes in CI, with and without the cache.
   Find out whether a row's id follows its content through a scroll, and through a rewrite of the row in place
   (see [The binding's API](#the-bindings-api)).
   Check whether `libghostty-vt-sys` cross-compiles to the wheel targets,
   and whether pydust supports Zig 0.17 by then.
2. **The rest of the scaffolding**: the release and docs workflows, Dependabot, pre-commit and the justfile,
   and the pending publisher on PyPI.
   A pre-release published to PyPI from a GitHub release proves the release workflow end to end.
3. **evp**: the first release's areas (see [The binding's API](#the-bindings-api)),
   tests of its own, stubs, and docs.
4. **`counterweight.emulator` on evp**, behind the same `Emulator` and `Screen`:
   counterweight's `tests/test_emulator.py` is the contract, unchanged.
   Delete the cffi code, the row and cell caches evp replaces, and the overscan search.
   Run `benchmarks snapshot` against today's numbers, the inline workloads for startup,
   and a mutation testing pass over the new `emulator.py`.
5. **Drop pyghostty from counterweight**: remove the dependency, and update counterweight's `CLAUDE.md` Key Dependencies,
   `emulator.py`'s module docstring, and the emulator notes in
   [canvas-and-embedding](https://github.com/JoshKarpel/counterweight/blob/43ad2e1477994716b3254626f245af42407944f4/plans/canvas-and-embedding.md).

## What did the spike find?

The spike is a PyO3 module on the pinned `libghostty-vt` with `Terminal` (`feed`, `resize`, modes, title, colors)
and `RenderState.frame()`, the screen helper described above, without overscan or `scrolled_off()`.
`spike/emulator.py` is counterweight's `Emulator.snapshot` rebuilt on it, reusing counterweight's own conversions,
and `spike/bench.py` checks that it returns the same rows, cursor and modes as counterweight's `Emulator`
after every scenario of counterweight's `benchmarks snapshot`, then times both the way that benchmark does.
Best times per snapshot of a 120×40 screen, on a 2-core VM, with a per-version build:

| After | pyghostty µs | evp prototype µs | evp `frame()` alone µs |
| --- | --- | --- | --- |
| nothing | 65 | 10 | 1.5 |
| a progress bar rewriting its row | 75 | 10 | 1.7 |
| a plain line, scrolling | 445 | 51 | 11 |
| a line of wide characters, scrolling | 522 | 48 | 12 |
| a line with every word colored, scrolling | 3,637 | 73 | 29 |

The colored scroll falls fiftyfold because `frame()` reuses the rows that only moved,
and converts each style once rather than once per row.
What remains of the prototype's time is Python: a dict lookup per row, and `cells_for` for the new row's cells.

Startup, the best of seven fresh processes:
importing evp takes 0.4 ms, and a terminal with its render state another 0.03 ms.
Making counterweight's first `Emulator` takes 173 ms, the cffi parsing [Why own the binding?](#why-own-the-binding) traces.

The cross-compile check and the measurement of `abi3` are under [How is it built and released?](#how-is-it-built-and-released).
ziggy-pydust still supports only Zig 0.15 on its default branch, with no release since September 2025,
and only dependency-bot commits since May 2026.

The CI workflow builds and tests on Linux (x86_64 and arm64), macOS (arm64 and x86_64) and Windows,
for Python 3.13 to 3.15, but hasn't run yet, so Ghostty's build time in CI, with and without the cache, is still unmeasured.

## Decisions

- **Language: Rust**, on libghostty-rs. ziggy-pydust doesn't support Ghostty's Zig.
- **`abi3`**: one wheel per platform, for a few microseconds a frame.
- **A native runner per wheel target**, since `libghostty-vt-sys` cross-compiles but a cross-built wheel goes untested.

## Risks

- **libghostty-vt's C API is pre-1.0**, so new Ghostty commits can change it; the pin is what contains that.
- **evp's first release waits on libghostty-rs's next one**, which has no date;
  the spike and step 3's work run on a git pin of `master`, but evp doesn't release on one.
- **libghostty-rs has two main contributors.** It's licensed MIT or Apache-2.0, so if it stalls, evp can fork it
  and keep it current with Ghostty's C API itself: about 20,000 lines to own, so the risk is work, not a dead end.
- **Ghostty's build time in CI is unmeasured** until CI first runs.
  Locally, a cold build of the pinned Ghostty takes 2 minutes 24 seconds and 800 MB on a 2-core VM.

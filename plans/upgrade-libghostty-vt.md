# Plan: Upgrade libghostty-vt Past 0.2.2

Artifact: https://claude.ai/code/artifact/c11e0675-cef5-4c6b-bbf4-878f9eaf2223

evp builds on libghostty-vt 0.2.2, the newest release of [libghostty-rs](https://github.com/Uzaaft/libghostty-rs),
and the Ghostty commit it pins (`a887df42`, built with Zig 0.15.2).
libghostty-rs's `master` has since gained most of what evp's screen helpers would rather build on.
This plan covers what evp gains by moving past 0.2.2, what changes in evp when it does, and when to do it.
It doesn't cover binding the C APIs evp doesn't bind yet (selection, search, kitty graphics and the rest):
each of those waits for its own design, on whichever release is current then.

## What does 0.2.2 lack?

Everything below is missing from the C API of the Ghostty that 0.2.2 builds, not just from its Rust wrapper,
so calling `libghostty-vt-sys` directly can't fill the gap.
The 0.2.2 column is how evp works around each one today.

| On `master` | What evp does on 0.2.2 | What the workaround costs |
| --- | --- | --- |
| A row's raw cells in one call (`cells_raw`) | Reads each cell's raw value with two calls (`select`, then `raw_cell`) | Most of `frame()`'s time on a scroll (see below) |
| Row ids that follow a row through a scroll | Finds a moved row by comparing raw cells with each row of the last frame | Little: a comparison usually stops at the first cell |
| Overscan: rows above the screen in the render state | Reads scrolled-off rows a cell at a time through grid references, each of which libghostty resolves by walking the scrollback's pages | About 25 µs a frame for a program scrolling one 120-column row a frame, with a 10,000-row scrollback |
| A scrollback limit in lines (`set_scrollback_max_lines`) | A byte limit, fixed when the terminal is made, which libghostty frees a page (a few hundred KB) at a time | A caller that wants a number of lines works out a byte budget with headroom and trims to the count itself |
| `Snapshot::clean` | Clears each row's dirty flag, then the frame's | One call per row |
| `Snapshot::cursor` | Reads the cursor's fields one call at a time | A few calls per frame |

Two behaviors differ too:

- **Erasing the scrollback.**
  `scrolled_off()` follows a tracked grid reference (an anchor) on the row that was at the top of the screen at its last call.
  After `ESC [ 3 J` the anchor lands back at the top of the screen,
  so an erase is caught only when the scrollback held rows at the last call, from its row count shrinking.
  Rows that scroll off and are erased before the next call, when the last call found the scrollback empty,
  disappear without `has_gap`.
  `tests/test_render_state.py` pins that limit.
  With overscan and row ids, the row `scrolled_off()` last returned not being found is a sure sign of a gap.
- **Long grapheme clusters.**
  0.2.2's Ghostty keeps every codepoint of a cluster; the Ghostty `master` pins keeps the first 65.
  Its tests accept either.

## What does it gain in speed?

`spike/bench.py` times counterweight's `benchmarks snapshot` scenarios, a 120×40 screen, on a 2-core VM.
`frame()` on `master` is from the first spike, which built on libghostty-rs `d2036ba`
and found moved rows by row id and `cells_raw`; on 0.2.2 it's evp as it is now.
Best µs per snapshot:

| After | `frame()` on 0.2.2 | `frame()` on `master` | counterweight prototype on 0.2.2 | prototype on `master` |
| --- | --- | --- | --- | --- |
| nothing | 2.8 | 1.5 | 12 | 10 |
| a progress bar rewriting its row | 4.3 | 1.7 | 13 | 10 |
| a plain line, scrolling | 42 | 11 | 52 | 51 |
| a line of wide characters, scrolling | 42 | 12 | 52 | 48 |
| a line with every word colored, scrolling | 71 | 29 | 82 | 73 |

`frame()` is two to four times faster on `master`, nearly all of it from reading a row's raw cells in one call.
Through counterweight's prototype the gain is 0 to 20%, since counterweight's own Python work dominates.
Against pyghostty today (435 µs for a plain line, 3,621 µs for a colored one), both are an order of magnitude ahead,
so the upgrade isn't urgent for counterweight's speed.

## What changes in evp?

- **`frame()` reads raw cells with `cells_raw`**, one call per row, and keeps finding moved rows by their cells.
  Content matching already handles what row ids do, and more: a scroll region gives every row on its page a new id,
  where matching by cells still finds the rows it moved.
  Adopt row ids only if a measurement shows the scan costing something worth saving.
- **`Terminal` takes a scrollback limit in lines**, replacing `max_scrollback_bytes` with `scrollback_lines`,
  set with `set_scrollback_max_lines`, with the byte limit lifted.
  That's a breaking change to evp's Python API, so it waits for a minor release and a changelog entry.
  counterweight's byte budget and trimming go with it.
- **`scrolled_off()` keeps its anchor to count the rows that scrolled off**, which stays exact through
  the scrollback freeing pages, and reads them through overscan instead of grid references
  if a fast-scrolling workload (thousands of rows a frame) shows the grid references costing enough.
  Changing the overscan request redraws every row on the next update, so request it in steps, as counterweight does now.
- **The erase gap is re-probed on the new Ghostty.**
  If the anchor still can't tell an erase from no change, `scrolled_off()` remembers the id of the last row it returned
  and reports a gap when that row is gone.
- **`frame()` calls `clean` and `cursor`** in place of the per-row and per-field calls.
- **arm64 macOS builds on `macos-latest` again.**
  On the macOS 26 image, Zig 0.15.2 can't link its own build runner against libSystem,
  so `ci.yml` and `build.yml` run on `macos-15`; once the new Zig builds Ghostty on `macos-latest`, they move back.

`Row`, `Style`, `Frame`, `ScrolledOff` and `History` don't change.

## What does upgrading take?

1. Wait for the libghostty-rs release after 0.2.2, plus the 7-day cooldown.
   0.2.2 is from 2026-09-28, and no date is announced for the next release.
2. Bump `libghostty-vt` and set Zig to what the newly pinned Ghostty names (0.17.0 for `master` today),
   as `docs/maintaining.md` describes.
3. Port to the API changes evp touches:
   `Terminal::new` takes `(cols, rows)` instead of `Options`, and `title()` returns bytes (`fb9378e`).
   The other breaking changes since 0.2.2 are in APIs evp doesn't call
   (OSC command types, clipboard MIME types, build info, the `sys` hook setters, prompt-based viewport scrolling,
   and `graphemes_buf`, which evp avoids for `graphemes_utf8`).
4. Make the changes above, updating the tests that pin 0.2.2's limits.
5. Rerun `spike/bench.py` and `spike/counterweight-tests.sh`, and record the new numbers here.

## Risks

- **`master` changes fast.**
  Many of its recent commits are breaking, so the release after 0.2.2 may differ from what this plan read;
  step 3's list is to be redone against the release itself.
- **Zig moves two minor versions**, from 0.15 to 0.17, which every contributor and CI runner picks up through `mise.toml`.

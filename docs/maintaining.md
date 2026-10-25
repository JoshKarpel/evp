# Maintaining

## Building

evp links libghostty-vt statically, and libghostty-rs's `libghostty-vt-sys` builds it:
its build script clones the Ghostty commit it pins and runs `zig build` with the `zig` on `PATH`.
So working on evp needs Zig as well as Rust, both from `mise.toml`, and network access for a clean build.
Installing a wheel needs neither.

A clean build compiles Ghostty, which takes a few minutes,
so CI caches Cargo's target directory, keyed on `Cargo.lock` and `mise.toml`.
The justfile exports `PYO3_ENVIRONMENT_SIGNATURE` and `PYO3_PYTHON`,
so `maturin` and plain `cargo` share that directory rather than invalidating each other's builds.

## Upgrading libghostty-vt

Ghostty refuses to build with any Zig but the one its `build.zig.zon` names,
so a new libghostty-vt release can need a new Zig:

1. Bump `libghostty-vt` in `Cargo.toml` and run `cargo update -p libghostty-vt`.
2. Find the Ghostty commit the new `libghostty-vt-sys` pins (`GHOSTTY_COMMIT` in its `build.rs`),
   and set `zig` in `mise.toml` to the `minimum_zig_version` in that commit's `build.zig.zon`.
3. Run `just check`, then `spike/counterweight-tests.sh`,
   which runs counterweight's emulator tests against evp.

[`plans/upgrade-libghostty-vt.md`](https://github.com/JoshKarpel/evp/blob/main/plans/upgrade-libghostty-vt.md)
covers the next release and what evp gains from it.

## Adding support for a new Python version

evp builds one `abi3` wheel per platform for every CPython from 3.13 on,
so a new Python needs no new wheels. Add it to CI's `python-version` matrix,
and add its `Programming Language :: Python :: 3.X` classifier to `pyproject.toml`.
If PyO3 doesn't support it yet, upgrade PyO3 in `Cargo.toml` first.

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

## Releasing

`.github/workflows/build.yml` builds an `abi3` wheel on each platform's own runner,
tests it against every supported Python, and builds an sdist.
It runs on every push and pull request, alongside CI, so the release build is checked before a release needs it.
Publishing a GitHub release runs `.github/workflows/release.yml`, which calls `build.yml`
and publishes what it built to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/).
Linux wheels build in maturin-action's `manylinux2014` container, so they install on glibc 2.17 and newer;
the container installs mise and the tools in `mise.toml` for itself, since it only sees the workspace.

To release, set `version` in `Cargo.toml`, which maturin gives the wheels and sdist too
(`pyproject.toml` declares the version `dynamic`, so there's no second copy to forget),
add its entry to `docs/changelog.md`, then publish a GitHub release tagged `v<version>`.
`release.yml` refuses to publish anything whose version isn't the tag's.

Publishing relies on two pieces of setup outside the repository:

- A trusted publisher on PyPI for `evp`: owner `JoshKarpel`, repository `evp`,
  workflow `release.yml`, environment `pypi`.
- A `pypi` environment in the repository's settings, with a required reviewer,
  so a release waits for approval before anything reaches PyPI, where a version can never be uploaded twice.

`build.yml` pins maturin and mise to the versions `uv.lock` and `ci.yml` use; keep them in step when those move.

## Upgrading libghostty-vt

Ghostty refuses to build with any Zig but the one its `build.zig.zon` names,
so a new libghostty-vt release can need a new Zig:

1. Bump `libghostty-vt` in `Cargo.toml` and run `cargo update -p libghostty-vt`.
2. Find the Ghostty commit the new `libghostty-vt-sys` pins (`GHOSTTY_COMMIT` in its `build.rs`),
   and set `zig` in `mise.toml` to the `minimum_zig_version` in that commit's `build.zig.zon`.
3. Run `just check`, then `spike/counterweight-tests.sh`,
   which runs counterweight's emulator tests against evp.
   Several tests pin libghostty behavior that its own docs describe differently (`CLAUDE.md` lists them),
   so a failure there can mean Ghostty changed the behavior, not that evp broke.
4. While Zig is 0.15, CI builds arm64 macOS on `macos-15`,
   since Zig 0.15.2 can't link on GitHub's macOS 26 image (`macos-latest`).
   With a newer Zig, try `macos-latest` in `ci.yml` and `build.yml`.

[`plans/upgrade-libghostty-vt.md`](https://github.com/JoshKarpel/evp/blob/main/plans/upgrade-libghostty-vt.md)
covers the next release and what evp gains from it.

## Adding support for a new Python version

evp builds one `abi3` wheel per platform for every CPython from 3.13 on,
so a new Python needs no new wheels. Add it to CI's `python-version` matrix and to the versions `build.yml` tests the wheel against,
and add its `Programming Language :: Python :: 3.X` classifier to `pyproject.toml`.
If PyO3 doesn't support it yet, upgrade PyO3 in `Cargo.toml` first.

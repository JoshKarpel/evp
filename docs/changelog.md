# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased](https://github.com/JoshKarpel/evp/commits/main)

### Added

- `Terminal`, a terminal emulator fed the bytes a program writes.
- `RenderState`, which reads what a terminal shows a frame at a time with `frame`,
  the rows that scroll off it with `scrolled_off`, and its scrollback with `history`.

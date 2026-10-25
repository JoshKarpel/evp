# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased](https://github.com/JoshKarpel/evp/commits/main)

### Added

- `Terminal`, a terminal emulator fed the bytes a program writes,
  with callbacks for its replies to the program, the bell, title, working directory, clipboard writes,
  and the size, color scheme and device attributes it reports (`DeviceAttributes`).
- `RenderState`, which reads what a terminal shows a frame at a time with `frame`,
  the rows that scroll off it with `scrolled_off`, and its scrollback with `history`.
- `KeyEncoder` and `MouseEncoder`, which encode key and mouse events as the terminal's modes say,
  and `encode_focus`, `encode_paste`, `is_paste_safe`, `encode_color_scheme` and `encode_size_report`.
- `Formatter`, which writes what a terminal shows as plain text, VT sequences or HTML.
- `codepoint_width` and `grapheme_width`, which measure text as the terminal lays it out.

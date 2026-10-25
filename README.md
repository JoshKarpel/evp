# evp

A Python binding to [libghostty-vt](https://ghostty.org), the terminal emulator at the core of Ghostty,
built with [PyO3](https://pyo3.rs/) on [libghostty-rs](https://github.com/Uzaaft/libghostty-rs)
and packaged with [maturin](https://www.maturin.rs/).
Feed it the bytes a program writes to its terminal, and read back what that terminal shows, as values.

```python
from evp import RenderState, Terminal

terminal = Terminal(80, 24, max_scrollback_bytes=10_000_000)
state = RenderState(terminal)

terminal.feed(b"hello, \x1b[1;31mworld\x1b[0m\r\n")

frame = state.frame()
print("".join(frame.rows[0].graphemes).rstrip())  # hello, world
```

The name is a pun: EVP, electronic voice phenomena, are the voices ghost hunters claim to record,
and evp is how Python hears from Ghostty.

## Installation

evp is on [PyPI](https://pypi.org/project/evp/), and needs Python 3.13 or newer:

```bash
pip install evp
```

To build it from source, install [mise](https://mise.jdx.dev/),
which provides Rust, Zig, just and uv at the versions in `mise.toml`, then:

```bash
mise install
just build
```

The first build clones and compiles Ghostty, which takes a few minutes.

## Links

- [Documentation](https://joshkarpel.github.io/evp)
- [libghostty-rs](https://github.com/Uzaaft/libghostty-rs), the Rust crate evp builds on
- [Ghostty](https://github.com/ghostty-org/ghostty)
- [counterweight](https://github.com/JoshKarpel/counterweight), the terminal UI framework evp was written for

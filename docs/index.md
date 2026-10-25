# evp

A Python binding to [libghostty-vt](https://ghostty.org), the terminal emulator at the core of Ghostty,
built with [PyO3](https://pyo3.rs/) on [libghostty-rs](https://github.com/Uzaaft/libghostty-rs)
and packaged with [maturin](https://maturin.rs/).
Feed it the bytes a program writes to its terminal, and read back what that terminal shows,
as values.

The name is a pun: EVP, electronic voice phenomena, are the voices ghost hunters claim to record,
and evp is how Python hears from Ghostty.

## Reading a terminal

```python
from evp import RenderState, Terminal

replies: list[bytes] = []
terminal = Terminal(80, 24, max_scrollback_bytes=10_000_000, on_write_pty=replies.append)
state = RenderState(terminal)

terminal.feed(b"hello, \x1b[1;31mworld\x1b[0m\r\n")

styles = []
frame = state.frame()
styles.extend(frame.new_styles)
for row in frame.rows:
    text = "".join(row.graphemes).rstrip()
    bold = [styles[index].bold for index in row.styles]
```

`Terminal.feed` takes whatever the program wrote, escape sequences and all,
and `on_write_pty` receives the terminal's answers to the program's queries,
which belong on the program's input.

A `RenderState` reads the terminal: `frame` for what's on the screen,
`scrolled_off` for the rows that scrolled off the top since its last call,
and `history` for the whole scrollback.
A terminal has one render state at a time.

## Reading it every frame

evp is built for callers that read a terminal many times a second, like a terminal UI embedding one.

- **A row that didn't change is the same `Row`.**
  `frame` hands back the last frame's `Row` object for a row that shows the same cells,
  even after a scroll moved it,
  so keep whatever you derive from a row (converted cells, a rendered line) by row and reuse it by identity.
- **Convert each style once.**
  Rows name their cells' styles by index, and `frame`, `scrolled_off` and `history`
  each deliver the styles first used since any of them last did, in index order.
  Append them to a list, convert each once, and look styles up by index.
- **Call `scrolled_off` every frame if you keep the scrollback.**
  The scrollback frees its oldest rows as new ones arrive,
  and `scrolled_off` can return only the rows it still holds;
  `has_gap` says when some were lost.

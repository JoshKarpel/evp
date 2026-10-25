# Performance

These tips are for callers that read a terminal every frame,
like a terminal UI that embeds one.
They're ordered by how much they save, largest first.
Savings are stated as ratios, since absolute times change with the machine and with every release.
The script behind each ratio is
[`benchmarks/tips.py`](https://github.com/JoshKarpel/evp/tree/main/benchmarks/tips.py),
measured on a 120 by 40 terminal against a release build (`just bench-build`).

## Read new scrollback with `scrolled_off`, not `history`

`history` reads every row the scrollback holds, on every call.
`scrolled_off` reads only the rows that scrolled off since its last call,
so its cost follows the program's output rather than the scrollback's length.
On a 1,000-row scrollback, reading after one more line with `scrolled_off`
costs about a thousandth of reading the scrollback with `history`,
and the gap grows with the scrollback.
Keep `history` for occasional reads, such as searching or saving the whole scrollback.

## Reuse what you derive from a row while it's the same `Row`

`frame` returns the same `Row` object for a row that shows what it showed in the last frame,
including a row a scroll moved.
A `Row` hashes by identity, so key whatever you convert it into by the row itself,
and keep only the current frame's rows so rows that left the screen are forgotten:

```python
converted: dict[Row, Line] = {}
...
frame = state.frame()
converted = {row: converted[row] if row in converted else convert(row) for row in frame.rows}
```

Converting a frame this way costs about 2% of converting every row
when a progress bar rewrites one row,
and 10 to 15% when a line scrolls the screen, since only the new row is converted.

## Read a frame every tick

A frame after no output costs about 7% of a frame after a line scrolled the screen,
since it hands back the last frame's rows without reading them again.
There's no need to track whether output arrived before reading a frame.

## Convert each style once, by index

Rows name their cells' styles by index into the styles the render state has delivered,
and each read's `new_styles` delivers the styles first used since the last.
Convert each style into your own type as it's delivered, then look cells up by index:

```python
converted.extend(convert_style(style) for style in frame.new_styles)
cell_styles = [converted[index] for index in row.styles]
```

Converting a screen of colored text this way costs about 40% of converting each cell's style.

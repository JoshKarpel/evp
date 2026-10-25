use std::mem;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use libghostty_vt::render::{CellIteration, CellIterator, Dirty, RowIterator};
use libghostty_vt::screen::{Cell, CellContentTag, CellWide, GridRef, Screen, TrackedGridRef};
use libghostty_vt::style::Id as StyleId;
use libghostty_vt::terminal::{Point, PointCoordinate, PointSpace};
use pyo3::exceptions::PyRuntimeError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString, PyTuple};
use rustc_hash::FxHashMap;

use crate::Owned;
use crate::errors::ghostty_error;
use crate::style::{Color, Style};
use crate::terminal::Terminal;

/// One row of a frame, as parallel sequences with one entry per column.
///
/// A wide character's grapheme takes its first column, with width 2, and its second column
/// holds an empty grapheme with width 0.
#[pyclass(frozen, module = "evp")]
pub struct Row {
    /// Each column's grapheme cluster, a space where the column is blank.
    #[pyo3(get)]
    graphemes: Py<PyTuple>,
    /// How many columns each grapheme cluster takes: 1, 2 for a wide character, or 0 after one.
    #[pyo3(get)]
    widths: Py<PyBytes>,
    /// Each column's style, as an index into the styles the render state has delivered.
    #[pyo3(get)]
    styles: Py<PyTuple>,
}

/// A row as `frame` last read it, kept so the next frame can hand back the same `Row`.
struct ReadRow {
    row: Py<Row>,
    /// The raw cell values it was read from.
    raw: Vec<Cell>,
    /// For each style id in the row, a column using it and the style index it was read as,
    /// or `None` when the row holds a multi-codepoint grapheme cluster, whose codepoints after the
    /// first are kept outside the raw cells, so equal raw cells don't mean an equal row.
    style_probes: Option<Vec<(u16, u32)>>,
}

impl ReadRow {
    fn clone_ref(&self, py: Python<'_>) -> Self {
        ReadRow {
            row: self.row.clone_ref(py),
            raw: self.raw.clone(),
            style_probes: self.style_probes.clone(),
        }
    }
}

/// Every style a render state has delivered, interned terminal-wide.
///
/// libghostty's style ids mean something only within one page, so evp names styles
/// by these indices instead, and a consumer converts each style once.
struct Styles {
    indices: FxHashMap<Style, u32>,
    /// Styles interned since `frame`, `scrolled_off` or `history` last delivered them, in index order.
    added: Vec<Style>,
}

impl Styles {
    fn new() -> Self {
        let mut styles = Styles {
            indices: FxHashMap::default(),
            added: Vec::new(),
        };
        styles.index(Style::DEFAULT);
        styles
    }

    fn index(&mut self, style: Style) -> u32 {
        let next = u32::try_from(self.indices.len()).expect("fewer than 2^32 distinct styles");
        *self.indices.entry(style).or_insert_with(|| {
            self.added.push(style);
            next
        })
    }

    /// The styles added since the last delivery, as Python objects, which the next delivery won't repeat.
    fn deliver(&mut self, py: Python<'_>) -> PyResult<Py<PyTuple>> {
        let added = self
            .added
            .drain(..)
            .map(|style| Py::new(py, style))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(PyTuple::new(py, added)?.unbind())
    }
}

/// What a terminal shows at one moment, as `RenderState.frame` reads it.
#[pyclass(frozen, module = "evp")]
pub struct Frame {
    /// The terminal's `(columns, rows)`.
    #[pyo3(get)]
    size: (u16, u16),
    /// Every row, top to bottom. A row unchanged since the last frame is the same `Row` object.
    #[pyo3(get)]
    rows: Py<PyTuple>,
    /// The styles first used since the last delivery: the next indices, in order.
    #[pyo3(get)]
    new_styles: Py<PyTuple>,
    /// The cursor's `(x, y, at_wide_tail)`, or `None` when it's hidden or outside the viewport.
    #[pyo3(get)]
    cursor: Option<(u16, u16, bool)>,
    /// What the program's default foreground stands for, as RGB.
    #[pyo3(get)]
    foreground: (u8, u8, u8),
    /// What the program's default background stands for, as RGB.
    #[pyo3(get)]
    background: (u8, u8, u8),
    /// The 256-color palette as the program left it, as 768 bytes of RGB.
    #[pyo3(get)]
    palette: Py<PyBytes>,
}

/// The rows that scrolled off the top of the screen since the last `RenderState.scrolled_off`.
#[pyclass(frozen, module = "evp")]
pub struct ScrolledOff {
    /// The rows, oldest first, as the scrollback holds them now.
    #[pyo3(get)]
    rows: Py<PyTuple>,
    /// The styles first used since the last delivery: the next indices, in order.
    #[pyo3(get)]
    new_styles: Py<PyTuple>,
    /// Whether rows were lost since the last call: more scrolled off than the scrollback holds,
    /// the program erased the scrollback, or a resize rewrapped it.
    #[pyo3(get)]
    has_gap: bool,
}

/// Every row the scrollback holds, as `RenderState.history` reads it.
#[pyclass(frozen, module = "evp")]
pub struct History {
    /// The rows, oldest first.
    #[pyo3(get)]
    rows: Py<PyTuple>,
    /// The styles first used since the last delivery: the next indices, in order.
    #[pyo3(get)]
    new_styles: Py<PyTuple>,
}

/// Where `scrolled_off` last left off: the row at the top of the screen then.
struct Anchor {
    /// Follows its row into the scrollback, where its position counts the rows that scrolled off since.
    row: Owned<TrackedGridRef>,
    screen: Screen,
    size: (u16, u16),
    /// How many rows the scrollback held then.
    scrollback: usize,
}

impl Anchor {
    fn at_top(terminal: &libghostty_vt::Terminal<'static, 'static>) -> PyResult<Self> {
        let top = Point::Active(PointCoordinate { x: 0, y: 0 });
        Ok(Anchor {
            row: Owned(terminal.track_grid_ref(top).map_err(ghostty_error)?),
            screen: terminal.active_screen().map_err(ghostty_error)?,
            size: size(terminal)?,
            scrollback: terminal.scrollback_rows().map_err(ghostty_error)?,
        })
    }
}

fn size(terminal: &libghostty_vt::Terminal<'static, 'static>) -> PyResult<(u16, u16)> {
    Ok((
        terminal.cols().map_err(ghostty_error)?,
        terminal.rows().map_err(ghostty_error)?,
    ))
}

/// Reads what a terminal shows, a frame at a time, and what scrolls off it. A terminal has at most one.
#[pyclass(module = "evp")]
pub struct RenderState {
    terminal: Py<Terminal>,
    is_rendered: Arc<AtomicBool>,
    state: Owned<libghostty_vt::RenderState<'static>>,
    row_iterator: Owned<RowIterator<'static>>,
    cell_iterator: Owned<CellIterator<'static>>,
    /// The last frame's rows, top to bottom. A row libghostty doesn't mark dirty is unchanged
    /// since then, at the same position: a scroll marks every row dirty.
    rows: Vec<ReadRow>,
    styles: Styles,
    anchor: Anchor,
}

impl Drop for RenderState {
    fn drop(&mut self) {
        self.is_rendered.store(false, Ordering::Release);
    }
}

#[pymethods]
impl RenderState {
    #[new]
    fn new(terminal: &Bound<'_, Terminal>) -> PyResult<Self> {
        let borrowed = terminal.borrow_mut();
        let is_rendered = Arc::clone(&borrowed.is_rendered);
        // libghostty lets a second render state take the first's dirty rows,
        // which would make the first hand back rows whose content changed.
        if is_rendered.swap(true, Ordering::AcqRel) {
            return Err(PyRuntimeError::new_err(
                "This terminal already has a RenderState: a second would take the first's dirty rows",
            ));
        }
        let anchor = Anchor::at_top(&borrowed.inner.0);
        drop(borrowed);
        Ok(RenderState {
            terminal: terminal.clone().unbind(),
            is_rendered,
            state: Owned(libghostty_vt::RenderState::new().map_err(ghostty_error)?),
            row_iterator: Owned(RowIterator::new().map_err(ghostty_error)?),
            cell_iterator: Owned(CellIterator::new().map_err(ghostty_error)?),
            rows: Vec::new(),
            styles: Styles::new(),
            anchor: anchor?,
        })
    }

    /// Bring the render state up to date with the terminal and read what it shows.
    fn frame(&mut self, py: Python<'_>) -> PyResult<Frame> {
        let RenderState {
            terminal,
            state,
            row_iterator,
            cell_iterator,
            rows: last_rows,
            styles,
            ..
        } = self;
        let terminal = terminal.borrow_mut(py);
        let snapshot = state.0.update(&terminal.inner.0).map_err(ghostty_error)?;
        let size = (
            snapshot.cols().map_err(ghostty_error)?,
            snapshot.rows().map_err(ghostty_error)?,
        );
        let dirty = snapshot.dirty().map_err(ghostty_error)?;

        let previous = mem::take(last_rows);
        let is_same_size = previous.len() == usize::from(size.1);
        let mut rows = Vec::with_capacity(usize::from(size.1));
        let mut iteration = row_iterator.0.update(&snapshot).map_err(ghostty_error)?;
        while let Some(row) = iteration.next() {
            let unchanged = match dirty {
                Dirty::Clean => is_same_size,
                Dirty::Partial => is_same_size && !row.dirty().map_err(ghostty_error)?,
                Dirty::Full => false,
            };
            let read = match previous.get(rows.len()) {
                Some(last) if unchanged => last.clone_ref(py),
                _ => {
                    let mut cells =
                        RenderStateCells(cell_iterator.0.update(row).map_err(ghostty_error)?);
                    let raw = raw_cells(&mut cells, size.0)?;
                    match find_unchanged(&previous, &raw, &mut cells, styles)? {
                        Some(last) => last.clone_ref(py),
                        None => read_row(py, raw, &mut cells, styles)?,
                    }
                }
            };
            row.set_dirty(false).map_err(ghostty_error)?;
            rows.push(read);
        }
        snapshot.set_dirty(Dirty::Clean).map_err(ghostty_error)?;
        let frame_rows = rows
            .iter()
            .map(|read| read.row.clone_ref(py))
            .collect::<Vec<_>>();
        *last_rows = rows;

        let colors = snapshot.colors().map_err(ghostty_error)?;
        let cursor = if snapshot.cursor_visible().map_err(ghostty_error)? {
            snapshot.cursor_viewport().map_err(ghostty_error)?
        } else {
            None
        };
        let palette: Vec<u8> = colors
            .palette
            .iter()
            .flat_map(|c| [c.r, c.g, c.b])
            .collect();
        Ok(Frame {
            size,
            rows: PyTuple::new(py, frame_rows)?.unbind(),
            new_styles: styles.deliver(py)?,
            cursor: cursor.map(|viewport| (viewport.x, viewport.y, viewport.at_wide_tail)),
            foreground: (
                colors.foreground.r,
                colors.foreground.g,
                colors.foreground.b,
            ),
            background: (
                colors.background.r,
                colors.background.g,
                colors.background.b,
            ),
            palette: PyBytes::new(py, &palette).unbind(),
        })
    }

    /// Read the rows that scrolled off the top of the screen since the last call,
    /// or since the render state was made.
    ///
    /// Each row is read once, as the scrollback holds it at the call.
    /// A program drawing on the alternate screen scrolls nothing off.
    fn scrolled_off(&mut self, py: Python<'_>) -> PyResult<ScrolledOff> {
        let borrowed = self.terminal.borrow_mut(py);
        let terminal = &borrowed.inner.0;
        let screen = terminal.active_screen().map_err(ghostty_error)?;
        if screen != self.anchor.screen {
            // The anchor's screen isn't the one showing, and the one showing has no scrollback of
            // its own (the alternate screen) or couldn't scroll while the other showed (the primary).
            if screen == Screen::Primary {
                self.anchor = Anchor::at_top(terminal)?;
            }
            return Ok(ScrolledOff {
                rows: PyTuple::empty(py).unbind(),
                new_styles: self.styles.deliver(py)?,
                has_gap: false,
            });
        }

        let scrollback = terminal.scrollback_rows().map_err(ghostty_error)?;
        let anchor = &self.anchor.row.0;
        let (start, is_lost) = match anchor.point(PointSpace::History).map_err(ghostty_error)? {
            // History coordinates count from the oldest row, on the screen too, so the anchor's
            // row is the first that scrolled off since, or below the last if none did.
            Some(point) if anchor.has_value() => {
                let start = usize::try_from(point.y).map_or(scrollback, |y| y.min(scrollback));
                // An anchor still on the screen means nothing scrolled off since, so nothing was
                // freed to make room either, and a smaller scrollback means the program erased it
                // (`ESC [ 3 J`), which puts the anchor back at the top of the screen. libghostty-vt
                // 0.2.2 leaves rows that scrolled off and were erased since a call that found the
                // scrollback empty indistinguishable from no rows at all.
                let is_on_screen = anchor
                    .point(PointSpace::Active)
                    .map_err(ghostty_error)?
                    .is_some();
                (start, is_on_screen && scrollback < self.anchor.scrollback)
            }
            // The scrollback freed the anchor's row, and with it rows that scrolled off after it.
            _ => (0, true),
        };
        let has_gap = is_lost || size(terminal)? != self.anchor.size;

        let columns = terminal.cols().map_err(ghostty_error)?;
        let rows = read_history(py, terminal, start..scrollback, columns, &mut self.styles)?;
        self.anchor = Anchor::at_top(terminal)?;
        Ok(ScrolledOff {
            rows,
            new_styles: self.styles.deliver(py)?,
            has_gap,
        })
    }

    /// Read every row the scrollback holds now, oldest first, rewrapped by every resize since it
    /// scrolled off. It reads each row each call, so it's for now and then, not every frame.
    fn history(&mut self, py: Python<'_>) -> PyResult<History> {
        let borrowed = self.terminal.borrow_mut(py);
        let terminal = &borrowed.inner.0;
        let scrollback = terminal.scrollback_rows().map_err(ghostty_error)?;
        let columns = terminal.cols().map_err(ghostty_error)?;
        let rows = read_history(py, terminal, 0..scrollback, columns, &mut self.styles)?;
        Ok(History {
            rows,
            new_styles: self.styles.deliver(py)?,
        })
    }
}

/// Read the scrollback rows `ys`, counted from the oldest.
fn read_history(
    py: Python<'_>,
    terminal: &libghostty_vt::Terminal<'static, 'static>,
    ys: std::ops::Range<usize>,
    columns: u16,
    styles: &mut Styles,
) -> PyResult<Py<PyTuple>> {
    let rows = ys
        .map(|y| {
            let y = u32::try_from(y).expect("fewer than 2^32 scrollback rows");
            let mut cells = HistoryCells::new(terminal, y);
            let raw = raw_cells(&mut cells, columns)?;
            Ok(read_row(py, raw, &mut cells, styles)?.row)
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(PyTuple::new(py, rows)?.unbind())
}

/// Where `read_row` reads a row's cells from: a render state's row, or a scrollback row.
trait Cells {
    fn cell(&mut self, x: u16) -> libghostty_vt::error::Result<Cell>;
    fn style(&mut self, x: u16) -> libghostty_vt::error::Result<libghostty_vt::style::Style>;
    /// Replace `buf` with the cell's whole grapheme cluster.
    fn cluster(&mut self, x: u16, buf: &mut String) -> libghostty_vt::error::Result<()>;
}

struct RenderStateCells<'s>(CellIteration<'static, 's>);

impl Cells for RenderStateCells<'_> {
    fn cell(&mut self, x: u16) -> libghostty_vt::error::Result<Cell> {
        self.0.select(x)?;
        self.0.raw_cell()
    }

    fn style(&mut self, x: u16) -> libghostty_vt::error::Result<libghostty_vt::style::Style> {
        self.0.select(x)?;
        self.0.style()
    }

    fn cluster(&mut self, x: u16, buf: &mut String) -> libghostty_vt::error::Result<()> {
        self.0.select(x)?;
        self.0.graphemes_utf8(buf)
    }
}

/// A scrollback row's cells, through grid references, which libghostty resolves by walking the
/// scrollback's pages, so each cell's reference is resolved once.
struct HistoryCells<'t> {
    terminal: &'t libghostty_vt::Terminal<'static, 'static>,
    y: u32,
    current: Option<(u16, GridRef<'t>)>,
    codepoints: Vec<char>,
}

impl<'t> HistoryCells<'t> {
    fn new(terminal: &'t libghostty_vt::Terminal<'static, 'static>, y: u32) -> Self {
        HistoryCells {
            terminal,
            y,
            current: None,
            codepoints: vec!['\0'; 16],
        }
    }

    fn at(&mut self, x: u16) -> libghostty_vt::error::Result<&GridRef<'t>> {
        if self.current.as_ref().is_none_or(|(at, _)| *at != x) {
            let point = Point::History(PointCoordinate { x, y: self.y });
            self.current = Some((x, self.terminal.grid_ref(point)?));
        }
        Ok(&self.current.as_ref().expect("just set").1)
    }
}

impl Cells for HistoryCells<'_> {
    fn cell(&mut self, x: u16) -> libghostty_vt::error::Result<Cell> {
        self.at(x)?.cell()
    }

    fn style(&mut self, x: u16) -> libghostty_vt::error::Result<libghostty_vt::style::Style> {
        self.at(x)?.style()
    }

    fn cluster(&mut self, x: u16, buf: &mut String) -> libghostty_vt::error::Result<()> {
        let mut codepoints = mem::take(&mut self.codepoints);
        let result = loop {
            match self.at(x)?.graphemes(&mut codepoints) {
                Ok(len) => {
                    buf.clear();
                    buf.extend(&codepoints[..len]);
                    break Ok(());
                }
                Err(libghostty_vt::Error::OutOfSpace { required }) => {
                    codepoints.resize(required, '\0');
                }
                Err(error) => break Err(error),
            }
        };
        self.codepoints = codepoints;
        result
    }
}

/// A row's raw cell values, one per column.
fn raw_cells(cells: &mut impl Cells, columns: u16) -> PyResult<Vec<Cell>> {
    (0..columns)
        .map(|x| cells.cell(x).map_err(ghostty_error))
        .collect()
}

/// A row of the last frame that shows what a dirty row with these raw cells shows, if any.
///
/// libghostty-vt 0.2.2 has no row ids, so a row a scroll moved is found by its cells:
/// a comparison of two rows usually stops at their first cell, so trying every row is cheap.
/// Equal raw cells hold the same codepoints, widths and style ids, but a style id means something
/// only within its page, and a page reuses a freed id for another style, so each id's style is read
/// again from the dirty row.
fn find_unchanged<'r>(
    previous: &'r [ReadRow],
    raw: &[Cell],
    cells: &mut impl Cells,
    styles: &mut Styles,
) -> PyResult<Option<&'r ReadRow>> {
    'candidates: for candidate in previous {
        let Some(probes) = &candidate.style_probes else {
            continue;
        };
        if candidate.raw != raw {
            continue;
        }
        for &(x, index) in probes {
            if styles.index(cells.style(x).map_err(ghostty_error)?.into()) != index {
                continue 'candidates;
            }
        }
        return Ok(Some(candidate));
    }
    Ok(None)
}

/// Read a row from its raw cells, reading a cell's style only for the first cell in the row with its style id.
fn read_row(
    py: Python<'_>,
    raw: Vec<Cell>,
    cells: &mut impl Cells,
    styles: &mut Styles,
) -> PyResult<ReadRow> {
    let space = intern!(py, " ");
    let empty = intern!(py, "");
    let mut graphemes: Vec<Bound<'_, PyString>> = Vec::with_capacity(raw.len());
    let mut widths: Vec<u8> = Vec::with_capacity(raw.len());
    let mut indices: Vec<u32> = Vec::with_capacity(raw.len());
    // A row holds few distinct styles, so a list beats a map here.
    let mut by_style_id: Vec<(StyleId, u32)> = Vec::new();
    let mut style_probes = Some(Vec::new());
    let mut cluster = String::new();
    let mut utf8 = [0; 4];

    for (x, &cell) in (0u16..).zip(&raw) {
        let content = cell.content_tag().map_err(ghostty_error)?;
        let index = if cell.has_styling().map_err(ghostty_error)? {
            let id = cell.style_id().map_err(ghostty_error)?;
            match by_style_id.iter().find(|(seen, _)| *seen == id) {
                Some(&(_, index)) => index,
                None => {
                    let index = styles.index(cells.style(x).map_err(ghostty_error)?.into());
                    by_style_id.push((id, index));
                    if let Some(probes) = &mut style_probes {
                        probes.push((x, index));
                    }
                    index
                }
            }
        } else {
            match content {
                CellContentTag::BgColorPalette => {
                    let palette = cell.bg_color_palette().map_err(ghostty_error)?;
                    styles.index(Style::erased(Color::Palette(palette.0)))
                }
                CellContentTag::BgColorRgb => {
                    let rgb = cell.bg_color_rgb().map_err(ghostty_error)?;
                    styles.index(Style::erased(Color::Rgb(rgb.r, rgb.g, rgb.b)))
                }
                _ => 0,
            }
        };

        let (grapheme, width) = match cell.wide().map_err(ghostty_error)? {
            // The wide character before it takes this column too.
            CellWide::SpacerTail => (empty.clone(), 0),
            // A soft-wrapped line's last column, left blank where a wide character didn't fit.
            CellWide::SpacerHead => (space.clone(), 1),
            wide => {
                let width = if wide == CellWide::Wide { 2 } else { 1 };
                let grapheme = match content {
                    CellContentTag::Codepoint => {
                        match char::from_u32(cell.codepoint().map_err(ghostty_error)?) {
                            Some(c) if c != '\0' => PyString::new(py, c.encode_utf8(&mut utf8)),
                            _ => space.clone(),
                        }
                    }
                    CellContentTag::CodepointGrapheme => {
                        cells.cluster(x, &mut cluster).map_err(ghostty_error)?;
                        style_probes = None;
                        PyString::new(py, &cluster)
                    }
                    CellContentTag::BgColorPalette | CellContentTag::BgColorRgb => space.clone(),
                };
                (grapheme, width)
            }
        };
        graphemes.push(grapheme);
        widths.push(width);
        indices.push(index);
    }

    let row = Row {
        graphemes: PyTuple::new(py, graphemes)?.unbind(),
        widths: PyBytes::new(py, &widths).unbind(),
        styles: PyTuple::new(py, indices)?.unbind(),
    };
    Ok(ReadRow {
        row: Py::new(py, row)?,
        raw,
        style_probes,
    })
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Row>()?;
    m.add_class::<Frame>()?;
    m.add_class::<ScrolledOff>()?;
    m.add_class::<History>()?;
    m.add_class::<RenderState>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    //! The libghostty behavior `frame` and `scrolled_off` rely on.

    use libghostty_vt::render::{Dirty, RowIterator};
    use libghostty_vt::terminal::{Options, Point, PointCoordinate, PointSpace};
    use libghostty_vt::{RenderState, Terminal};

    /// Each viewport row's dirty flag after an update, top to bottom, then clears them.
    fn dirty_rows(
        state: &mut RenderState<'static>,
        terminal: &Terminal<'static, 'static>,
    ) -> Vec<bool> {
        let snapshot = state.update(terminal).unwrap();
        let mut iterator = RowIterator::new().unwrap();
        let mut iteration = iterator.update(&snapshot).unwrap();
        let mut dirty = Vec::new();
        while let Some(row) = iteration.next() {
            dirty.push(row.dirty().unwrap());
            row.set_dirty(false).unwrap();
        }
        snapshot.set_dirty(Dirty::Clean).unwrap();
        dirty
    }

    fn filled(max_scrollback: usize) -> Terminal<'static, 'static> {
        let mut terminal = Terminal::new(Options {
            cols: 10,
            rows: 4,
            max_scrollback,
        })
        .unwrap();
        terminal.vt_write(b"a\r\nb\r\nc\r\nd");
        terminal
    }

    #[test]
    fn rewriting_a_row_leaves_the_other_rows_clean() {
        let mut terminal = filled(0);
        let mut state = RenderState::new().unwrap();
        dirty_rows(&mut state, &terminal);
        terminal.vt_write(b"\rD");
        assert_eq!(
            dirty_rows(&mut state, &terminal),
            [false, false, false, true]
        );
    }

    #[test]
    fn a_scroll_marks_every_row_dirty() {
        let mut terminal = filled(0);
        let mut state = RenderState::new().unwrap();
        dirty_rows(&mut state, &terminal);
        terminal.vt_write(b"\r\ne");
        assert_eq!(dirty_rows(&mut state, &terminal), [true; 4]);
    }

    #[test]
    fn a_tracked_reference_follows_the_top_row_into_the_scrollback() {
        let mut terminal = filled(1_000_000);
        let anchor = terminal
            .track_grid_ref(Point::Active(PointCoordinate { x: 0, y: 0 }))
            .unwrap();
        let before = terminal.scrollback_rows().unwrap();
        terminal.vt_write(b"\r\ne\r\nf");
        let at = anchor.point(PointSpace::History).unwrap().unwrap();
        assert_eq!(at.y as usize, before);
        assert_eq!(terminal.scrollback_rows().unwrap(), before + 2);
    }

    #[test]
    fn a_tracked_reference_loses_its_value_when_the_scrollback_frees_its_row() {
        // A wide terminal fills the scrollback's pages in fewer rows.
        let mut terminal = Terminal::new(Options {
            cols: 1000,
            rows: 4,
            max_scrollback: 1,
        })
        .unwrap();
        let anchor = terminal
            .track_grid_ref(Point::Active(PointCoordinate { x: 0, y: 0 }))
            .unwrap();
        let line = format!("\r\n{}", "x".repeat(999));
        for _ in 0..2_000 {
            terminal.vt_write(line.as_bytes());
        }
        assert!(!anchor.has_value());
    }
}

use std::mem;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use libghostty_vt::render::{CellIterator, RowId, RowIteration, RowIterator};
use libghostty_vt::screen::{Cell, CellContentTag, CellWide};
use libghostty_vt::style::Id as StyleId;
use pyo3::exceptions::PyRuntimeError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString, PyTuple};
use rustc_hash::FxHashMap;

use crate::errors::ghostty_error;
use crate::style::{Color, Style};
use crate::terminal::Terminal;

/// A libghostty render-state object, owned by a Python `RenderState`.
struct Owned<T>(T);

// SAFETY: as for `OwnedTerminal`: libghostty's render state and its iterators have no thread
// affinity, and only `RenderState`'s `&mut self` methods touch them, so each access has exclusive
// use of them whatever thread it runs on.
unsafe impl<T> Send for Owned<T> {}
unsafe impl<T> Sync for Owned<T> {}

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
    /// Each column's style, as an index into the styles `Frame.new_styles` has delivered.
    #[pyo3(get)]
    styles: Py<PyTuple>,
}

/// A row as last read, kept by libghostty's row id so the next frame can hand back the same `Row`.
struct ReadRow {
    row: Py<Row>,
    /// The raw cell values it was read from.
    raw: Vec<Cell>,
    /// For each style id in the row, a column using it and the style index it was read as,
    /// or `None` when the row holds a multi-codepoint grapheme cluster, whose codepoints after the
    /// first are kept outside the raw cells, so equal raw cells don't mean an unchanged row.
    style_probes: Option<Vec<(u16, u32)>>,
}

/// Every style a render state has delivered, interned terminal-wide.
///
/// libghostty's style ids mean something only within one page, so frames name styles
/// by these indices instead, and a consumer converts each style once.
struct Styles {
    indices: FxHashMap<Style, u32>,
    /// Styles interned since the last frame, in index order.
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
    /// The styles first used since the last frame: the next indices, in order.
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

/// Reads what a terminal shows, a frame at a time. A terminal has at most one.
#[pyclass(module = "evp")]
pub struct RenderState {
    terminal: Py<Terminal>,
    is_rendered: Arc<AtomicBool>,
    state: Owned<libghostty_vt::RenderState<'static>>,
    row_iterator: Owned<RowIterator<'static>>,
    cell_iterator: Owned<CellIterator<'static>>,
    rows: FxHashMap<RowId, ReadRow>,
    styles: Styles,
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
        let is_rendered = Arc::clone(&terminal.borrow().is_rendered);
        // libghostty lets a second render state take the first's dirty rows,
        // which would make the first hand back rows whose content changed.
        if is_rendered.swap(true, Ordering::AcqRel) {
            return Err(PyRuntimeError::new_err(
                "This terminal already has a RenderState: a second would take the first's dirty rows",
            ));
        }
        Ok(RenderState {
            terminal: terminal.clone().unbind(),
            is_rendered,
            state: Owned(libghostty_vt::RenderState::new().map_err(ghostty_error)?),
            row_iterator: Owned(RowIterator::new().map_err(ghostty_error)?),
            cell_iterator: Owned(CellIterator::new().map_err(ghostty_error)?),
            rows: FxHashMap::default(),
            styles: Styles::new(),
        })
    }

    /// Bring the render state up to date with the terminal and read what it shows.
    fn frame(&mut self, py: Python<'_>) -> PyResult<Frame> {
        let RenderState {
            terminal,
            state,
            row_iterator,
            cell_iterator,
            rows: read_rows,
            styles,
            ..
        } = self;
        let terminal = terminal.borrow_mut(py);
        let snapshot = state.0.update(&terminal.inner.0).map_err(ghostty_error)?;

        let mut previous = mem::take(read_rows);
        let mut current = FxHashMap::default();
        current.reserve(previous.len());
        let mut rows = Vec::with_capacity(previous.len());
        let mut iteration = row_iterator.0.update(&snapshot).map_err(ghostty_error)?;
        while let Some(row) = iteration.next() {
            let id = row.id().map_err(ghostty_error)?;
            let read = match previous.remove(&id) {
                Some(read)
                    if !row.dirty().map_err(ghostty_error)?
                        || is_unchanged(&read, row, &mut cell_iterator.0, styles)? =>
                {
                    read
                }
                _ => read_row(py, row, &mut cell_iterator.0, styles)?,
            };
            rows.push(read.row.clone_ref(py));
            current.insert(id, read);
        }
        *read_rows = current;

        let colors = snapshot.colors().map_err(ghostty_error)?;
        let cursor = snapshot.cursor().map_err(ghostty_error)?;
        let size = (
            snapshot.cols().map_err(ghostty_error)?,
            snapshot.rows().map_err(ghostty_error)?,
        );
        snapshot.clean().map_err(ghostty_error)?;

        let palette: Vec<u8> = colors
            .palette
            .iter()
            .flat_map(|c| [c.r, c.g, c.b])
            .collect();
        let new_styles = styles
            .added
            .drain(..)
            .map(|style| Py::new(py, style))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(Frame {
            size,
            rows: PyTuple::new(py, rows)?.unbind(),
            new_styles: PyTuple::new(py, new_styles)?.unbind(),
            cursor: cursor
                .viewport
                .filter(|_| cursor.visible)
                .map(|viewport| (viewport.x, viewport.y, viewport.at_wide_tail)),
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
}

/// Whether a dirty row still shows what it showed when it was read.
///
/// libghostty marks every row dirty when the screen scrolls, though most only moved.
/// Equal raw cells hold the same codepoints, widths and style ids, but a style id can be freed
/// and reused for another style once no cell holds it, so each id's style is read again.
fn is_unchanged(
    read: &ReadRow,
    row: &RowIteration<'static, '_>,
    cells: &mut CellIterator<'static>,
    styles: &mut Styles,
) -> PyResult<bool> {
    let Some(probes) = &read.style_probes else {
        return Ok(false);
    };
    if !row
        .cells_raw()
        .map_err(ghostty_error)?
        .eq(read.raw.iter().copied())
    {
        return Ok(false);
    }
    if probes.is_empty() {
        return Ok(true);
    }
    let mut iteration = cells.update(row).map_err(ghostty_error)?;
    for &(x, index) in probes {
        iteration.select(x).map_err(ghostty_error)?;
        let style = iteration.style().map_err(ghostty_error)?;
        if styles.index(style.into()) != index {
            return Ok(false);
        }
    }
    Ok(true)
}

/// Read a row's cells, reading a cell's style only for the first cell in the row with its style id.
fn read_row(
    py: Python<'_>,
    row: &RowIteration<'static, '_>,
    cells: &mut CellIterator<'static>,
    styles: &mut Styles,
) -> PyResult<ReadRow> {
    let raw: Vec<Cell> = row.cells_raw().map_err(ghostty_error)?.collect();
    let mut iteration = cells.update(row).map_err(ghostty_error)?;
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
                    iteration.select(x).map_err(ghostty_error)?;
                    let index = styles.index(iteration.style().map_err(ghostty_error)?.into());
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
                        iteration.select(x).map_err(ghostty_error)?;
                        iteration
                            .graphemes_utf8(&mut cluster)
                            .map_err(ghostty_error)?;
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
    m.add_class::<RenderState>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    //! How libghostty's row ids behave, which decides when `frame` can reuse a dirty row's `Row`.

    use libghostty_vt::render::{RowId, RowIterator};
    use libghostty_vt::{RenderState, Terminal};

    /// Each viewport row's id and dirty flag after an update, top to bottom, then cleans.
    fn rows(
        state: &mut RenderState<'static>,
        terminal: &Terminal<'static, 'static>,
    ) -> Vec<(RowId, bool)> {
        let snapshot = state.update(terminal).unwrap();
        let mut iterator = RowIterator::new().unwrap();
        let mut iteration = iterator.update(&snapshot).unwrap();
        let mut rows = Vec::new();
        while let Some(row) = iteration.next() {
            rows.push((row.id().unwrap(), row.dirty().unwrap()));
        }
        snapshot.clean().unwrap();
        rows
    }

    fn filled(scrollback_lines: usize) -> (Terminal<'static, 'static>, RenderState<'static>) {
        let mut terminal = Terminal::new(10, 4).unwrap();
        terminal
            .set_scrollback_max_lines(Some(scrollback_lines))
            .unwrap();
        terminal.vt_write(b"a\r\nb\r\nc\r\nd");
        let mut state = RenderState::new().unwrap();
        rows(&mut state, &terminal);
        (terminal, state)
    }

    #[test]
    fn a_scroll_into_scrollback_keeps_each_moved_rows_id() {
        let (mut terminal, mut state) = filled(100);
        let before = rows(&mut state, &terminal);
        terminal.vt_write(b"\r\ne");
        let after = rows(&mut state, &terminal);
        let before_ids: Vec<_> = before.iter().map(|(id, _)| *id).collect();
        let after_ids: Vec<_> = after.iter().map(|(id, _)| *id).collect();
        assert_eq!(after_ids[..3], before_ids[1..]);
        assert!(!before_ids.contains(&after_ids[3]));
        assert!(after.iter().all(|(_, dirty)| *dirty));
    }

    #[test]
    fn a_scroll_with_no_scrollback_keeps_each_moved_rows_id() {
        let (mut terminal, mut state) = filled(0);
        let before = rows(&mut state, &terminal);
        terminal.vt_write(b"\r\ne");
        let after = rows(&mut state, &terminal);
        let before_ids: Vec<_> = before.iter().map(|(id, _)| *id).collect();
        let after_ids: Vec<_> = after.iter().map(|(id, _)| *id).collect();
        assert_eq!(after_ids[..3], before_ids[1..]);
        assert!(!before_ids.contains(&after_ids[3]));
    }

    #[test]
    fn rewriting_a_row_in_place_keeps_its_id_and_marks_only_it_dirty() {
        let (mut terminal, mut state) = filled(100);
        let before = rows(&mut state, &terminal);
        terminal.vt_write(b"\rD");
        let after = rows(&mut state, &terminal);
        assert_eq!(
            after.iter().map(|(id, _)| *id).collect::<Vec<_>>(),
            before.iter().map(|(id, _)| *id).collect::<Vec<_>>()
        );
        assert_eq!(
            after.iter().map(|(_, dirty)| *dirty).collect::<Vec<_>>(),
            [false, false, false, true]
        );
    }

    #[test]
    fn a_scroll_region_gives_every_row_a_new_id() {
        let (mut terminal, mut state) = filled(100);
        let before = rows(&mut state, &terminal);
        // Scroll only rows 2 to 4 up by one: row 1, outside the region, gets a new id too.
        terminal.vt_write(b"\x1b[2;4r\x1b[4;1H\r\n");
        let after = rows(&mut state, &terminal);
        assert!(
            after
                .iter()
                .all(|(id, _)| !before.iter().any(|(old, _)| old == id))
        );
    }
}

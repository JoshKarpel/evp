use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};

use libghostty_vt::style::{Palette, RgbColor};
use libghostty_vt::terminal::{Mode, ModeKind};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::errors::ghostty_error;

/// libghostty-vt's terminal, owned by a Python `Terminal`.
pub(crate) struct OwnedTerminal(pub(crate) libghostty_vt::Terminal<'static, 'static>);

// SAFETY: libghostty's terminal has no thread affinity: it's plain memory that Ghostty itself
// reads and writes from several threads under a lock. Only `Terminal`'s `&mut self` methods and
// `RenderState`'s `&mut self` methods (through `Py::borrow_mut`) touch it, so PyO3's borrow
// checking gives each access exclusive use of it, whatever thread it runs on.
// Keep it that way: a `&self` method that reads it would allow two threads at once.
unsafe impl Send for OwnedTerminal {}
unsafe impl Sync for OwnedTerminal {}

/// A terminal emulator, fed the bytes a program writes.
#[pyclass(module = "evp")]
pub struct Terminal {
    pub(crate) inner: OwnedTerminal,
    /// The first exception `on_write_pty` raised during the current call into libghostty,
    /// which the call raises once libghostty returns.
    raised: Arc<Mutex<Option<PyErr>>>,
    /// Whether a `RenderState` reads this terminal, since a second one would take its dirty rows.
    pub(crate) is_rendered: Arc<AtomicBool>,
}

impl Terminal {
    /// Raise what `on_write_pty` raised during the call into libghostty that just returned.
    fn raise_pending(&self) -> PyResult<()> {
        match self
            .raised
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take()
        {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}

fn rgb((r, g, b): (u8, u8, u8)) -> RgbColor {
    RgbColor { r, g, b }
}

#[pymethods]
impl Terminal {
    #[new]
    #[pyo3(signature = (columns, rows, *, scrollback_lines = 0, on_write_pty = None))]
    fn new(
        columns: u16,
        rows: u16,
        scrollback_lines: usize,
        on_write_pty: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let mut terminal = libghostty_vt::Terminal::new(columns, rows).map_err(ghostty_error)?;
        terminal
            .set_scrollback_max_lines(Some(scrollback_lines))
            .map_err(ghostty_error)?;
        if scrollback_lines > 0 {
            // libghostty also caps its scrollback at a few hundred rows' worth of bytes by default,
            // so lift that and let the line limit bound it.
            terminal
                .set_scrollback_max_bytes(None)
                .map_err(ghostty_error)?;
        }
        let raised = Arc::new(Mutex::new(None));
        if let Some(callback) = on_write_pty {
            let raised = Arc::clone(&raised);
            terminal
                .on_pty_write(move |_, data| {
                    Python::attach(|py| {
                        if let Err(error) = callback.call1(py, (PyBytes::new(py, data),)) {
                            raised
                                .lock()
                                .unwrap_or_else(PoisonError::into_inner)
                                .get_or_insert(error);
                        }
                    });
                })
                .map_err(ghostty_error)?;
        }
        Ok(Terminal {
            inner: OwnedTerminal(terminal),
            raised,
            is_rendered: Arc::new(AtomicBool::new(false)),
        })
    }

    /// Feed the terminal bytes the program wrote, raising whatever `on_write_pty` raised meanwhile.
    fn feed(&mut self, data: &[u8]) -> PyResult<()> {
        self.inner.0.vt_write(data);
        self.raise_pending()
    }

    /// Resize the terminal, reflowing what it shows.
    fn resize(&mut self, columns: u16, rows: u16) -> PyResult<()> {
        self.inner
            .0
            .resize(columns, rows, 0, 0)
            .map_err(ghostty_error)?;
        self.raise_pending()
    }

    /// The terminal's `(columns, rows)`.
    fn size(&mut self) -> PyResult<(u16, u16)> {
        let terminal = &self.inner.0;
        Ok((
            terminal.cols().map_err(ghostty_error)?,
            terminal.rows().map_err(ghostty_error)?,
        ))
    }

    /// Whether a mode is set: a DEC private mode (`ESC [ ? n h`), or with `ansi`, an ANSI one.
    #[pyo3(signature = (number, *, ansi = false))]
    fn mode(&mut self, number: u16, ansi: bool) -> PyResult<bool> {
        let kind = if ansi { ModeKind::Ansi } else { ModeKind::Dec };
        self.inner
            .0
            .mode(Mode::new(number, kind))
            .map_err(ghostty_error)
    }

    /// The title the program set (with OSC 0 or 2), or an empty one.
    fn title(&mut self) -> PyResult<String> {
        Ok(self.inner.0.title().map_err(ghostty_error)?.to_owned())
    }

    /// Set the colors the program's default foreground and background stand for,
    /// until the program sets its own (with OSC 10 and 11).
    fn set_default_colors(
        &mut self,
        foreground: (u8, u8, u8),
        background: (u8, u8, u8),
    ) -> PyResult<()> {
        self.inner
            .0
            .set_default_fg_color(Some(rgb(foreground)))
            .map_err(ghostty_error)?
            .set_default_bg_color(Some(rgb(background)))
            .map_err(ghostty_error)?;
        Ok(())
    }

    /// Set the 256-color palette, as 768 bytes of RGB, keeping entries the program changed (with OSC 4).
    fn set_default_palette(&mut self, palette: &[u8]) -> PyResult<()> {
        let mut colors = [RgbColor::default(); 256];
        if palette.len() != 3 * colors.len() {
            return Err(PyValueError::new_err(format!(
                "A palette is 768 bytes, 3 for each of 256 colors, but got {}",
                palette.len()
            )));
        }
        for (color, &[r, g, b]) in colors.iter_mut().zip(palette.as_chunks::<3>().0) {
            *color = rgb((r, g, b));
        }
        self.inner
            .0
            .set_default_color_palette(Some(Palette(colors)))
            .map_err(ghostty_error)?;
        Ok(())
    }

    /// Whether a `RenderState` reads this terminal now.
    #[getter]
    fn is_rendered(&self) -> bool {
        self.is_rendered.load(Ordering::Acquire)
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Terminal>()?;
    Ok(())
}

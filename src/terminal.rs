use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};

use libghostty_vt::style::{Palette, RgbColor};
use libghostty_vt::terminal::{
    ClipboardWriteError, ConformanceLevel, DeviceAttributeFeature, DeviceType, Mode, ModeKind,
    Options, PrimaryDeviceAttributes, ScrollViewport, SecondaryDeviceAttributes, SizeReportSize,
    TertiaryDeviceAttributes,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::encode::color_scheme;
use crate::errors::ghostty_error;

/// libghostty-vt's terminal, owned by a Python `Terminal`.
pub(crate) struct OwnedTerminal(pub(crate) libghostty_vt::Terminal<'static, 'static>);

// SAFETY: libghostty's terminal has no thread affinity: it's plain memory that Ghostty itself
// reads and writes from several threads under a lock. Only `Terminal`'s `&mut self` methods and
// the `&mut self` methods of `RenderState`, `KeyEncoder`, `MouseEncoder` and `Formatter`
// (through `Py::borrow_mut`) touch it, so PyO3's borrow
// checking gives each access exclusive use of it, whatever thread it runs on.
// Keep it that way: a `&self` method that reads it would allow two threads at once.
unsafe impl Send for OwnedTerminal {}
unsafe impl Sync for OwnedTerminal {}

/// What the terminal answers a program's device attributes queries (`ESC [ c`, `ESC [ > c`, `ESC [ = c`) with.
#[pyclass(frozen, module = "evp")]
#[derive(Clone)]
pub struct DeviceAttributes {
    /// The primary attributes' conformance level: 62 for a VT220, up to 65 for a VT525.
    #[pyo3(get)]
    conformance_level: u16,
    /// The primary attributes' features, as DEC numbers them: 22 for ANSI color, 52 for the clipboard.
    #[pyo3(get)]
    features: Vec<u16>,
    /// The secondary attributes' terminal type: 1 for a VT220.
    #[pyo3(get)]
    device_type: u16,
    /// The secondary attributes' firmware version.
    #[pyo3(get)]
    firmware_version: u16,
    /// The tertiary attributes' unit id, which the reply writes as 8 hexadecimal digits.
    #[pyo3(get)]
    unit_id: u32,
}

#[pymethods]
impl DeviceAttributes {
    #[new]
    #[pyo3(signature = (*, conformance_level = 62, features = vec![22], device_type = 1, firmware_version = 0, unit_id = 0))]
    fn new(
        conformance_level: u16,
        features: Vec<u16>,
        device_type: u16,
        firmware_version: u16,
        unit_id: u32,
    ) -> PyResult<Self> {
        if features.len() > 64 {
            return Err(PyValueError::new_err(format!(
                "Device attributes have at most 64 features, but got {}",
                features.len()
            )));
        }
        Ok(DeviceAttributes {
            conformance_level,
            features,
            device_type,
            firmware_version,
            unit_id,
        })
    }
}

impl From<&DeviceAttributes> for libghostty_vt::terminal::DeviceAttributes {
    fn from(attributes: &DeviceAttributes) -> Self {
        let features = attributes
            .features
            .iter()
            .map(|&feature| DeviceAttributeFeature(feature))
            .collect::<Vec<_>>();
        libghostty_vt::terminal::DeviceAttributes {
            primary: PrimaryDeviceAttributes::new(
                ConformanceLevel(attributes.conformance_level),
                &features,
            ),
            secondary: SecondaryDeviceAttributes {
                device_type: DeviceType(attributes.device_type),
                firmware_version: attributes.firmware_version,
                rom_cartridge: 0,
            },
            tertiary: TertiaryDeviceAttributes {
                unit_id: attributes.unit_id,
            },
        }
    }
}

/// The first exception a callback raised during the current call into libghostty,
/// which the call raises once libghostty returns.
type Raised = Arc<Mutex<Option<PyErr>>>;

/// Run a Python callback from inside libghostty, keeping the first exception any callback raises
/// for the call into libghostty to raise when it returns.
fn call<T>(raised: &Raised, callback: impl FnOnce(Python<'_>) -> PyResult<T>) -> Option<T> {
    Python::attach(|py| match callback(py) {
        Ok(value) => Some(value),
        Err(error) => {
            raised
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .get_or_insert(error);
            None
        }
    })
}

/// A value of one of evp's enums, as its Python enum.
fn enum_member<'py>(py: Python<'py>, name: &str, value: u32) -> PyResult<Bound<'py, PyAny>> {
    py.import("evp._evp")?.getattr(name)?.call1((value,))
}

/// A terminal emulator, fed the bytes a program writes.
#[pyclass(module = "evp")]
pub struct Terminal {
    pub(crate) inner: OwnedTerminal,
    raised: Raised,
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
    #[pyo3(signature = (
        columns,
        rows,
        *,
        max_scrollback_bytes = 0,
        on_write_pty = None,
        on_bell = None,
        on_title_changed = None,
        on_pwd_changed = None,
        on_clipboard_write = None,
        on_size = None,
        on_color_scheme = None,
        on_device_attributes = None,
    ))]
    #[expect(
        clippy::too_many_arguments,
        reason = "the terminal's options and callbacks, as keyword arguments"
    )]
    fn new(
        columns: u16,
        rows: u16,
        max_scrollback_bytes: usize,
        on_write_pty: Option<Py<PyAny>>,
        on_bell: Option<Py<PyAny>>,
        on_title_changed: Option<Py<PyAny>>,
        on_pwd_changed: Option<Py<PyAny>>,
        on_clipboard_write: Option<Py<PyAny>>,
        on_size: Option<Py<PyAny>>,
        on_color_scheme: Option<Py<PyAny>>,
        on_device_attributes: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        // libghostty-rs documents `max_scrollback` as lines, but this Ghostty treats it as bytes,
        // and frees scrollback a page (a few hundred KB) at a time, so it keeps at least a page or
        // two whenever it's above zero. Plain text takes about 10 bytes a cell.
        let mut terminal = libghostty_vt::Terminal::new(Options {
            cols: columns,
            rows,
            max_scrollback: max_scrollback_bytes,
        })
        .map_err(ghostty_error)?;
        let raised: Raised = Arc::new(Mutex::new(None));
        // libghostty runs these while `feed` (or `resize`) has the terminal borrowed,
        // so each passes what the callback needs rather than letting it call into the terminal.
        if let Some(callback) = on_write_pty {
            let raised = Arc::clone(&raised);
            terminal
                .on_pty_write(move |_, data| {
                    call(&raised, |py| callback.call1(py, (PyBytes::new(py, data),)));
                })
                .map_err(ghostty_error)?;
        }
        if let Some(callback) = on_bell {
            let raised = Arc::clone(&raised);
            terminal
                .on_bell(move |_| {
                    call(&raised, |py| callback.call0(py));
                })
                .map_err(ghostty_error)?;
        }
        if let Some(callback) = on_title_changed {
            let raised = Arc::clone(&raised);
            terminal
                .on_title_changed(move |terminal| {
                    call(&raised, |py| {
                        let title = terminal.title().map_err(ghostty_error)?;
                        callback.call1(py, (title,))
                    });
                })
                .map_err(ghostty_error)?;
        }
        if let Some(callback) = on_pwd_changed {
            let raised = Arc::clone(&raised);
            terminal
                .on_pwd_changed(move |terminal| {
                    call(&raised, |py| {
                        let pwd = terminal.pwd().map_err(ghostty_error)?;
                        callback.call1(py, (pwd,))
                    });
                })
                .map_err(ghostty_error)?;
        }
        if let Some(callback) = on_clipboard_write {
            let raised = Arc::clone(&raised);
            terminal
                .on_clipboard_write(move |_, write| {
                    call(&raised, |py| {
                        let location =
                            enum_member(py, "ClipboardLocation", write.location() as u32)?;
                        let contents = write
                            .contents()
                            .map(|content| (content.mime, content.data))
                            .collect::<Vec<_>>();
                        callback.call1(py, (location, contents))
                    })
                    // Only some protocols acknowledge a write, and evp's callback has no way to refuse one
                    // but raising, so a callback that raised is the one failure to report.
                    .map(drop)
                    .ok_or(ClipboardWriteError::Denied)
                })
                .map_err(ghostty_error)?;
        }
        if let Some(callback) = on_size {
            let raised = Arc::clone(&raised);
            terminal
                .on_size(move |terminal| {
                    call(&raised, |py| {
                        let size: Option<(u32, u32)> = callback.call0(py)?.extract(py)?;
                        let (Some((cell_width, cell_height)), Ok(columns), Ok(rows)) =
                            (size, terminal.cols(), terminal.rows())
                        else {
                            return Ok(None);
                        };
                        Ok(Some(SizeReportSize {
                            rows,
                            columns,
                            cell_width,
                            cell_height,
                        }))
                    })
                    .flatten()
                })
                .map_err(ghostty_error)?;
        }
        if let Some(callback) = on_color_scheme {
            let raised = Arc::clone(&raised);
            terminal
                .on_color_scheme(move |_| {
                    call(&raised, |py| {
                        let scheme: Option<u32> = callback.call0(py)?.extract(py)?;
                        scheme.map(color_scheme).transpose()
                    })
                    .flatten()
                })
                .map_err(ghostty_error)?;
        }
        // libghostty-vt's header says an unset callback leaves device attributes queries unanswered,
        // but this Ghostty answers with its own, as it does when the callback returns `None`;
        // tests/test_terminal.py pins both.
        if let Some(callback) = on_device_attributes {
            let raised = Arc::clone(&raised);
            terminal
                .on_device_attributes(move |_| {
                    call(&raised, |py| {
                        let attributes: Option<PyRef<'_, DeviceAttributes>> =
                            callback.call0(py)?.extract(py)?;
                        Ok(attributes.map(|attributes| (&*attributes).into()))
                    })
                    .flatten()
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

    /// Resize the terminal, reflowing what it shows. A cell's size in pixels is for size reports and images.
    #[pyo3(signature = (columns, rows, *, cell_width = 0, cell_height = 0))]
    fn resize(
        &mut self,
        columns: u16,
        rows: u16,
        cell_width: u32,
        cell_height: u32,
    ) -> PyResult<()> {
        self.inner
            .0
            .resize(columns, rows, cell_width, cell_height)
            .map_err(ghostty_error)?;
        self.raise_pending()
    }

    /// Reset the terminal as a program's `ESC c` does, keeping its size.
    fn reset(&mut self) -> PyResult<()> {
        self.inner.0.reset();
        self.raise_pending()
    }

    /// Scroll the viewport by `delta` rows into the scrollback, up for negative.
    fn scroll_viewport(&mut self, delta: isize) {
        self.inner.0.scroll_viewport(ScrollViewport::Delta(delta));
    }

    /// Scroll the viewport to the oldest row of the scrollback.
    fn scroll_viewport_to_top(&mut self) {
        self.inner.0.scroll_viewport(ScrollViewport::Top);
    }

    /// Scroll the viewport back to the screen the program draws on.
    fn scroll_viewport_to_bottom(&mut self) {
        self.inner.0.scroll_viewport(ScrollViewport::Bottom);
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

    /// Set a mode, as the program would with `ESC [ ? n h` or `l`, or with `ansi`, `ESC [ n h` or `l`.
    #[pyo3(signature = (number, value, *, ansi = false))]
    fn set_mode(&mut self, number: u16, value: bool, ansi: bool) -> PyResult<()> {
        let kind = if ansi { ModeKind::Ansi } else { ModeKind::Dec };
        self.inner
            .0
            .set_mode(Mode::new(number, kind), value)
            .map_err(ghostty_error)?;
        Ok(())
    }

    /// The title the program set (with OSC 0 or 2), or an empty one.
    fn title(&mut self) -> PyResult<String> {
        Ok(self.inner.0.title().map_err(ghostty_error)?.to_owned())
    }

    /// The working directory the program reported (with OSC 7), or an empty one.
    fn pwd(&mut self) -> PyResult<String> {
        Ok(self.inner.0.pwd().map_err(ghostty_error)?.to_owned())
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
    m.add_class::<DeviceAttributes>()?;
    m.add_class::<Terminal>()?;
    Ok(())
}

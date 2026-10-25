use libghostty_vt::fmt::{Format, Formatter as GhosttyFormatter, FormatterOptions};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::enums::parse;
use crate::errors::ghostty_error;
use crate::terminal::Terminal;

/// Writes what a terminal's screen shows as plain text, VT sequences or HTML.
///
/// libghostty's formatter borrows its terminal, so `format` makes one each call from these options.
#[pyclass(module = "evp")]
pub struct Formatter {
    terminal: Py<Terminal>,
    format: Format,
    unwrap: bool,
    trim: bool,
    palette: bool,
    modes: bool,
    scrolling_region: bool,
    tabstops: bool,
    pwd: bool,
    keyboard: bool,
    cursor: bool,
    style: bool,
    hyperlink: bool,
    protection: bool,
    kitty_keyboard: bool,
    charsets: bool,
}

#[pymethods]
impl Formatter {
    #[new]
    #[pyo3(signature = (
        terminal,
        *,
        format = libghostty_vt::ffi::FormatterFormat::PLAIN,
        unwrap = false,
        trim = false,
        palette = false,
        modes = false,
        scrolling_region = false,
        tabstops = false,
        pwd = false,
        keyboard = false,
        cursor = false,
        style = false,
        hyperlink = false,
        protection = false,
        kitty_keyboard = false,
        charsets = false,
    ))]
    #[expect(
        clippy::too_many_arguments,
        clippy::fn_params_excessive_bools,
        reason = "libghostty's formatter options, as keyword arguments"
    )]
    fn new(
        terminal: Py<Terminal>,
        format: u32,
        unwrap: bool,
        trim: bool,
        palette: bool,
        modes: bool,
        scrolling_region: bool,
        tabstops: bool,
        pwd: bool,
        keyboard: bool,
        cursor: bool,
        style: bool,
        hyperlink: bool,
        protection: bool,
        kitty_keyboard: bool,
        charsets: bool,
    ) -> PyResult<Self> {
        Ok(Formatter {
            terminal,
            format: parse("FormatterFormat", format)?,
            unwrap,
            trim,
            palette,
            modes,
            scrolling_region,
            tabstops,
            pwd,
            keyboard,
            cursor,
            style,
            hyperlink,
            protection,
            kitty_keyboard,
            charsets,
        })
    }

    /// Format what the terminal's active screen shows now.
    fn format(&mut self, py: Python<'_>) -> PyResult<String> {
        let terminal = self.terminal.borrow_mut(py);
        let options = FormatterOptions::new()
            .with_format(self.format)
            .with_unwrap(self.unwrap)
            .with_trim(self.trim)
            .with_palette(self.palette)
            .with_modes(self.modes)
            .with_scrolling_region(self.scrolling_region)
            .with_tabstops(self.tabstops)
            .with_pwd(self.pwd)
            .with_keyboard(self.keyboard)
            .with_cursor(self.cursor)
            .with_style(self.style)
            .with_hyperlink(self.hyperlink)
            .with_protection(self.protection)
            .with_kitty_keyboard(self.kitty_keyboard)
            .with_charsets(self.charsets);
        let mut formatter =
            GhosttyFormatter::new(&terminal.inner.0, options).map_err(ghostty_error)?;
        let formatted = formatter.format_alloc(None).map_err(ghostty_error)?;
        String::from_utf8(formatted.to_vec()).map_err(|error| {
            PyValueError::new_err(format!("libghostty formatted invalid UTF-8: {error}"))
        })
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Formatter>()?;
    Ok(())
}

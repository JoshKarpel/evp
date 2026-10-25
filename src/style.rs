use libghostty_vt::style::{RgbColor, StyleColor};
use pyo3::prelude::*;
use pyo3::types::PyTuple;

/// A color a style names: none (the terminal's default), a palette index, or RGB.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) enum Color {
    Default,
    Palette(u8),
    Rgb(u8, u8, u8),
}

impl Color {
    fn to_python<'py>(self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(match self {
            Color::Default => py.None().into_bound(py),
            Color::Palette(index) => index.into_pyobject(py)?.into_any(),
            Color::Rgb(r, g, b) => PyTuple::new(py, [r, g, b])?.into_any(),
        })
    }
}

impl From<StyleColor> for Color {
    fn from(color: StyleColor) -> Self {
        match color {
            StyleColor::None => Color::Default,
            StyleColor::Palette(index) => Color::Palette(index.0),
            StyleColor::Rgb(RgbColor { r, g, b }) => Color::Rgb(r, g, b),
        }
    }
}

/// How a cell is drawn: its colors and attributes, as libghostty-vt's `GhosttyStyle`.
#[pyclass(frozen, eq, hash, module = "evp")]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Style {
    foreground: Color,
    background: Color,
    underline_color: Color,
    #[pyo3(get)]
    bold: bool,
    #[pyo3(get)]
    italic: bool,
    #[pyo3(get)]
    faint: bool,
    #[pyo3(get)]
    blink: bool,
    #[pyo3(get)]
    inverse: bool,
    #[pyo3(get)]
    invisible: bool,
    #[pyo3(get)]
    strikethrough: bool,
    #[pyo3(get)]
    overline: bool,
    /// libghostty's SGR underline kind: 0 for none, then single, double, curly, dotted, dashed.
    #[pyo3(get)]
    underline: i32,
}

impl Style {
    /// The style of a cell with no styling.
    pub(crate) const DEFAULT: Style = Style {
        foreground: Color::Default,
        background: Color::Default,
        underline_color: Color::Default,
        bold: false,
        italic: false,
        faint: false,
        blink: false,
        inverse: false,
        invisible: false,
        strikethrough: false,
        overline: false,
        underline: 0,
    };

    /// The style of a blank cell the program erased with a background color,
    /// which libghostty keeps in the cell rather than in a style.
    pub(crate) fn erased(background: Color) -> Style {
        Style {
            background,
            ..Style::DEFAULT
        }
    }
}

impl From<libghostty_vt::style::Style> for Style {
    fn from(style: libghostty_vt::style::Style) -> Self {
        Style {
            foreground: style.fg_color.into(),
            background: style.bg_color.into(),
            underline_color: style.underline_color.into(),
            bold: style.bold,
            italic: style.italic,
            faint: style.faint,
            blink: style.blink,
            inverse: style.inverse,
            invisible: style.invisible,
            strikethrough: style.strikethrough,
            overline: style.overline,
            underline: style.underline as i32,
        }
    }
}

#[pymethods]
impl Style {
    fn __repr__(&self) -> String {
        format!("{self:?}")
    }

    /// The foreground color: `None` for the terminal's default, a palette index, or an RGB tuple.
    #[getter]
    fn foreground<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.foreground.to_python(py)
    }

    /// The background color: `None` for the terminal's default, a palette index, or an RGB tuple.
    #[getter]
    fn background<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.background.to_python(py)
    }

    /// The underline color: `None` for the foreground, a palette index, or an RGB tuple.
    #[getter]
    fn underline_color<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.underline_color.to_python(py)
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Style>()?;
    Ok(())
}

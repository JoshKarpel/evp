use libghostty_vt::error::{Error, Result};
use libghostty_vt::ffi;
use libghostty_vt::focus;
use libghostty_vt::paste;
use libghostty_vt::terminal::ColorScheme;
use libghostty_vt::unicode;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::errors::ghostty_error;

/// Run one of libghostty's encoders, which write into a caller's buffer and report the size they
/// need when it's too small, with a buffer that grows to fit.
pub(crate) fn encode_into(mut encode: impl FnMut(&mut [u8]) -> Result<usize>) -> Result<Vec<u8>> {
    let mut buf = vec![0; 64];
    let written = match encode(&mut buf) {
        Err(Error::OutOfSpace { required }) => {
            buf.resize(required, 0);
            encode(&mut buf)?
        }
        result => result?,
    };
    buf.truncate(written);
    Ok(buf)
}

/// The bytes that report a focus change to a program that asked for focus reports (mode 1004).
#[pyfunction]
fn encode_focus(py: Python<'_>, event: u32) -> PyResult<Py<PyBytes>> {
    let event = match event {
        ffi::FocusEvent::GAINED => focus::Event::Gained,
        ffi::FocusEvent::LOST => focus::Event::Lost,
        _ => {
            return Err(PyValueError::new_err(format!(
                "{event} is not a valid FocusEvent"
            )));
        }
    };
    let encoded = encode_into(|buf| event.encode(buf)).map_err(ghostty_error)?;
    Ok(PyBytes::new(py, &encoded).unbind())
}

/// Text as a paste writes it to the program: control characters that could act on the terminal replaced
/// by spaces, and wrapped in bracketed paste's markers when `bracketed`, or with newlines as carriage returns.
#[pyfunction]
#[pyo3(signature = (text, *, bracketed))]
fn encode_paste(py: Python<'_>, text: &str, bracketed: bool) -> PyResult<Py<PyBytes>> {
    let mut data = text.as_bytes().to_vec();
    let encoded =
        encode_into(|buf| paste::encode(&mut data, bracketed, buf)).map_err(ghostty_error)?;
    Ok(PyBytes::new(py, &encoded).unbind())
}

/// Whether text is safe to paste without asking: it has no newline, which could run a command,
/// and no bracketed paste end marker, which could end the paste early.
#[pyfunction]
fn is_paste_safe(text: &str) -> bool {
    paste::is_safe(text)
}

/// A `ColorScheme`'s value as libghostty-vt's, which has no conversion from its value.
pub(crate) fn color_scheme(value: u32) -> PyResult<ColorScheme> {
    match value {
        ffi::ColorScheme::LIGHT => Ok(ColorScheme::Light),
        ffi::ColorScheme::DARK => Ok(ColorScheme::Dark),
        _ => Err(PyValueError::new_err(format!(
            "{value} is not a valid ColorScheme"
        ))),
    }
}

/// The bytes that report the terminal's color scheme, as the reply to `ESC [ ? 996 n` does.
/// Send them unasked only while the program has mode 2031 set.
#[pyfunction]
fn encode_color_scheme(py: Python<'_>, scheme: u32) -> PyResult<Py<PyBytes>> {
    let scheme = color_scheme(scheme)?;
    let encoded = encode_into(|buf| scheme.encode_report(buf)).map_err(ghostty_error)?;
    Ok(PyBytes::new(py, &encoded).unbind())
}

/// The bytes of a size report, in the given style.
#[pyfunction]
#[pyo3(signature = (style, *, columns, rows, cell_width, cell_height))]
fn encode_size_report(
    py: Python<'_>,
    style: u32,
    columns: u16,
    rows: u16,
    cell_width: u32,
    cell_height: u32,
) -> PyResult<Py<PyBytes>> {
    if style > ffi::SizeReportStyle::CSI_18_T {
        return Err(PyValueError::new_err(format!(
            "{style} is not a valid SizeReportStyle"
        )));
    }
    let size = ffi::SizeReportSize {
        rows,
        columns,
        cell_width,
        cell_height,
    };
    let encoded = encode_into(|buf| {
        let mut written = 0;
        // SAFETY: libghostty-vt 0.2.2 has no safe wrapper for this encoder. It reads `size` by value,
        // writes at most `buf.len()` bytes into `buf`, and writes the length it wrote or needs into `written`.
        let result = unsafe {
            ffi::ghostty_size_report_encode(
                style,
                size,
                buf.as_mut_ptr().cast(),
                buf.len(),
                &raw mut written,
            )
        };
        match result {
            ffi::Result::SUCCESS => Ok(written),
            ffi::Result::OUT_OF_SPACE => Err(Error::OutOfSpace { required: written }),
            ffi::Result::OUT_OF_MEMORY => Err(Error::OutOfMemory),
            _ => Err(Error::InvalidValue),
        }
    })
    .map_err(ghostty_error)?;
    Ok(PyBytes::new(py, &encoded).unbind())
}

/// How many columns a codepoint takes, as the terminal lays it out: 0, 1, or 2 if it's wide.
/// Summing these over a string is right only while grapheme clustering (mode 2027) is off.
#[pyfunction]
fn codepoint_width(codepoint: char) -> u8 {
    unicode::codepoint_width(codepoint)
}

/// The first grapheme cluster of `text`, as the terminal lays it out with grapheme clustering (mode 2027) on:
/// how many codepoints it takes, and how many columns. `(0, 0)` only for empty text.
#[pyfunction]
fn grapheme_width(text: &str) -> (usize, u8) {
    unicode::grapheme_width(&text.chars().collect::<Vec<_>>())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(encode_focus, m)?)?;
    m.add_function(wrap_pyfunction!(encode_paste, m)?)?;
    m.add_function(wrap_pyfunction!(is_paste_safe, m)?)?;
    m.add_function(wrap_pyfunction!(encode_color_scheme, m)?)?;
    m.add_function(wrap_pyfunction!(encode_size_report, m)?)?;
    m.add_function(wrap_pyfunction!(codepoint_width, m)?)?;
    m.add_function(wrap_pyfunction!(grapheme_width, m)?)?;
    Ok(())
}

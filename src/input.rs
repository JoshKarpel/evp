use libghostty_vt::ffi;
use libghostty_vt::key::{self, Mods};
use libghostty_vt::mouse;
use libghostty_vt::terminal::Mode;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::Owned;
use crate::enums::parse;
use crate::errors::ghostty_error;
use crate::terminal::Terminal;

/// Encodes key events as the bytes a program reads, as the terminal's modes say.
#[pyclass(module = "evp")]
pub struct KeyEncoder {
    terminal: Py<Terminal>,
    encoder: Owned<key::Encoder<'static>>,
    event: Owned<key::Event<'static>>,
    macos_option_as_alt: key::OptionAsAlt,
}

#[pymethods]
impl KeyEncoder {
    #[new]
    #[pyo3(signature = (terminal, *, macos_option_as_alt = ffi::OptionAsAlt::FALSE))]
    fn new(terminal: Py<Terminal>, macos_option_as_alt: u32) -> PyResult<Self> {
        Ok(KeyEncoder {
            terminal,
            encoder: Owned(key::Encoder::new().map_err(ghostty_error)?),
            event: Owned(key::Event::new().map_err(ghostty_error)?),
            macos_option_as_alt: parse("OptionAsAlt", macos_option_as_alt)?,
        })
    }

    /// The bytes a key event sends the program: empty for one that sends nothing, like a modifier's press.
    #[pyo3(signature = (
        key,
        *,
        action = ffi::KeyAction::PRESS,
        mods = 0,
        consumed_mods = 0,
        text = None,
        unshifted_codepoint = None,
        composing = false,
    ))]
    #[expect(
        clippy::too_many_arguments,
        reason = "a key event's fields, as keyword arguments"
    )]
    fn encode(
        &mut self,
        py: Python<'_>,
        key: u32,
        action: u32,
        mods: u16,
        consumed_mods: u16,
        text: Option<String>,
        unshifted_codepoint: Option<char>,
        composing: bool,
    ) -> PyResult<Py<PyBytes>> {
        let terminal = self.terminal.borrow_mut(py);
        // The terminal's modes can change with every byte the program writes, so read them each time.
        self.encoder
            .0
            .set_options_from_terminal(&terminal.inner.0)
            .set_macos_option_as_alt(self.macos_option_as_alt);
        self.event
            .0
            .set_key(parse("Key", key)?)
            .set_action(parse("KeyAction", action)?)
            .set_mods(Mods::from_bits_retain(mods))
            .set_consumed_mods(Mods::from_bits_retain(consumed_mods))
            .set_utf8(text)
            .set_unshifted_codepoint(unshifted_codepoint.unwrap_or('\0'))
            .set_composing(composing);
        let mut encoded = Vec::new();
        self.encoder
            .0
            .encode_to_vec(&self.event.0, &mut encoded)
            .map_err(ghostty_error)?;
        Ok(PyBytes::new(py, &encoded).unbind())
    }
}

/// The modes libghostty's mouse encoder reads from a terminal: which events it reports, and in which format.
const MOUSE_MODES: [Mode; 8] = [
    Mode::X10_MOUSE,
    Mode::NORMAL_MOUSE,
    Mode::BUTTON_MOUSE,
    Mode::ANY_MOUSE,
    Mode::UTF8_MOUSE,
    Mode::SGR_MOUSE,
    Mode::URXVT_MOUSE,
    Mode::SGR_PIXELS_MOUSE,
];

/// What a mouse encoder last read from its terminal: its mouse modes and its size.
type Synced = ([bool; MOUSE_MODES.len()], (u16, u16));

/// Encodes mouse events as the bytes a program reads, as the terminal's mouse modes say.
#[pyclass(module = "evp")]
pub struct MouseEncoder {
    terminal: Py<Terminal>,
    encoder: Owned<mouse::Encoder<'static>>,
    event: Owned<mouse::Event<'static>>,
    cell_size: (u32, u32),
    track_last_cell: bool,
    /// Reading the terminal's modes, or setting the size, forgets the last cell `track_last_cell`
    /// reported motion in, so the encoder is synced only when one of them changed.
    synced: Option<Synced>,
}

#[pymethods]
impl MouseEncoder {
    #[new]
    #[pyo3(signature = (terminal, *, cell_width = 1, cell_height = 1, track_last_cell = false))]
    fn new(
        terminal: Py<Terminal>,
        cell_width: u32,
        cell_height: u32,
        track_last_cell: bool,
    ) -> PyResult<Self> {
        if cell_width == 0 || cell_height == 0 {
            return Err(PyValueError::new_err(
                "A cell's width and height must be above zero",
            ));
        }
        Ok(MouseEncoder {
            terminal,
            encoder: Owned(mouse::Encoder::new().map_err(ghostty_error)?),
            event: Owned(mouse::Event::new().map_err(ghostty_error)?),
            cell_size: (cell_width, cell_height),
            track_last_cell,
            synced: None,
        })
    }

    /// The bytes a mouse event at pixel `(x, y)` sends the program: empty when its modes don't report it.
    #[pyo3(signature = (action, x, y, *, button = None, mods = 0, any_button_pressed = false))]
    #[expect(
        clippy::too_many_arguments,
        reason = "a mouse event's fields, as keyword arguments"
    )]
    fn encode(
        &mut self,
        py: Python<'_>,
        action: u32,
        x: f32,
        y: f32,
        button: Option<u32>,
        mods: u16,
        any_button_pressed: bool,
    ) -> PyResult<Py<PyBytes>> {
        let terminal = self.terminal.borrow_mut(py);
        let terminal = &terminal.inner.0;
        let mut modes = [false; MOUSE_MODES.len()];
        for (is_set, &mode) in modes.iter_mut().zip(&MOUSE_MODES) {
            *is_set = terminal.mode(mode).map_err(ghostty_error)?;
        }
        let size = (
            terminal.cols().map_err(ghostty_error)?,
            terminal.rows().map_err(ghostty_error)?,
        );
        if self.synced != Some((modes, size)) {
            let (cell_width, cell_height) = self.cell_size;
            self.encoder
                .0
                .set_options_from_terminal(terminal)
                .set_track_last_cell(self.track_last_cell)
                .set_size(mouse::EncoderSize {
                    screen_width: u32::from(size.0).saturating_mul(cell_width),
                    screen_height: u32::from(size.1).saturating_mul(cell_height),
                    cell_width,
                    cell_height,
                    padding_top: 0,
                    padding_bottom: 0,
                    padding_right: 0,
                    padding_left: 0,
                });
            self.synced = Some((modes, size));
        }
        self.encoder.0.set_any_button_pressed(any_button_pressed);
        self.event
            .0
            .set_action(parse("MouseAction", action)?)
            .set_button(
                button
                    .map(|button| parse("MouseButton", button))
                    .transpose()?,
            )
            .set_mods(Mods::from_bits_retain(mods))
            .set_position(mouse::Position {
                x: position("x", x, self.cell_size.0)?,
                y: position("y", y, self.cell_size.1)?,
            });
        let mut encoded = Vec::new();
        self.encoder
            .0
            .encode_to_vec(&self.event.0, &mut encoded)
            .map_err(ghostty_error)?;
        Ok(PyBytes::new(py, &encoded).unbind())
    }

    /// Forget the last cell motion was reported in, so the next motion is reported even in the same cell.
    fn reset(&mut self) {
        self.encoder.0.reset();
    }
}

/// A mouse position libghostty can convert without overflowing, which aborts a debug build and is
/// undefined behavior in a release one: to a cell, a `u16` once negatives are clamped to 0,
/// and for SGR-Pixels, to an `i32`.
/// Ghostty reports a position beyond the screen in its edge cell, so the bound costs nothing.
fn position(name: &str, pixels: f32, cell: u32) -> PyResult<f32> {
    let pixels_limit = 2f64.powi(31);
    let limit = pixels_limit.min(65_536.0 * f64::from(cell));
    if pixels.is_finite() && (-pixels_limit..limit).contains(&f64::from(pixels)) {
        Ok(pixels)
    } else {
        Err(PyValueError::new_err(format!(
            "{name} must be at least -2**31 and less than {limit} pixels, not {pixels}"
        )))
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<KeyEncoder>()?;
    m.add_class::<MouseEncoder>()?;
    Ok(())
}

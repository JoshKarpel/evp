use libghostty_vt::ffi;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// An enum's members, as `(name, value)` pairs.
type Members = &'static [(&'static str, u64)];

/// Members named as their C constants are, read from libghostty-vt-sys's bindings, so their values have
/// one source: `members!(ffi::Key { A, B })`, or `members!(SHIFT = ffi::MODS_SHIFT)` where the names differ.
macro_rules! members {
    ($module:ident { $($name:ident),* $(,)? }) => {
        &[$((stringify!($name), ffi::$module::$name as u64)),*]
    };
    ($($name:ident = $value:expr),* $(,)?) => {
        &[$((stringify!($name), $value as u64)),*]
    };
}

/// Every enum evp exposes: its name, its base (`IntEnum`, or `IntFlag` for bit sets), docstring and members.
const ENUMS: &[(&str, &str, &str, Members)] = &[
    (
        "Key",
        "IntEnum",
        "A physical key, independent of the keyboard layout, as the W3C UI Events `KeyboardEvent.code` names it.",
        members!(Key {
            UNIDENTIFIED, BACKQUOTE, BACKSLASH, BRACKET_LEFT, BRACKET_RIGHT, COMMA,
            DIGIT_0, DIGIT_1, DIGIT_2, DIGIT_3, DIGIT_4, DIGIT_5, DIGIT_6, DIGIT_7, DIGIT_8, DIGIT_9,
            EQUAL, INTL_BACKSLASH, INTL_RO, INTL_YEN,
            A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z,
            MINUS, PERIOD, QUOTE, SEMICOLON, SLASH,
            ALT_LEFT, ALT_RIGHT, BACKSPACE, CAPS_LOCK, CONTEXT_MENU, CONTROL_LEFT, CONTROL_RIGHT,
            ENTER, META_LEFT, META_RIGHT, SHIFT_LEFT, SHIFT_RIGHT, SPACE, TAB,
            CONVERT, KANA_MODE, NON_CONVERT,
            DELETE, END, HELP, HOME, INSERT, PAGE_DOWN, PAGE_UP,
            ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT, ARROW_UP,
            NUM_LOCK, NUMPAD_0, NUMPAD_1, NUMPAD_2, NUMPAD_3, NUMPAD_4,
            NUMPAD_5, NUMPAD_6, NUMPAD_7, NUMPAD_8, NUMPAD_9,
            NUMPAD_ADD, NUMPAD_BACKSPACE, NUMPAD_CLEAR, NUMPAD_CLEAR_ENTRY, NUMPAD_COMMA,
            NUMPAD_DECIMAL, NUMPAD_DIVIDE, NUMPAD_ENTER, NUMPAD_EQUAL,
            NUMPAD_MEMORY_ADD, NUMPAD_MEMORY_CLEAR, NUMPAD_MEMORY_RECALL, NUMPAD_MEMORY_STORE,
            NUMPAD_MEMORY_SUBTRACT, NUMPAD_MULTIPLY, NUMPAD_PAREN_LEFT, NUMPAD_PAREN_RIGHT,
            NUMPAD_SUBTRACT, NUMPAD_SEPARATOR, NUMPAD_UP, NUMPAD_DOWN, NUMPAD_RIGHT, NUMPAD_LEFT,
            NUMPAD_BEGIN, NUMPAD_HOME, NUMPAD_END, NUMPAD_INSERT, NUMPAD_DELETE,
            NUMPAD_PAGE_UP, NUMPAD_PAGE_DOWN,
            ESCAPE, F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12, F13,
            F14, F15, F16, F17, F18, F19, F20, F21, F22, F23, F24, F25,
            FN, FN_LOCK, PRINT_SCREEN, SCROLL_LOCK, PAUSE,
            BROWSER_BACK, BROWSER_FAVORITES, BROWSER_FORWARD, BROWSER_HOME, BROWSER_REFRESH,
            BROWSER_SEARCH, BROWSER_STOP, EJECT, LAUNCH_APP_1, LAUNCH_APP_2, LAUNCH_MAIL,
            MEDIA_PLAY_PAUSE, MEDIA_SELECT, MEDIA_STOP, MEDIA_TRACK_NEXT, MEDIA_TRACK_PREVIOUS,
            POWER, SLEEP, AUDIO_VOLUME_DOWN, AUDIO_VOLUME_MUTE, AUDIO_VOLUME_UP, WAKE_UP,
            COPY, CUT, PASTE,
        }),
    ),
    (
        "KeyAction",
        "IntEnum",
        "What a key did: pressed, released, or repeated while held.",
        members!(KeyAction { RELEASE, PRESS, REPEAT }),
    ),
    (
        "Mods",
        "IntFlag",
        "Modifier keys held during a key or mouse event. A `_SIDE` flag means the right-hand key of its modifier.",
        members!(
            SHIFT = ffi::MODS_SHIFT,
            CTRL = ffi::MODS_CTRL,
            ALT = ffi::MODS_ALT,
            SUPER = ffi::MODS_SUPER,
            CAPS_LOCK = ffi::MODS_CAPS_LOCK,
            NUM_LOCK = ffi::MODS_NUM_LOCK,
            SHIFT_SIDE = ffi::MODS_SHIFT_SIDE,
            CTRL_SIDE = ffi::MODS_CTRL_SIDE,
            ALT_SIDE = ffi::MODS_ALT_SIDE,
            SUPER_SIDE = ffi::MODS_SUPER_SIDE,
        ),
    ),
    (
        "OptionAsAlt",
        "IntEnum",
        "Which of macOS's option keys a key encoder treats as alt.",
        members!(OptionAsAlt { FALSE, TRUE, LEFT, RIGHT }),
    ),
    (
        "MouseAction",
        "IntEnum",
        "What the mouse did: pressed a button, released one, or moved.",
        members!(MouseAction { PRESS, RELEASE, MOTION }),
    ),
    (
        "MouseButton",
        "IntEnum",
        "A mouse button. Buttons four and five are the scroll wheel's up and down, six and seven its left and right.",
        members!(MouseButton {
            UNKNOWN, LEFT, RIGHT, MIDDLE, FOUR, FIVE, SIX, SEVEN, EIGHT, NINE, TEN, ELEVEN,
        }),
    ),
    (
        "FocusEvent",
        "IntEnum",
        "Whether the terminal gained or lost focus.",
        members!(FocusEvent { GAINED, LOST }),
    ),
    (
        "ColorScheme",
        "IntEnum",
        "Whether the terminal's colors are light or dark.",
        members!(ColorScheme { LIGHT, DARK }),
    ),
    (
        "SizeReportStyle",
        "IntEnum",
        "\
Which size report to encode: an in-band report (mode 2048),
or the reply to XTWINOPS 14, 16 or 18 (the text area in pixels, a cell in pixels, the text area in cells).",
        members!(SizeReportStyle { MODE_2048, CSI_14_T, CSI_16_T, CSI_18_T }),
    ),
    (
        "ClipboardLocation",
        "IntEnum",
        "Which clipboard a program wrote to.",
        members!(ClipboardLocation { STANDARD, SELECTION, PRIMARY }),
    ),
    (
        "FormatterFormat",
        "IntEnum",
        "What a formatter writes: plain text, VT sequences that redraw the screen, or HTML.",
        members!(FormatterFormat { PLAIN, VT, HTML }),
    ),
];

/// Convert a Python enum's value into libghostty-vt's Rust enum, raising `ValueError` for any other value.
pub(crate) fn parse<T: TryFrom<u32>>(name: &str, value: u32) -> PyResult<T> {
    T::try_from(value).map_err(|_| PyValueError::new_err(format!("{value} is not a valid {name}")))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    let enum_module = py.import("enum")?;
    for &(name, base, doc, members) in ENUMS {
        let kwargs = PyDict::new(py);
        kwargs.set_item("module", "evp")?;
        let class = enum_module
            .getattr(base)?
            .call((name, members.to_vec()), Some(&kwargs))?;
        class.setattr("__doc__", doc)?;
        m.add(name, class)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// libghostty's keys run from 0 without gaps, so a key the table leaves out shows as a missing value.
    #[test]
    fn every_key_is_listed() {
        let (_, _, _, keys) = ENUMS.iter().find(|(name, ..)| *name == "Key").unwrap();
        let mut values = keys.iter().map(|&(_, value)| value).collect::<Vec<_>>();
        values.sort_unstable();
        let last = u64::from(ffi::Key::PASTE);
        assert_eq!(values, (0..=last).collect::<Vec<_>>());
        assert!(libghostty_vt::key::Key::try_from(u32::try_from(last + 1).unwrap()).is_err());
    }
}

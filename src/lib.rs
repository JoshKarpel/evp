use pyo3::prelude::*;

mod encode;
mod enums;
mod errors;
mod format;
mod input;
mod render;
mod style;
mod terminal;

/// A libghostty object a Python object owns: a render state, an iterator, a tracked grid reference, an encoder.
pub(crate) struct Owned<T>(pub(crate) T);

// SAFETY: as for `OwnedTerminal`: libghostty's objects have no thread affinity, and only the
// `&mut self` methods of the Python object that owns one touch it, so each access has exclusive use
// of it whatever thread it runs on.
unsafe impl<T> Send for Owned<T> {}
unsafe impl<T> Sync for Owned<T> {}

#[pymodule]
fn _evp(m: &Bound<'_, PyModule>) -> PyResult<()> {
    errors::register(m)?;
    enums::register(m)?;
    encode::register(m)?;
    style::register(m)?;
    terminal::register(m)?;
    render::register(m)?;
    input::register(m)?;
    format::register(m)?;
    Ok(())
}

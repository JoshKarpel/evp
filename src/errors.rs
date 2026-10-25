use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(
    evp,
    GhosttyError,
    PyException,
    "An error libghostty-vt returned."
);

/// A libghostty-vt error as the Python exception it raises, for `map_err`.
pub(crate) fn ghostty_error(error: libghostty_vt::Error) -> PyErr {
    GhosttyError::new_err(error.to_string())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("GhosttyError", m.py().get_type::<GhosttyError>())?;
    Ok(())
}

use pyo3::prelude::*;

mod errors;
mod render;
mod style;
mod terminal;

#[pymodule]
fn _evp(m: &Bound<'_, PyModule>) -> PyResult<()> {
    errors::register(m)?;
    style::register(m)?;
    terminal::register(m)?;
    render::register(m)?;
    Ok(())
}

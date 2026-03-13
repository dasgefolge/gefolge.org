#![deny(rust_2018_idioms, unused, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    pyo3::{
        create_exception,
        prelude::*,
        wrap_pyfunction,
    },
    serenity::{
        model::prelude::*,
        utils::MessageBuilder,
    },
};

create_exception!(peter, CommandError, pyo3::exceptions::PyRuntimeError);

fn user_to_id(user: Bound<'_, PyAny>) -> PyResult<UserId> {
    if let Ok(snowflake) = user.getattr("snowflake") {
        // support gefolge_web.login.Mensch arguments
        Ok(UserId::new(snowflake.extract()?))
    } else {
        // support plain snowflakes
        Ok(UserId::new(user.extract()?))
    }
}

#[pyfunction] fn escape(text: &str) -> String {
    let mut builder = MessageBuilder::default();
    builder.push_safe(text);
    builder.build()
}

#[pyfunction] fn add_role(user_id: Bound<'_, PyAny>, role_id: u64) -> PyResult<()> {
    peter_ipc::add_role(user_to_id(user_id)?, RoleId::new(role_id))
        .map_err(|e| CommandError::new_err(e.to_string()))
}

#[pyfunction] fn channel_msg(channel_id: u64, msg: String) -> PyResult<()> {
    peter_ipc::channel_msg(ChannelId::new(channel_id), msg)
        .map_err(|e| CommandError::new_err(e.to_string()))
}

#[pyfunction] fn msg(user_id: Bound<'_, PyAny>, msg: String) -> PyResult<()> {
    peter_ipc::msg(user_to_id(user_id)?, msg)
        .map_err(|e| CommandError::new_err(e.to_string()))
}

#[pyfunction] fn quit() -> PyResult<()> {
    peter_ipc::quit()
        .map_err(|e| CommandError::new_err(e.to_string()))
}

#[pyfunction] fn set_display_name(user_id: Bound<'_, PyAny>, new_display_name: String) -> PyResult<()> {
    peter_ipc::set_display_name(user_to_id(user_id)?, new_display_name)
        .map_err(|e| CommandError::new_err(e.to_string()))
}

#[pymodule] fn peter(_: Python<'_>, m: Bound<'_, PyModule>) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(escape))?;
    //TODO make sure that all IPC commands are listed below
    m.add_wrapped(wrap_pyfunction!(add_role))?;
    m.add_wrapped(wrap_pyfunction!(channel_msg))?;
    m.add_wrapped(wrap_pyfunction!(msg))?;
    m.add_wrapped(wrap_pyfunction!(quit))?;
    m.add_wrapped(wrap_pyfunction!(set_display_name))?;
    Ok(())
}

use {
    pyo3::{
        exceptions::*,
        prelude::*,
        types::*,
    },
    serde_json::Value as Json,
    crate::{
        DB_POOL,
        TOKIO_RUNTIME,
        util::SqlxResultExt as _,
    },
};

#[pyclass]
#[derive(Debug, PartialEq, Eq, Hash)]
enum Table {
    Events,
    Locations,
    Profiles,
    UserData,
}

fn json_to_py(py: Python<'_>, json: Json) -> PyResult<Py<PyAny>> {
    Ok(match json {
        Json::Null => py.None(),
        Json::Bool(value) => value.into_py(py),
        Json::Number(number) => if let Some(value) = number.as_u64() {
            value.into_py(py)
        } else if let Some(value) = number.as_i64() {
            value.into_py(py)
        } else if let Some(value) = number.as_f64() {
            value.into_py(py)
        } else {
            unreachable!("serde_json::Number is neither u64 nor i64 nor f64")
        },
        Json::String(value) => value.into_py(py),
        Json::Array(value) => PyList::new(py, value.into_iter().map(|value| json_to_py(py, value)).collect::<PyResult<Vec<_>>>()?).into(),
        Json::Object(value) => {
            let dict = PyDict::new(py);
            for (k, v) in value {
                dict.set_item(k, json_to_py(py, v)?)?;
            }
            dict.into()
        }
    })
}

#[pyfunction] fn get_json(py: Python<'_>, table: &Table, id: &PyAny) -> PyResult<Py<PyAny>> {
    json_to_py(py, TOKIO_RUNTIME.get(py).block_on(match table {
        Table::Events => sqlx::query_scalar!("SELECT value FROM json_events WHERE id = $1", id.extract::<&str>()?).fetch_one(DB_POOL.get(py)),
        Table::Locations => sqlx::query_scalar!("SELECT value FROM json_locations WHERE id = $1", id.extract::<&str>()?).fetch_one(DB_POOL.get(py)),
        Table::Profiles => sqlx::query_scalar!("SELECT value FROM json_profiles WHERE id = $1", id.extract::<u64>()? as i64).fetch_one(DB_POOL.get(py)),
        Table::UserData => sqlx::query_scalar!("SELECT value FROM json_user_data WHERE id = $1", id.extract::<u64>()? as i64).fetch_one(DB_POOL.get(py)),
    }).to_py()?)
}

//TODO skip serialization/deserialization step across ffi boundary?
#[pyfunction] fn set_json(py: Python<'_>, table: &Table, id: &PyAny, value: &str) -> PyResult<()> {
    let value = serde_json::from_str::<Json>(value).map_err(|e| PyValueError::new_err(e.to_string()))?;
    TOKIO_RUNTIME.get(py).block_on(match table {
        Table::Events => sqlx::query_scalar!("INSERT INTO json_events (id, value) VALUES ($1, $2)", id.extract::<&str>()?, value).execute(DB_POOL.get(py)),
        Table::Locations => sqlx::query_scalar!("INSERT INTO json_locations (id, value) VALUES ($1, $2)", id.extract::<&str>()?, value).execute(DB_POOL.get(py)),
        Table::Profiles => sqlx::query_scalar!("INSERT INTO json_profiles (id, value) VALUES ($1, $2)", id.extract::<u64>()? as i64, value).execute(DB_POOL.get(py)),
        Table::UserData => sqlx::query_scalar!("INSERT INTO json_user_data (id, value) VALUES ($1, $2)", id.extract::<u64>()? as i64, value).execute(DB_POOL.get(py)),
    }).to_py()?;
    Ok(())
}

//TODO skip serialization/deserialization step across ffi boundary?
#[pyfunction] fn set_json_if_not_exists(py: Python<'_>, table: &Table, id: &PyAny, value: &str) -> PyResult<()> {
    let value = serde_json::from_str::<Json>(value).map_err(|e| PyValueError::new_err(e.to_string()))?;
    TOKIO_RUNTIME.get(py).block_on(match table {
        Table::Events => sqlx::query_scalar!("INSERT INTO json_events (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.extract::<&str>()?, value).execute(DB_POOL.get(py)),
        Table::Locations => sqlx::query_scalar!("INSERT INTO json_locations (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.extract::<&str>()?, value).execute(DB_POOL.get(py)),
        Table::Profiles => sqlx::query_scalar!("INSERT INTO json_profiles (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.extract::<u64>()? as i64, value).execute(DB_POOL.get(py)),
        Table::UserData => sqlx::query_scalar!("INSERT INTO json_user_data (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.extract::<u64>()? as i64, value).execute(DB_POOL.get(py)),
    }).to_py()?;
    Ok(())
}

pub(crate) fn module(py: Python<'_>) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "db")?;
    m.add_class::<Table>()?;
    m.add_function(wrap_pyfunction!(get_json, m)?)?;
    m.add_function(wrap_pyfunction!(set_json, m)?)?;
    m.add_function(wrap_pyfunction!(set_json_if_not_exists, m)?)?;
    Ok(m)
}

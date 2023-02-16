#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]

use {
    pyo3::prelude::*,
    sqlx::{
        PgPool,
        postgres::PgConnectOptions,
    },
    crate::util::PyLazy,
};

mod util;

pub(crate) static TOKIO_RUNTIME: PyLazy<tokio::runtime::Runtime> = PyLazy::new(|_| tokio::runtime::Builder::new_multi_thread().enable_all().build().expect("failed to build global Tokio runtime"));
pub(crate) static DB_POOL: PyLazy<PgPool> = PyLazy::new(|py| TOKIO_RUNTIME.get(py).block_on(PgPool::connect_with(
    PgConnectOptions::default().username("fenhl").database("gefolge").application_name("gefolge-web")
)).expect("failed to build global PostgreSQL connection pool"));

macro_rules! py_mod {
    ($($name:ident,)*) => {
        $(mod $name;)*

        #[pymodule]
        fn rs(py: Python<'_>, m: &PyModule) -> PyResult<()> {
            let sys_modules = py.import("sys")?.getattr("modules")?;
            $(
                let $name = $name::module(py)?;
                m.add_submodule($name)?;
                sys_modules.set_item(concat!("rs.", stringify!($name)), $name)?;
            )*
            Ok(())
        }
    };
}

py_mod!(
    db,
);

use pyo3::{
    exceptions::*,
    once_cell::GILOnceCell,
    prelude::*,
};

pub(crate) trait SqlxResultExt {
    type Ok;

    fn to_py(self) -> PyResult<Self::Ok>;
}

impl<T> SqlxResultExt for sqlx::Result<T> {
    type Ok = T;

    fn to_py(self) -> PyResult<T> {
        self.map_err(|e| match e {
            sqlx::Error::Configuration(_) => PyValueError::new_err(e.to_string()),
            sqlx::Error::Database(e) => PyRuntimeError::new_err(e.to_string()),
            sqlx::Error::Io(e) => e.into(),
            sqlx::Error::Tls(e) => PyConnectionError::new_err(e.to_string()),
            sqlx::Error::Protocol(e) => PyConnectionError::new_err(e),
            sqlx::Error::RowNotFound => PyLookupError::new_err(e.to_string()),
            sqlx::Error::TypeNotFound { .. } => PyTypeError::new_err(e.to_string()),
            sqlx::Error::ColumnIndexOutOfBounds { .. } => PyIndexError::new_err(e.to_string()),
            sqlx::Error::ColumnNotFound(_) => PyLookupError::new_err(e.to_string()),
            sqlx::Error::ColumnDecode { .. } => PyValueError::new_err(e.to_string()),
            sqlx::Error::Decode { .. } => PyValueError::new_err(e.to_string()),
            sqlx::Error::PoolTimedOut => PyTimeoutError::new_err(e.to_string()),
            sqlx::Error::PoolClosed => PyConnectionResetError::new_err(e.to_string()),
            sqlx::Error::WorkerCrashed => PyRuntimeError::new_err(e.to_string()),
            _ => PyException::new_err(e.to_string()),
        })
    }
}

pub(crate) struct PyLazy<T> {
    cell: GILOnceCell<T>,
    init: for<'r> fn(Python<'r>) -> T,
}

impl<T> PyLazy<T> {
    pub(crate) const fn new(init: for<'r> fn(Python<'r>) -> T) -> Self {
        Self {
            cell: GILOnceCell::new(),
            init,
        }
    }

    pub(crate) fn get(&self, py: Python<'_>) -> &T {
        self.cell.get_or_init(py, || (self.init)(py))
    }
}

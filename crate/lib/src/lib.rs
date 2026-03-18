#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

pub mod config;
pub mod db;
pub mod event;
pub mod money;
#[cfg(feature = "peter")] pub mod peter;
pub mod time;
pub mod websocket;

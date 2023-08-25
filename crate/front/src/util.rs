use rocket::{
    Responder,
    http::Status,
};

#[derive(Responder)]
pub(crate) enum StatusOrError<E> {
    Status(Status),
    Err(E),
}

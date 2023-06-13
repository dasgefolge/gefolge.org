use {
    std::fmt,
    chrono::{
        LocalResult,
        prelude::*,
    },
    rocket::{
        Responder,
        http::Status,
        response::content::RawHtml,
    },
    rocket_util::html,
};

#[derive(Responder)]
pub(crate) enum StatusOrError<E> {
    Status(Status),
    Err(E),
}

pub(crate) fn format_date_range<Z: TimeZone>(start: DateTime<Z>, end: DateTime<Z>) -> RawHtml<String>
where Z::Offset: fmt::Display { //TODO respect user preferences including event timezone override toggle
    html! {
        span(class = "daterange", data_start = start.timestamp_millis(), data_end = end.timestamp_millis()) {
            @if start.year() != end.year() {
                : start.format("%d.%m.%Y").to_string();
                : "–";
                : end.format("%d.%m.%Y").to_string();
            } else if start.month() != end.month() {
                : start.format("%d.%m.").to_string();
                : "–";
                : end.format("%d.%m.%Y").to_string();
            } else if start.day() != end.day() {
                : start.format("%d.").to_string();
                : "–";
                : end.format("%d.%m.%Y").to_string();
            } else {
                : start.format("%d.%m.%Y").to_string();
            }
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum TimeFromLocalError<T> {
    #[error("invalid timestamp")]
    None,
    #[error("ambiguous timestamp")]
    Ambiguous([T; 2]),
}

pub(crate) trait LocalResultExt {
    type Ok;

    fn single_ok(self) -> Result<Self::Ok, TimeFromLocalError<Self::Ok>>;
}

impl<T> LocalResultExt for LocalResult<T> {
    type Ok = T;

    fn single_ok(self) -> Result<T, TimeFromLocalError<T>> {
        match self {
            LocalResult::None => Err(TimeFromLocalError::None),
            LocalResult::Single(value) => Ok(value),
            LocalResult::Ambiguous(value1, value2) => Err(TimeFromLocalError::Ambiguous([value1, value2])),
        }
    }
}

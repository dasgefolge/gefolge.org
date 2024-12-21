use {
    chrono::prelude::*,
    chrono_tz::{
        Europe,
        Tz,
    },
    rocket::response::content::RawHtml,
    rocket_util::html,
    gefolge_web_lib::time::MaybeLocalDateTime,
    crate::user,
};

pub(crate) fn format_date_range(viewer_data: &user::Data, start: MaybeLocalDateTime, end: MaybeLocalDateTime) -> RawHtml<String> {
    fn format_date_range_noscript(start: DateTime<Tz>, end: DateTime<Tz>) -> String {
        if start.year() != end.year() {
            format!("{}–{}", start.format("%d.%m.%Y"), end.format("%d.%m.%Y"))
        } else if start.month() != end.month() {
            format!("{}–{}", start.format("%d.%m."), end.format("%d.%m.%Y"))
        } else if start.day() != end.day() {
            format!("{}–{}", start.format("%d."), end.format("%d.%m.%Y"))
        } else {
            start.format("%d.%m.%Y").to_string()
        }
    }

    match (viewer_data.timezone, viewer_data.event_timezone_override, start, end) {
        (_, _, MaybeLocalDateTime::Nonlocal(_), MaybeLocalDateTime::Local(_)) => unimplemented!("tried to format date range with nonlocal start and local end"),
        (_, _, MaybeLocalDateTime::Local(_), MaybeLocalDateTime::Nonlocal(_)) => unimplemented!("tried to format date range with local start and nonlocal end"),
        (None, _, MaybeLocalDateTime::Nonlocal(start), MaybeLocalDateTime::Nonlocal(end)) => {
            let start = start.with_timezone(&Europe::Berlin);
            let end = end.with_timezone(&Europe::Berlin);
            html! {
                span(class = "daterange", title = Europe::Berlin.name(), data_start = start.timestamp_millis(), data_end = end.timestamp_millis()) {
                    : format_date_range_noscript(start, end);
                }
            }
        }
        (Some(user_timezone), _, MaybeLocalDateTime::Nonlocal(start), MaybeLocalDateTime::Nonlocal(end)) => {
            let start = start.with_timezone(&user_timezone);
            let end = end.with_timezone(&user_timezone);
            html! {
                span(class = "daterange", title = user_timezone.name(), data_start = start.timestamp_millis(), data_end = end.timestamp_millis(), data_timezone = user_timezone.name()) {
                    : format_date_range_noscript(start, end);
                }
            }
        }
        (None, false, MaybeLocalDateTime::Local(start), MaybeLocalDateTime::Local(end)) => {
            if start.timezone() != end.timezone() { unimplemented!("tried to format date range with different timezones at start vs end") }
            html! {
                span(class = "daterange", title = start.timezone().name(), data_start = start.timestamp_millis(), data_end = end.timestamp_millis()) {
                    : format_date_range_noscript(start, end);
                }
            }
        }
        (Some(user_timezone), false, MaybeLocalDateTime::Local(start), MaybeLocalDateTime::Local(end)) => {
            let start = start.with_timezone(&user_timezone);
            let end = end.with_timezone(&user_timezone);
            html! {
                span(class = "daterange", title = user_timezone.name(), data_start = start.timestamp_millis(), data_end = end.timestamp_millis(), data_timezone = user_timezone.name()) {
                    : format_date_range_noscript(start, end);
                }
            }
        }
        (_, true, MaybeLocalDateTime::Local(start), MaybeLocalDateTime::Local(end)) => {
            if start.timezone() != end.timezone() { unimplemented!("tried to format date range with different timezones at start vs end") }
            html! {
                span(class = "daterange", title = start.timezone().name(), data_start = start.timestamp_millis(), data_end = end.timestamp_millis(), data_timezone = start.timezone().name()) {
                    : format_date_range_noscript(start, end);
                }
            }
        }
    }
}

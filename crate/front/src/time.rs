use {
    jiff::{
        ZonedDateTime,
        civil,
    },
    rocket::response::content::RawHtml,
    rocket_util::html,
    gefolge_web_lib::{
        time::MaybeLocalDateTime,
        user,
    },
};

pub(crate) fn format_datetime(viewer_data: &user::Data, datetime: MaybeLocalDateTime, long: bool) -> RawHtml<String> {
    fn format_datetime_noscript(datetime: ZonedDateTime) -> String {
        datetime.strftime("%d.%m.%Y %H:%M").to_string()
    }

    match (&viewer_data.timezone, viewer_data.event_timezone_override, datetime) {
        (None, _, MaybeLocalDateTime::Nonlocal(datetime)) => {
            let datetime = datetime.in_tz("Europe/Berlin").unwrap();
            html! {
                span(class = "datetime", title = "Europe/Berlin", data_timestamp = datetime.timestamp().as_millisecond(), data_long = long.to_string()) {
                    : format_datetime_noscript(datetime);
                }
            }
        }
        (Some(user_timezone), _, MaybeLocalDateTime::Nonlocal(datetime)) => {
            let datetime = datetime.to_zoned_datetime(user_timezone.clone());
            html! {
                span(class = "datetime", title = user_timezone.iana_name().unwrap(), data_timestamp = datetime.timestamp().as_millisecond(), data_long = long.to_string(), data_timezone = user_timezone.iana_name().unwrap()) {
                    : format_datetime_noscript(datetime);
                }
            }
        }
        (None, false, MaybeLocalDateTime::Local(datetime)) => html! {
            span(class = "datetime", title = datetime.time_zone().iana_name().unwrap(), data_timestamp = datetime.timestamp().as_millisecond(), data_long = long.to_string()) {
                : format_datetime_noscript(datetime);
            }
        },
        (Some(user_timezone), false, MaybeLocalDateTime::Local(datetime)) => {
            let datetime = datetime.with_time_zone(user_timezone.clone());
            html! {
                span(class = "datetime", title = user_timezone.iana_name().unwrap(), data_timestamp = datetime.timestamp().as_millisecond(), data_long = long.to_string(), data_timezone = user_timezone.iana_name().unwrap()) {
                    : format_datetime_noscript(datetime);
                }
            }
        }
        (_, true, MaybeLocalDateTime::Local(datetime)) => html! {
            span(class = "datetime", title = datetime.time_zone().iana_name().unwrap(), data_timestamp = datetime.timestamp().as_millisecond(), data_long = long.to_string(), data_timezone = datetime.time_zone().iana_name().unwrap()) {
                : format_datetime_noscript(datetime);
            }
        },
    }
}

pub(crate) fn format_date_range(start: civil::Date, end: civil::Date) -> RawHtml<String> {
    RawHtml(if start.year() != end.year() {
        format!("{}–{}", start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y"))
    } else if start.month() != end.month() {
        format!("{}–{}", start.strftime("%d.%m."), end.strftime("%d.%m.%Y"))
    } else if start.day() != end.day() {
        format!("{}–{}", start.strftime("%d."), end.strftime("%d.%m.%Y"))
    } else {
        start.strftime("%d.%m.%Y").to_string()
    })
}

pub(crate) fn format_datetime_range(viewer_data: &user::Data, start: MaybeLocalDateTime, end: MaybeLocalDateTime) -> RawHtml<String> {
    match (&viewer_data.timezone, viewer_data.event_timezone_override, start, end) {
        (_, _, MaybeLocalDateTime::Nonlocal(_), MaybeLocalDateTime::Local(_)) => unimplemented!("tried to format date range with nonlocal start and local end"),
        (_, _, MaybeLocalDateTime::Local(_), MaybeLocalDateTime::Nonlocal(_)) => unimplemented!("tried to format date range with local start and nonlocal end"),
        (None, _, MaybeLocalDateTime::Nonlocal(start), MaybeLocalDateTime::Nonlocal(end)) => {
            let start = start.in_tz("Europe/Berlin").unwrap();
            let end = end.in_tz("Europe/Berlin").unwrap();
            html! {
                span(class = "daterange", title = "Europe/Berlin", data_start = start.timestamp().as_millisecond(), data_end = end.timestamp().as_millisecond()) {
                    : format_date_range(start.date(), end.date());
                }
            }
        }
        (Some(user_timezone), _, MaybeLocalDateTime::Nonlocal(start), MaybeLocalDateTime::Nonlocal(end)) => {
            let start = start.to_zoned_datetime(user_timezone.clone());
            let end = end.to_zoned_datetime(user_timezone.clone());
            html! {
                span(class = "daterange", title = user_timezone.iana_name().unwrap(), data_start = start.timestamp().as_millisecond(), data_end = end.timestamp().as_millisecond(), data_timezone = user_timezone.iana_name().unwrap()) {
                    : format_date_range(start.date(), end.date());
                }
            }
        }
        (None, false, MaybeLocalDateTime::Local(start), MaybeLocalDateTime::Local(end)) => {
            if start.time_zone() != end.time_zone() { unimplemented!("tried to format date range with different timezones at start vs end") }
            html! {
                span(class = "daterange", title = start.time_zone().iana_name().unwrap(), data_start = start.timestamp().as_millisecond(), data_end = end.timestamp().as_millisecond()) {
                    : format_date_range(start.date(), end.date());
                }
            }
        }
        (Some(user_timezone), false, MaybeLocalDateTime::Local(start), MaybeLocalDateTime::Local(end)) => {
            let start = start.with_time_zone(user_timezone.clone());
            let end = end.with_time_zone(user_timezone.clone());
            html! {
                span(class = "daterange", title = user_timezone.iana_name().unwrap(), data_start = start.timestamp().as_millisecond(), data_end = end.timestamp().as_millisecond(), data_timezone = user_timezone.iana_name().unwrap()) {
                    : format_date_range(start.date(), end.date());
                }
            }
        }
        (_, true, MaybeLocalDateTime::Local(start), MaybeLocalDateTime::Local(end)) => {
            if start.time_zone() != end.time_zone() { unimplemented!("tried to format date range with different timezones at start vs end") }
            html! {
                span(class = "daterange", title = start.time_zone().iana_name().unwrap(), data_start = start.timestamp().as_millisecond(), data_end = end.timestamp().as_millisecond(), data_timezone = start.time_zone().iana_name().unwrap()) {
                    : format_date_range(start.date(), end.date());
                }
            }
        }
    }
}

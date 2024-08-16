use {
    std::{
        cmp::Ordering,
        str::FromStr,
    },
    chrono::prelude::*,
    chrono_tz::{
        Europe,
        Tz,
    },
    rocket::response::content::RawHtml,
    rocket_util::html,
    serde_plain::derive_deserialize_from_fromstr,
    wheel::traits::LocalResultExt as _,
    crate::user,
};

#[derive(Debug, Clone, Copy)]
pub(crate) enum MaybeAwareDateTime {
    Naive(NaiveDateTime),
    Aware(DateTime<Utc>),
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum ToMaybeLocalError {
    #[error(transparent)] FromLocal(#[from] wheel::traits::TimeFromLocalError<DateTime<Tz>>),
    #[error("tried to combine naive datetime {} with nonlocal context", .0.format("%Y-%m-%dT%H:%M:%S"))]
    NaiveNonlocal(NaiveDateTime),
}

impl MaybeAwareDateTime {
    pub(crate) fn to_maybe_local(&self, local_timezone: Option<Tz>) -> Result<MaybeLocalDateTime, ToMaybeLocalError> {
        Ok(if let Some(local_timezone) = local_timezone {
            MaybeLocalDateTime::Local(match self {
                Self::Naive(naive) => local_timezone.from_local_datetime(naive).single_ok()?,
                Self::Aware(aware) => aware.with_timezone(&local_timezone),
            })
        } else {
            MaybeLocalDateTime::Nonlocal(match self {
                Self::Naive(naive) => return Err(ToMaybeLocalError::NaiveNonlocal(*naive)),
                Self::Aware(aware) => *aware,
            })
        })
    }
}

#[derive(Debug, thiserror::Error)]
#[error("failed to parse maybe-aware datetime (aware: {e_aware}, naive: {e_naive})")]
pub(crate) struct MaybeAwareDateTimeParseError {
    e_aware: chrono::ParseError,
    e_naive: chrono::ParseError,
}

impl FromStr for MaybeAwareDateTime {
    type Err = MaybeAwareDateTimeParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%SZ") {
            Ok(aware) => Ok(Self::Aware(aware.and_utc())),
            Err(e_aware) => match NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S") {
                Ok(naive) => Ok(Self::Naive(naive)),
                Err(e_naive) => Err(Self::Err { e_aware, e_naive }),
            },
        }
    }
}

derive_deserialize_from_fromstr!(MaybeAwareDateTime, "naive or UTC datetime in ISO 8601 format");

#[derive(Clone, Copy)]
pub(crate) enum MaybeLocalDateTime {
    Nonlocal(DateTime<Utc>),
    Local(DateTime<Tz>),
}

impl MaybeLocalDateTime {
    fn with_timezone<Z: TimeZone>(&self, tz: &Z) -> DateTime<Z> {
        match self {
            Self::Nonlocal(nonlocal) => nonlocal.with_timezone(tz),
            Self::Local(local) => local.with_timezone(tz),
        }
    }
}

impl<Z: TimeZone> PartialEq<DateTime<Z>> for MaybeLocalDateTime {
    fn eq(&self, other: &DateTime<Z>) -> bool {
        self.with_timezone(&Utc) == *other
    }
}

impl<Z: TimeZone> PartialOrd<DateTime<Z>> for MaybeLocalDateTime {
    fn partial_cmp(&self, other: &DateTime<Z>) -> Option<Ordering> {
        self.with_timezone(&Utc).partial_cmp(other)
    }
}

impl<Z: TimeZone> PartialEq<MaybeLocalDateTime> for DateTime<Z> {
    fn eq(&self, other: &MaybeLocalDateTime) -> bool {
        *other == self.with_timezone(&Utc)
    }
}

impl<Z: TimeZone> PartialOrd<MaybeLocalDateTime> for DateTime<Z> {
    fn partial_cmp(&self, other: &MaybeLocalDateTime) -> Option<Ordering> {
        other.partial_cmp(&self.with_timezone(&Utc)).map(Ordering::reverse)
    }
}

impl PartialEq for MaybeLocalDateTime {
    fn eq(&self, other: &Self) -> bool {
        self.with_timezone(&Utc) == other.with_timezone(&Utc)
    }
}

impl Eq for MaybeLocalDateTime {}

impl PartialOrd for MaybeLocalDateTime {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for MaybeLocalDateTime {
    fn cmp(&self, other: &Self) -> Ordering {
        self.with_timezone(&Utc).cmp(&other.with_timezone(&Utc))
    }
}

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

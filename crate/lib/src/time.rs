use {
    std::{
        cmp::Ordering,
        fmt,
        ops::Range,
        str::FromStr,
    },
    jiff::{
        Span,
        Timestamp,
        ZonedDateTime,
        civil,
        tz::TimeZone,
    },
    serde_with::{
        DeserializeFromStr,
        SerializeDisplay,
    },
};

#[derive(Debug, Clone, Copy, DeserializeFromStr, SerializeDisplay)]
pub enum MaybeAwareDateTime {
    Naive(civil::DateTime),
    Aware(Timestamp),
}

#[derive(Debug, thiserror::Error)]
pub enum ToMaybeLocalError {
    #[error(transparent)] Jiff(#[from] jiff::Error),
    #[error("tried to combine naive datetime {} with nonlocal context", .0.strftime("%FT%T"))]
    NaiveNonlocal(civil::DateTime),
}

impl MaybeAwareDateTime {
    pub fn to_maybe_local(&self, local_timezone: Option<TimeZone>) -> Result<MaybeLocalDateTime, ToMaybeLocalError> {
        Ok(if let Some(local_timezone) = local_timezone {
            MaybeLocalDateTime::Local(match self {
                Self::Naive(naive) => naive.to_zoned_datetime(local_timezone)?,
                Self::Aware(aware) => aware.to_zoned_datetime(local_timezone),
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
pub struct MaybeAwareDateTimeParseError {
    e_aware: jiff::Error,
    e_naive: jiff::Error,
}

impl FromStr for MaybeAwareDateTime {
    type Err = MaybeAwareDateTimeParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match civil::DateTime::strptime("%FT%TZ", s) {
            Ok(aware) => Ok(Self::Aware(aware.to_zoned_datetime(TimeZone::UTC).unwrap().timestamp())),
            Err(e_aware) => match civil::DateTime::strptime("%FT%T", s) {
                Ok(naive) => Ok(Self::Naive(naive)),
                Err(e_naive) => Err(Self::Err { e_aware, e_naive }),
            },
        }
    }
}

impl fmt::Display for MaybeAwareDateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Naive(dt) => dt.strftime("%FT%T").fmt(f),
            Self::Aware(dt) => dt.strftime("%FT%TZ").fmt(f),
        }
    }
}

#[derive(Clone)]
pub enum MaybeLocalDateTime {
    Nonlocal(Timestamp),
    Local(ZonedDateTime),
}

impl MaybeLocalDateTime {
    pub fn with_timezone(&self, tz: TimeZone) -> ZonedDateTime {
        match self {
            Self::Nonlocal(nonlocal) => nonlocal.to_zoned_datetime(tz),
            Self::Local(local) => local.with_time_zone(tz),
        }
    }
}

impl From<MaybeLocalDateTime> for Timestamp {
    fn from(value: MaybeLocalDateTime) -> Self {
        match value {
            MaybeLocalDateTime::Nonlocal(timestamp) => timestamp,
            MaybeLocalDateTime::Local(date_time) => date_time.timestamp(),
        }
    }
}

impl<'a> From<&'a MaybeLocalDateTime> for Timestamp {
    fn from(value: &MaybeLocalDateTime) -> Self {
        match value {
            MaybeLocalDateTime::Nonlocal(timestamp) => *timestamp,
            MaybeLocalDateTime::Local(date_time) => date_time.timestamp(),
        }
    }
}

impl PartialEq for MaybeLocalDateTime {
    fn eq(&self, other: &Self) -> bool {
        Timestamp::from(self) == Timestamp::from(other)
    }
}

impl PartialEq<Timestamp> for MaybeLocalDateTime {
    fn eq(&self, other: &Timestamp) -> bool {
        Timestamp::from(self) == *other
    }
}

impl Eq for MaybeLocalDateTime {}

impl PartialOrd for MaybeLocalDateTime {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(Timestamp::from(self).cmp(&other.into()))
    }
}

impl PartialOrd<Timestamp> for MaybeLocalDateTime {
    fn partial_cmp(&self, other: &Timestamp) -> Option<Ordering> {
        Some(Timestamp::from(self).cmp(other))
    }
}

impl Ord for MaybeLocalDateTime {
    fn cmp(&self, other: &Self) -> Ordering {
        Timestamp::from(self).cmp(&other.into())
    }
}

pub fn iter_date_range(range: Range<civil::Date>) -> impl Iterator<Item = civil::Date> {
    range.start.series(Span::new().days(1)).take_while(move |d| *d < range.end)
}

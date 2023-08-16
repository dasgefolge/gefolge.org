use {
    std::{
        convert::Infallible as Never,
        time::Duration,
    },
    async_proto::Protocol,
    chrono::{
        offset::LocalResult,
        prelude::*,
    },
    chrono_tz::Tz,
    serde::Deserialize,
    sqlx::{
        PgPool,
        types::Json,
    },
    tokio::time::sleep,
    crate::websocket::WsSink,
};

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error("ambiguous timestamp: could refer to {} or {} UTC", .0.with_timezone(&Utc).format("%Y-%m-%d %H:%M:%S"), .1.with_timezone(&Utc).format("%Y-%m-%d %H:%M:%S"))]
    AmbiguousTimestamp(DateTime<Tz>, DateTime<Tz>),
    #[error("invalid timestamp")]
    InvalidTimestamp,
    #[error("there are multiple events currently ongoing")]
    MultipleCurrentEvents,
    #[error("unknown location ID in event data")]
    UnknownLocation, //TODO get rid of this variant using a foreign-key constraint
}

trait IntoResult<T> {
    fn into_result(self) -> Result<T, Error>;
}

impl IntoResult<DateTime<Tz>> for LocalResult<DateTime<Tz>> {
    fn into_result(self) -> Result<DateTime<Tz>, Error> {
        match self {
            Self::None => Err(Error::InvalidTimestamp),
            Self::Single(dt) => Ok(dt),
            Self::Ambiguous(dt1, dt2) => Err(Error::AmbiguousTimestamp(dt1, dt2)),
        }
    }
}

#[derive(Deserialize)]
struct Location {
    timezone: Tz,
}

impl Location {
    async fn load(db_pool: &PgPool, loc_id: &str) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query_scalar!(r#"SELECT value AS "value: Json<Self>" FROM json_locations WHERE id = $1"#, loc_id).fetch_optional(db_pool).await?.map(|Json(value)| value))
    }
}

enum LocationInfo {
    Unknown,
    Online,
    Known(Location),
}

impl LocationInfo {
    fn timezone(&self) -> Tz {
        match self {
            Self::Unknown | Self::Online => chrono_tz::Europe::Berlin,
            Self::Known(info) => info.timezone,
        }
    }
}

#[derive(Debug, Deserialize)]
struct Event {
    end: Option<NaiveDateTime>,
    location: Option<String>,
    start: Option<NaiveDateTime>,
    timezone: Option<Tz>,
}

impl Event {
    async fn location_info(&self, db_pool: &PgPool) -> Result<LocationInfo, Error> {
        Ok(match self.location.as_deref() {
            Some("online") => LocationInfo::Online,
            Some(name) => LocationInfo::Known(Location::load(db_pool, name).await?.ok_or(Error::UnknownLocation)?),
            None => LocationInfo::Unknown,
        })
    }

    async fn timezone(&self, db_pool: &PgPool) -> Result<Tz, Error> {
        Ok(if let Some(timezone) = self.timezone {
            timezone
        } else {
            self.location_info(db_pool).await?.timezone()
        })
    }

    async fn start(&self, db_pool: &PgPool) -> Result<Option<DateTime<Tz>>, Error> {
        Ok(if let Some(start_naive) = self.start {
            Some(self.timezone(db_pool).await?.from_local_datetime(&start_naive).into_result()?)
        } else {
            None
        })
    }

    async fn end(&self, db_pool: &PgPool) -> Result<Option<DateTime<Tz>>, Error> {
        Ok(if let Some(end_naive) = self.end {
            Some(self.timezone(db_pool).await?.from_local_datetime(&end_naive).into_result()?)
        } else {
            None
        })
    }
}

#[derive(Protocol)]
enum ServerMessage {
    Ping,
    Error {
        debug: String,
        display: String,
    },
    NoEvent,
    CurrentEvent {
        id: String,
        timezone: Tz,
    },
    LatestVersion([u8; 20]),
}

pub(crate) async fn client_session(db_pool: &PgPool, sink: WsSink) -> Result<Never, crate::websocket::Error> {
    let mut prev_state = None;
    loop {
        let now = Utc::now();
        let mut current_event = None;
        for row in sqlx::query!(r#"SELECT id, value AS "value: Json<Event>" FROM json_events"#).fetch_all(db_pool).await? {
            if let (Some(start), Some(end)) = (row.value.start(db_pool).await?, row.value.end(db_pool).await?) {
                if start <= now && now < end {
                    if current_event.replace((row.id, row.value.timezone(db_pool).await?)).is_some() {
                        return Err(Error::MultipleCurrentEvents.into())
                    }
                }
            }
        }
        if prev_state.map_or(true, |prev_state| prev_state != current_event) {
            if let Some((ref id, timezone)) = current_event {
                ServerMessage::CurrentEvent { id: id.clone(), timezone }.write_ws(&mut *sink.lock().await).await?;
            } else {
                ServerMessage::NoEvent.write_ws(&mut *sink.lock().await).await?;
            }
        }
        prev_state = Some(current_event);
        sleep(Duration::from_secs(10)).await;
    }
}

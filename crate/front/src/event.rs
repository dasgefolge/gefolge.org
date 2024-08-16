use {
    std::{
        convert::Infallible as Never,
        time::Duration,
    },
    async_proto::Protocol,
    chrono::prelude::*,
    chrono_tz::{
        Europe,
        Tz,
    },
    rocket::response::content::RawHtml,
    rocket_util::html,
    serde::Deserialize,
    sqlx::{
        PgExecutor,
        PgPool,
        types::Json,
    },
    tokio::time::sleep,
    crate::{
        time::{
            MaybeAwareDateTime,
            MaybeLocalDateTime,
        },
        websocket::WsSink,
    },
};

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] ToMaybeLocal(#[from] crate::time::ToMaybeLocalError),
    #[error("there are multiple events currently ongoing (at least {} and {})", .0[0], .0[1])]
    MultipleCurrentEvents([String; 2]),
    #[error("unknown location ID in event data")]
    UnknownLocation, //TODO get rid of this variant using a foreign-key constraint
}

#[derive(Deserialize)]
struct Location {
    timezone: Tz,
}

impl Location {
    async fn load(db_pool: impl PgExecutor<'_>, loc_id: &str) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query_scalar!(r#"SELECT value AS "value: Json<Self>" FROM json_locations WHERE id = $1"#, loc_id).fetch_optional(db_pool).await?.map(|Json(value)| value))
    }
}

enum LocationInfo {
    Unknown,
    Online,
    Known(Location),
}

impl LocationInfo {
    fn timezone(&self) -> Option<Tz> {
        match self {
            Self::Unknown | Self::Online => None,
            Self::Known(info) => Some(info.timezone),
        }
    }
}

#[derive(Debug, Deserialize)]
pub(crate) struct Event {
    end: Option<MaybeAwareDateTime>,
    location: Option<String>,
    name: Option<String>,
    start: Option<MaybeAwareDateTime>,
    timezone: Option<Tz>,
}

impl Event {
    async fn location_info(&self, db_pool: impl PgExecutor<'_>) -> Result<LocationInfo, Error> {
        Ok(match self.location.as_deref() {
            Some("online") => LocationInfo::Online,
            Some(name) => LocationInfo::Known(Location::load(db_pool, name).await?.ok_or(Error::UnknownLocation)?),
            None => LocationInfo::Unknown,
        })
    }

    async fn timezone(&self, db_pool: impl PgExecutor<'_>) -> Result<Option<Tz>, Error> {
        Ok(if let Some(timezone) = self.timezone {
            Some(timezone)
        } else {
            self.location_info(db_pool).await?.timezone()
        })
    }

    pub(crate) async fn start(&self, db_pool: impl PgExecutor<'_>) -> Result<Option<MaybeLocalDateTime>, Error> {
        Ok(if let Some(start) = self.start {
            Some(start.to_maybe_local(self.timezone(db_pool).await?)?)
        } else {
            None
        })
    }

    pub(crate) async fn end(&self, db_pool: impl PgExecutor<'_>) -> Result<Option<MaybeLocalDateTime>, Error> {
        Ok(if let Some(end) = self.end {
            Some(end.to_maybe_local(self.timezone(db_pool).await?)?)
        } else {
            None
        })
    }

    pub(crate) fn to_html(&self, id: &str) -> RawHtml<String> {
        html! {
            a(href = format!("/event/{id}")) : self.name.as_deref().unwrap_or(id);
        }
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
                    if let Some((other_id, _)) = current_event.replace((row.id.clone(), row.value.timezone(db_pool).await?)) {
                        return Err(Error::MultipleCurrentEvents([row.id, other_id]).into())
                    }
                }
            }
        }
        if prev_state.map_or(true, |prev_state| prev_state != current_event) {
            if let Some((ref id, timezone)) = current_event {
                ServerMessage::CurrentEvent { id: id.clone(), timezone: timezone.unwrap_or(Europe::Berlin) }.write_ws(&mut *sink.lock().await).await?;
            } else {
                ServerMessage::NoEvent.write_ws(&mut *sink.lock().await).await?;
            }
        }
        prev_state = Some(current_event);
        sleep(Duration::from_secs(10)).await;
    }
}

use {
    chrono_tz::Tz,
    rocket::response::content::RawHtml,
    rocket_util::html,
    serde::Deserialize,
    sqlx::{
        PgExecutor,
        types::Json,
    },
    crate::time::{
        MaybeAwareDateTime,
        MaybeLocalDateTime,
    },
};

#[derive(Debug, thiserror::Error)]
pub enum Error {
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
pub struct Event {
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

    pub async fn timezone(&self, db_pool: impl PgExecutor<'_>) -> Result<Option<Tz>, Error> {
        Ok(if let Some(timezone) = self.timezone {
            Some(timezone)
        } else {
            self.location_info(db_pool).await?.timezone()
        })
    }

    pub async fn start(&self, db_pool: impl PgExecutor<'_>) -> Result<Option<MaybeLocalDateTime>, Error> {
        Ok(if let Some(start) = self.start {
            Some(start.to_maybe_local(self.timezone(db_pool).await?)?)
        } else {
            None
        })
    }

    pub async fn end(&self, db_pool: impl PgExecutor<'_>) -> Result<Option<MaybeLocalDateTime>, Error> {
        Ok(if let Some(end) = self.end {
            Some(end.to_maybe_local(self.timezone(db_pool).await?)?)
        } else {
            None
        })
    }

    pub fn to_html(&self, id: &str) -> RawHtml<String> {
        html! {
            a(href = format!("/event/{id}")) : self.name.as_deref().unwrap_or(id);
        }
    }
}

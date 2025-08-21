use {
    std::{
        borrow::Cow,
        collections::{
            HashMap,
            HashSet,
        },
        ops::Range,
    },
    chrono::prelude::*,
    chrono_tz::Tz,
    rocket::response::content::RawHtml,
    rocket_util::html,
    serde::Deserialize,
    serde_with::{
        DisplayFromStr,
        PickFirst,
        serde_as,
    },
    serenity::model::prelude::*,
    sqlx::{
        PgExecutor,
        Postgres,
        Transaction,
        types::Json,
    },
    crate::{
        money::Euro,
        time::{
            MaybeAwareDateTime,
            MaybeLocalDateTime,
        },
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

#[derive(Debug, Clone, Deserialize)]
pub struct Event {
    anzahlung: Option<Euro>,
    end: Option<MaybeAwareDateTime>,
    location: Option<String>,
    #[serde(default)]
    menschen: Vec<Attendee>,
    name: Option<String>,
    start: Option<MaybeAwareDateTime>,
    timezone: Option<Tz>,
}

impl Event {
    pub async fn load(db_pool: impl PgExecutor<'_>, event_id: &str) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query_scalar(r#"SELECT value AS "value: Json<Self>" FROM json_events WHERE id = $1"#).bind(event_id).fetch_optional(db_pool).await?.map(|Json(value)| value))
    }

    pub fn anzahlung(&self) -> Option<Euro> { self.anzahlung }

    /// Returns the list of attendees for this event, including ones with unconfirmed signups.
    pub fn attendees(&self) -> &[Attendee] { &self.menschen }

    /// Shorthand to get the attendee with the given ID, if any.
    pub fn attendee(&self, id: AttendeeId) -> Option<&Attendee> {
        self.menschen.iter().find(|attendee| attendee.id == id)
    }

    pub async fn attendee_nights<'a>(&self, transaction: &mut Transaction<'_, Postgres>, attendee: &'a Attendee) -> Result<Option<impl Iterator<Item = (NaiveDate, Cow<'a, Night>)>>, Error> {
        let Some(nights) = self.nights(transaction).await? else { return Ok(None) };
        Ok(Some(nights.start.iter_days().take_while(move |d| *d < nights.end).map(|night| (night, attendee.nights.get(&night).map(Cow::Borrowed).unwrap_or_else(|| Cow::Owned(Night::default()))))))
    }

    async fn location_info(&self, db_pool: impl PgExecutor<'_>) -> Result<LocationInfo, Error> {
        Ok(match self.location.as_deref() {
            Some("online") => LocationInfo::Online,
            Some(name) => LocationInfo::Known(Location::load(db_pool, name).await?.ok_or(Error::UnknownLocation)?),
            None => LocationInfo::Unknown,
        })
    }

    async fn nights(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<Option<Range<NaiveDate>>, Error> {
        let Some(start) = self.start(&mut **transaction).await? else { return Ok(None) };
        let Some(end) = self.end(&mut **transaction).await? else { return Ok(None) };
        let Some(tz) = self.timezone(&mut **transaction).await? else { return Ok(None) };
        Ok(Some(start.with_timezone(&tz).date_naive()..end.with_timezone(&tz).date_naive()))
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

fn make_true() -> bool { true }

#[derive(Debug, Clone, Deserialize)]
pub struct Attendee {
    pub id: AttendeeId,
    #[serde(rename = "alkohol", default = "make_true")]
    pub alcohol: bool,
    #[serde(default)]
    pub food: FoodPreferences,
    #[serde(default)]
    nights: HashMap<NaiveDate, Night>,
    #[serde(default)]
    pub orga: HashSet<OrgaRole>,
}

#[serde_as]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(untagged)]
pub enum AttendeeId {
    EventGuest(#[serde_as(as = "PickFirst<(_, DisplayFromStr)>")] u8),
    Discord(UserId),
}

#[derive(Debug, Default, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FoodPreferences {
    #[serde(default)]
    pub animal_products: AnimalProducts,
    #[serde(default)]
    pub allergies: String,
}

#[derive(Debug, Default, Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AnimalProducts {
    #[default]
    Yes,
    Vegetarian,
    Vegan,
}

#[derive(Debug, Default, Clone, Copy, Deserialize)]
pub struct Night {
    #[serde(default)]
    pub going: Going,
}

#[derive(Debug, Default, Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Going {
    Yes,
    #[default]
    Maybe,
    No,
}

#[derive(Deserialize)]
struct Location {
    timezone: Tz,
}

impl Location {
    async fn load(db_pool: impl PgExecutor<'_>, loc_id: &str) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query_scalar(r#"SELECT value AS "value: Json<Self>" FROM json_locations WHERE id = $1"#).bind(loc_id).fetch_optional(db_pool).await?.map(|Json(value)| value))
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Deserialize)]
pub enum OrgaRole {
    Abrechnung,
    Buchung,
    Essen,
    Programm,
    #[serde(rename = "Schlüssel")]
    Schluessel,
}

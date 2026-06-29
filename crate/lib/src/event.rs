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
    rocket_util::{
        ToHtml,
        html,
    },
    serde::{
        Deserialize,
        Serialize,
    },
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
        prelude::*,
        types::Json,
    },
    url::Url,
    crate::{
        money::Euro,
        time::{
            MaybeAwareDateTime,
            MaybeLocalDateTime,
        },
        user::User,
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
    pub async fn all(db_pool: impl PgExecutor<'_>) -> sqlx::Result<Vec<(String, Self)>> { //TODO return stream
        Ok(sqlx::query(r#"SELECT id, value FROM json_events ORDER BY value -> 'start' ASC NULLS LAST"#).fetch_all(db_pool).await?.into_iter().map(|row| (row.get("id"), row.get::<Json<_>, _>("value").0)).collect())
    }

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

    pub fn location_id(&self) -> LocationId<'_> {
        match self.location.as_deref() {
            Some("online") => LocationId::Online,
            Some(name) => LocationId::Known(name),
            None => LocationId::Unknown,
        }
    }

    pub async fn location_info(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<LocationInfo, Error> {
        Ok(match self.location.as_deref() {
            Some("online") => LocationInfo::Online,
            Some(name) => LocationInfo::Known(Location::load(transaction, name).await?.ok_or(Error::UnknownLocation)?),
            None => LocationInfo::Unknown,
        })
    }

    async fn nights(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<Option<Range<NaiveDate>>, Error> {
        let Some(start) = self.start(&mut *transaction).await? else { return Ok(None) };
        let Some(end) = self.end(&mut *transaction).await? else { return Ok(None) };
        let Some(tz) = self.timezone(transaction).await? else { return Ok(None) };
        Ok(Some(start.with_timezone(&tz).date_naive()..end.with_timezone(&tz).date_naive()))
    }

    pub async fn timezone(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<Option<Tz>, Error> {
        Ok(if let Some(timezone) = self.timezone {
            Some(timezone)
        } else {
            self.location_info(transaction).await?.timezone()
        })
    }

    pub async fn start(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<Option<MaybeLocalDateTime>, Error> {
        Ok(if let Some(start) = self.start {
            Some(start.to_maybe_local(self.timezone(transaction).await?)?)
        } else {
            None
        })
    }

    pub async fn end(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<Option<MaybeLocalDateTime>, Error> {
        Ok(if let Some(end) = self.end {
            Some(end.to_maybe_local(self.timezone(transaction).await?)?)
        } else {
            None
        })
    }

    pub fn name(&self) -> Option<&str> {
        self.name.as_deref()
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

#[derive(Deserialize)]
#[serde(untagged)]
enum JsonNight {
    Old(Going),
    New {
        going: Going,
    },
}

impl From<JsonNight> for Night {
    fn from(value: JsonNight) -> Self {
        match value {
            JsonNight::Old(going) => Self { going },
            JsonNight::New { going } => Self { going },
        }
    }
}

#[derive(Debug, Default, Clone, Copy, Deserialize)]
#[serde(from = "JsonNight")]
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
struct JsonLocation {
    host: Option<UserId>,
    name: Option<String>,
    prefix: Option<String>,
    #[serde(default)]
    rooms: HashMap<String, HashMap<String, Room>>,
    timezone: Tz,
    website: Option<Url>,
}

pub struct Location {
    host: Option<User>,
    name: String,
    prefix: Cow<'static, str>,
    pub rooms: HashMap<String, HashMap<String, Room>>,
    timezone: Tz,
    website: Option<Url>,
}

impl Location {
    async fn load(transaction: &mut Transaction<'_, Postgres>, loc_id: &str) -> sqlx::Result<Option<Self>> {
        let Some(Json(JsonLocation { host, name, prefix, rooms, timezone, website })) = sqlx::query_scalar(r#"SELECT value AS "value: _" FROM json_locations WHERE id = $1"#).bind(loc_id).fetch_optional(&mut **transaction).await? else { return Ok(None) };
        Ok(Some(Self {
            host: if let Some(host) = host { User::from_id(transaction, host).await? } else { None }, //TODO error on nonexistent user instead of setting host to None?
            name: name.unwrap_or_else(|| loc_id.to_owned()),
            prefix: prefix.map(Cow::Owned).unwrap_or_else(|| Cow::Borrowed("in ")),
            timezone, rooms, website,
        }))
    }
}

impl ToHtml for Location {
    fn to_html(&self) -> RawHtml<String> {
        let mut buf = RawHtml(String::default());
        self.push_html(&mut buf);
        buf
    }

    fn push_html(&self, buf: &mut RawHtml<String>) {
        if let Some(host) = &self.host {
            buf.0.push_str("bei ");
            host.push_html(buf);
            buf.0.push(' ');
        }
        self.prefix.push_html(buf);
        if let Some(website) = &self.website {
            html! {
                a(href = website) : self.name;
            }.push_html(buf);
        } else {
            self.name.push_html(buf);
        }
    }
}

#[derive(Deserialize)]
pub struct Room {
    pub beds: u8,
}

pub enum LocationId<'a> {
    Unknown,
    Online,
    Known(&'a str),
}

pub enum LocationInfo {
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Deserialize, Serialize)]
pub enum OrgaRole {
    Abrechnung,
    Buchung,
    Essen,
    Programm,
    #[serde(rename = "Schlüssel")]
    Schluessel,
}

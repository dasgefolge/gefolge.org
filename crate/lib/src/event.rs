use {
    std::{
        borrow::Cow,
        collections::HashMap,
        fmt::{
            self,
            Write as _,
        },
        ops::Range,
        str::FromStr,
    },
    chrono::prelude::*,
    chrono_tz::Tz,
    enum_iterator::Sequence,
    enumset::{
        EnumSet,
        EnumSetType,
    },
    lazy_regex::regex_captures,
    rocket::{
        FromFormField,
        http::uri::{
            self,
            fmt::{
                Path,
                UriDisplay,
            },
        },
        response::content::RawHtml,
    },
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
        Database,
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
            iter_date_range,
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Deserialize, Serialize, Sequence)]
pub enum Season {
    Oster,
    Sommer,
    Winter,
}

impl FromStr for Season {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "osil" => Ok(Self::Oster),
            "sosil" => Ok(Self::Sommer),
            "sil" => Ok(Self::Winter),
            _ => Err(()),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Deserialize, Serialize)]
pub struct Id {
    pub year: i32,
    pub season: Season,
}

#[derive(Debug, thiserror::Error)]
pub enum IdParseError {
    #[error(transparent)] ParseInt(#[from] std::num::ParseIntError),
    #[error("event ID does not match expected pattern")]
    Pattern,
    #[error("unexpected event season")]
    Season,
}

impl FromStr for Id {
    type Err = IdParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let (_, season, year) = regex_captures!("^(.+?)([0-9]+)$", s).ok_or(IdParseError::Pattern)?;
        Ok(Self {
            year: year.parse()?,
            season: season.parse().map_err(|()| IdParseError::Season)?,
        })
    }
}

impl fmt::Display for Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.season {
            Season::Oster => write!(f, "osil")?,
            Season::Sommer => write!(f, "sosil")?,
            Season::Winter => write!(f, "sil")?,
        }
        write!(f, "{}", self.year)
    }
}

impl UriDisplay<Path> for Id {
    fn fmt(&self, f: &mut uri::fmt::Formatter<'_, Path>) -> fmt::Result {
        write!(f, "{self}")
    }
}

impl<'q, DB: Database> Encode<'q, DB> for Id
where String: Encode<'q, DB> {
    fn encode_by_ref(&self, buf: &mut <DB as Database>::ArgumentBuffer<'q>) -> Result<sqlx::encode::IsNull, Box<dyn std::error::Error + Send + Sync>> {
        self.to_string().encode(buf)
    }

    fn encode(self, buf: &mut <DB as Database>::ArgumentBuffer<'q>) -> Result<sqlx::encode::IsNull, Box<dyn std::error::Error + Send + Sync>> {
        self.to_string().encode(buf)
    }

    fn produces(&self) -> Option<<DB as Database>::TypeInfo> {
        self.to_string().produces()
    }

    fn size_hint(&self) -> usize {
        Encode::size_hint(&self.to_string())
    }
}

impl<DB: Database> Type<DB> for Id
where String: Type<DB> {
    fn type_info() -> <DB as Database>::TypeInfo {
        String::type_info()
    }

    fn compatible(ty: &<DB as Database>::TypeInfo) -> bool {
        String::compatible(ty)
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Event {
    anzahlung: Option<Euro>,
    channel: Option<ChannelId>,
    end: Option<MaybeAwareDateTime>,
    location: Option<String>,
    #[serde(default)]
    menschen: Vec<Attendee>,
    name: Option<String>,
    role: Option<RoleId>,
    start: Option<MaybeAwareDateTime>,
    timezone: Option<Tz>,
}

impl Event {
    pub async fn all(db_pool: impl PgExecutor<'_>) -> sqlx::Result<Vec<(String, Self)>> { //TODO return stream
        Ok(sqlx::query("SELECT id, value FROM json_events ORDER BY value -> 'start' ASC NULLS LAST").fetch_all(db_pool).await?.into_iter().map(|row| (row.get("id"), row.get::<Json<_>, _>("value").0)).collect())
    }

    pub async fn load(db_pool: impl PgExecutor<'_>, event_id: Id) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query_scalar("SELECT value FROM json_events WHERE id = $1").bind(event_id).fetch_optional(db_pool).await?.map(|Json(value)| value))
    }

    pub fn anzahlung(&self) -> Option<Euro> { self.anzahlung }
    pub fn discord_role(&self) -> Option<RoleId> { self.role }

    pub fn discord_channel(&self) -> ChannelId {
        self.channel.unwrap_or_else(|| ChannelId::new(387264349678338049))
    }

    /// Returns the list of attendees for this event, including ones with unconfirmed signups.
    pub fn attendees(&self) -> &[Attendee] { &self.menschen }

    /// Shorthand to get the attendee with the given ID, if any.
    pub fn attendee(&self, id: AttendeeId) -> Option<&Attendee> {
        self.menschen.iter().find(|attendee| attendee.id == id)
    }

    pub async fn attendee_nights<'a>(&self, transaction: &mut Transaction<'_, Postgres>, attendee: &'a Attendee) -> Result<Option<impl Iterator<Item = (NaiveDate, Cow<'a, Night>)>>, Error> {
        let Some(nights) = self.nights(transaction).await? else { return Ok(None) };
        Ok(Some(iter_date_range(nights).map(|night| (night, attendee.nights.get(&night).map(Cow::Borrowed).unwrap_or_else(|| Cow::Owned(Night::default()))))))
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

    pub async fn nights(&self, transaction: &mut Transaction<'_, Postgres>) -> Result<Option<Range<NaiveDate>>, Error> {
        let Some(start) = self.start(&mut *transaction).await? else { return Ok(None) };
        let Some(end) = self.end(&mut *transaction).await? else { return Ok(None) };
        let Some(tz) = self.timezone(transaction).await? else { return Ok(None) };
        Ok(Some(start.with_timezone(&tz).date_naive()..end.with_timezone(&tz).date_naive()))
    }

    pub fn orga_unassigned(&self, id: Id) -> EnumSet<OrgaRole> {
        let mut unassigned = EnumSet::all();
        if id.year >= 2026 {
            // ab 2026 werden events über den Verein abgerechnet
            unassigned.remove(OrgaRole::Abrechnung);
        }
        for attendee in self.attendees() {
            unassigned.remove_all(attendee.orga);
        }
        unassigned
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

    pub fn name(&self, id: Id) -> Cow<'_, str> {
        self.name.as_deref().map(Cow::Borrowed).unwrap_or_else(|| Cow::Owned(id.to_string()))
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
    pub orga: EnumSet<OrgaRole>,
    pub signup: MaybeAwareDateTime,
    via: Option<UserId>,
}

impl Attendee {
    pub async fn via(&self, transaction: &mut Transaction<'_, Postgres>) -> sqlx::Result<Option<User>> {
        Ok(if let Some(via) = self.via {
            Some(User::from_id(transaction, via).await?.expect("guest proxy user does not exist"))
        } else {
            None
        })
    }
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

#[derive(Debug, Default, Clone, Copy, Deserialize, Serialize, FromFormField)]
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

#[derive(Debug, Default, Clone, Copy, Deserialize, Serialize, FromFormField)]
#[serde(rename_all = "lowercase")]
pub enum Going {
    Yes,
    #[default]
    Maybe,
    No,
}

#[derive(Deserialize)]
struct JsonLocation {
    hausordnung: Option<Url>,
    host: Option<UserId>,
    name: Option<String>,
    prefix: Option<String>,
    #[serde(default)]
    rooms: HashMap<String, HashMap<String, Room>>,
    timezone: Tz,
    website: Option<Url>,
}

pub struct Location {
    pub hausordnung: Option<Url>,
    host: Option<User>,
    name: String,
    prefix: Cow<'static, str>,
    pub rooms: HashMap<String, HashMap<String, Room>>,
    timezone: Tz,
    website: Option<Url>,
}

impl Location {
    async fn load(transaction: &mut Transaction<'_, Postgres>, loc_id: &str) -> sqlx::Result<Option<Self>> {
        let Some(Json(JsonLocation { hausordnung, host, name, prefix, rooms, timezone, website })) = sqlx::query_scalar("SELECT value FROM json_locations WHERE id = $1").bind(loc_id).fetch_optional(&mut **transaction).await? else { return Ok(None) };
        Ok(Some(Self {
            host: if let Some(host) = host { User::from_id(transaction, host).await? } else { None }, //TODO error on nonexistent user instead of setting host to None?
            name: name.unwrap_or_else(|| loc_id.to_owned()),
            prefix: prefix.map(Cow::Owned).unwrap_or_else(|| Cow::Borrowed("in ")),
            hausordnung, timezone, rooms, website,
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

#[derive(Debug, Hash, Deserialize, Serialize, EnumSetType, Sequence)]
#[enumset(serialize_repr = "list")]
pub enum OrgaRole {
    Abrechnung,
    Buchung,
    Essen,
    Programm,
    #[serde(rename = "Schlüssel")]
    Schluessel,
}

impl fmt::Display for OrgaRole {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Abrechnung => write!(f, "Abrechnung"),
            Self::Buchung => write!(f, "Buchung"),
            Self::Essen => write!(f, "Essen"),
            Self::Programm => write!(f, "Programm"),
            Self::Schluessel => write!(f, "Schlüssel"),
        }
    }
}

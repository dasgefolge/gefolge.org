use {
    std::{
        collections::BTreeSet,
        fmt,
        time::Duration,
    },
    chrono_tz::Tz,
    derive_more::*,
    rocket::{
        State,
        http::Status,
        outcome::Outcome,
        request::{
            self,
            FromRequest,
            Request,
        },
        response::content::RawHtml,
    },
    rocket_util::{
        ToHtml,
        html,
    },
    serde::Deserialize,
    serenity::model::prelude::*,
    sqlx::{
        PgPool,
        postgres::Postgres,
        Transaction,
        types::Json,
    },
    tokio::time::{
        Instant,
        sleep_until,
    },
    crate::{
        auth::{
            DiscordUser,
            UserFromRequestError,
        },
        guard_try,
    },
};

const MENSCH: RoleId = RoleId::new(386753710434287626);
const GUEST: RoleId = RoleId::new(784929665478557737);

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) struct Discriminator(pub(crate) i16);

impl fmt::Display for Discriminator {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}", self.0)
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
pub(crate) struct User {
    pub(crate) id: UserId,
    pub(crate) discriminator: Option<Discriminator>,
    pub(crate) nick: Option<String>,
    roles: BTreeSet<RoleId>,
    pub(crate) username: String,
}

impl User {
    pub(crate) async fn from_id(transaction: &mut Transaction<'_, Postgres>, id: UserId) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query!(r#"SELECT discriminator, nick, roles AS "roles: sqlx::types::Json<BTreeSet<RoleId>>", username FROM users WHERE snowflake = $1"#, i64::from(id)).fetch_optional(&mut **transaction).await?.map(|row| User {
            discriminator: row.discriminator.map(Discriminator),
            nick: row.nick,
            roles: row.roles.0,
            username: row.username,
            id,
        }))
    }

    pub(crate) async fn from_api_key(transaction: &mut Transaction<'_, Postgres>, api_key: &str) -> sqlx::Result<Option<Self>> {
        let before_query = Instant::now();
        let ret = sqlx::query!(r#"SELECT snowflake, discriminator, nick, roles AS "roles: sqlx::types::Json<BTreeSet<RoleId>>", username FROM users, json_user_data WHERE id = snowflake AND value -> 'apiKey' = $1"#, Json(api_key) as _).fetch_optional(&mut **transaction).await?.map(|row| User {
            id: UserId::from(row.snowflake as u64),
            discriminator: row.discriminator.map(Discriminator),
            nick: row.nick,
            roles: row.roles.0,
            username: row.username,
        });
        sleep_until(before_query + Duration::from_millis(100)).await; // timing attack protection
        Ok(ret)
    }

    pub(crate) fn is_mensch(&self) -> bool {
        self.roles.contains(&MENSCH)
    }

    pub(crate) fn is_mensch_or_guest(&self) -> bool {
        self.roles.contains(&MENSCH) || self.roles.contains(&GUEST)
    }

    pub(crate) async fn data(&self, transaction: &mut Transaction<'_, Postgres>) -> sqlx::Result<Data> {
        Ok(sqlx::query_scalar!(r#"SELECT value AS "value: Json<Data>" FROM json_user_data WHERE id = $1"#, i64::from(self.id)).fetch_optional(&mut **transaction).await?.map(|Json(data)| data).unwrap_or_default())
    }
}

#[rocket::async_trait]
impl<'r> FromRequest<'r> for User {
    type Error = UserFromRequestError;

    async fn from_request(req: &'r Request<'_>) -> request::Outcome<Self, Self::Error> {
        match req.guard().await {
            Outcome::Success(DiscordUser { id }) => match req.guard::<&State<PgPool>>().await {
                Outcome::Success(pool) => {
                    let mut transaction = guard_try!(pool.begin().await);
                    if let Some(user) = guard_try!(Self::from_id(&mut transaction, id).await) {
                        Outcome::Success(user)
                    } else {
                        Outcome::Error((Status::Unauthorized, UserFromRequestError::NotInDiscordGuild))
                    }
                }
                Outcome::Error((status, ())) => Outcome::Error((status, UserFromRequestError::Database)),
                Outcome::Forward(status) => Outcome::Forward(status),
            },
            Outcome::Error((status, e)) => Outcome::Error((status, e)),
            Outcome::Forward(status) => Outcome::Forward(status),
        }
    }
}

impl ToHtml for User {
    fn to_html(&self) -> RawHtml<String> {
        let username = if let Some(discriminator) = self.discriminator {
            format!("{}#{discriminator}", self.username)
        } else {
            format!("@{}", self.username)
        };
        html! {
            a(title = username, href = format!("/mensch/{}", self.id)) {
                : self.nick.as_ref().unwrap_or(&self.username);
            }
        }
    }
}

#[derive(Deref, Into)]
pub(crate) struct Mensch(User);

#[rocket::async_trait]
impl<'r> FromRequest<'r> for Mensch {
    type Error = UserFromRequestError;

    async fn from_request(req: &'r Request<'_>) -> request::Outcome<Self, UserFromRequestError> {
        req.guard::<User>().await.and_then(|user| if user.is_mensch() {
            Outcome::Success(Self(user))
        } else {
            Outcome::Error((Status::Unauthorized, UserFromRequestError::MenschRequired))
        })
    }
}

fn make_true() -> bool { true }

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Data {
    pub(crate) timezone: Option<Tz>,
    #[serde(default = "make_true")]
    pub(crate) event_timezone_override: bool,
}

impl Default for Data {
    fn default() -> Self {
        Self {
            timezone: None,
            event_timezone_override: true,
        }
    }
}

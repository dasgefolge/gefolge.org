use {
    std::{
        collections::BTreeSet,
        fmt,
    },
    chrono_tz::Tz,
    rocket::response::content::RawHtml,
    rocket_util::html,
    serde::Deserialize,
    serenity::model::prelude::*,
    sqlx::{
        postgres::Postgres,
        Transaction,
        types::Json,
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
    pub(crate) async fn from_id(db: &mut Transaction<'_, Postgres>, id: UserId) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query!(r#"SELECT discriminator, nick, roles AS "roles: sqlx::types::Json<BTreeSet<RoleId>>", username FROM users WHERE snowflake = $1"#, i64::from(id)).fetch_optional(&mut **db).await?.map(|row| User {
            discriminator: row.discriminator.map(Discriminator),
            nick: row.nick,
            roles: row.roles.0,
            username: row.username,
            id,
        }))
    }

    pub(crate) async fn from_api_key(db: &mut Transaction<'_, Postgres>, api_key: &str) -> sqlx::Result<Option<Self>> {
        Ok(sqlx::query!(r#"SELECT snowflake, discriminator, nick, roles AS "roles: sqlx::types::Json<BTreeSet<RoleId>>", username FROM users, json_user_data WHERE id = snowflake AND value -> 'apiKey' = $1"#, Json(api_key) as _).fetch_optional(&mut **db).await?.map(|row| User {
            id: UserId::from(row.snowflake as u64),
            discriminator: row.discriminator.map(Discriminator),
            nick: row.nick,
            roles: row.roles.0,
            username: row.username,
        }))
    }

    pub(crate) fn is_mensch(&self) -> bool {
        self.roles.contains(&MENSCH)
    }

    pub(crate) fn is_mensch_or_guest(&self) -> bool {
        self.roles.contains(&MENSCH) || self.roles.contains(&GUEST)
    }

    pub(crate) async fn data(&self, db: &mut Transaction<'_, Postgres>) -> sqlx::Result<Data> {
        Ok(sqlx::query_scalar!(r#"SELECT value AS "value: Json<Data>" FROM json_user_data WHERE id = $1"#, i64::from(self.id)).fetch_optional(&mut **db).await?.map(|Json(data)| data).unwrap_or_default())
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

pub(crate) async fn html_mention(db: &mut Transaction<'_, Postgres>, user_id: UserId) -> sqlx::Result<RawHtml<String>> {
    Ok(if let Some(user) = User::from_id(db, user_id).await? {
        let username = if let Some(discriminator) = user.discriminator {
            format!("{}#{discriminator}", user.username)
        } else {
            format!("@{}", user.username)
        };
        html! {
            a(title = username, href = format!("/mensch/{user_id}")) {
                : user.nick.unwrap_or(user.username);
            }
        }
    } else {
        //TODO use data from Discord API directly or fetch global Discord username & discrim using serenity
        html! {
            : "<@";
            : user_id.to_string();
            : ">";
        }
    })
}

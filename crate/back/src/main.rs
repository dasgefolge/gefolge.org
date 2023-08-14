#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    std::{
        collections::BTreeSet,
        fmt,
        io::stdout,
        str::FromStr as _,
    },
    chrono::prelude::*,
    futures::stream::TryStreamExt as _,
    serde::Serialize,
    serde_json::Value as Json,
    serde_plain::derive_serialize_from_display,
    serenity::model::prelude::*,
    sqlx::{
        PgPool,
        postgres::PgConnectOptions,
    },
};

#[derive(clap::Subcommand)]
enum StringDbSubcommand {
    List,
    Get {
        id: String,
    },
    Set {
        id: String,
        #[clap(value_parser = Json::from_str)]
        value: Json,
    },
    SetIfNotExists {
        id: String,
        #[clap(value_parser = Json::from_str)]
        value: Json,
    },
}

#[derive(clap::Subcommand)]
enum UserIdDbSubcommand {
    List,
    Get {
        id: UserId,
    },
    Set {
        id: UserId,
        #[clap(value_parser = Json::from_str)]
        value: Json,
    },
    SetIfNotExists {
        id: UserId,
        #[clap(value_parser = Json::from_str)]
        value: Json,
    },
}

struct Discriminator(i16);

impl fmt::Display for Discriminator {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}", self.0)
    }
}

derive_serialize_from_display!(Discriminator);

#[derive(Serialize)]
struct Profile {
    discriminator: Option<Discriminator>,
    joined: Option<DateTime<Utc>>,
    nick: Option<String>,
    roles: BTreeSet<RoleId>,
    snowflake: UserId,
    username: String,
}

#[derive(clap::Parser)]
#[clap(version)]
enum Args {
    #[clap(subcommand)]
    Events(StringDbSubcommand),
    #[clap(subcommand)]
    Locations(StringDbSubcommand),
    #[clap(subcommand)]
    Profiles(UserIdDbSubcommand),
    #[clap(subcommand)]
    UserData(UserIdDbSubcommand),
}

#[derive(Debug, thiserror::Error)]
enum Error {
    #[error(transparent)] Json(#[from] serde_json::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error("a JSON argument did not match the expected format")]
    JsonFormat,
}

#[wheel::main(debug)]
async fn main(args: Args) -> Result<i32, Error> {
    let db_pool = PgPool::connect_with(PgConnectOptions::default().username("fenhl").database("gefolge").application_name("gefolge-web-back")).await?;
    match args {
        Args::Events(StringDbSubcommand::List) => {
            let mut events = sqlx::query_scalar!("SELECT id FROM json_events").fetch(&db_pool);
            while let Some(id) = events.try_next().await? {
                println!("{id}");
            }
        }
        Args::Events(StringDbSubcommand::Get { id }) => if let Some(value) = sqlx::query_scalar!("SELECT value FROM json_events WHERE id = $1", id).fetch_optional(&db_pool).await? {
            serde_json::to_writer(stdout(), &value)?;
        } else {
            return Ok(2)
        },
        Args::Events(StringDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_events (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id, value).execute(&db_pool).await?; }
        Args::Events(StringDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_events (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id, value).execute(&db_pool).await?; }
        Args::Locations(StringDbSubcommand::List) => {
            let mut locations = sqlx::query_scalar!("SELECT id FROM json_locations").fetch(&db_pool);
            while let Some(id) = locations.try_next().await? {
                println!("{id}");
            }
        }
        Args::Locations(StringDbSubcommand::Get { id }) => if let Some(value) = sqlx::query_scalar!("SELECT value FROM json_locations WHERE id = $1", id).fetch_optional(&db_pool).await? {
            serde_json::to_writer(stdout(), &value)?;
        } else {
            return Ok(2)
        },
        Args::Locations(StringDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_locations (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id, value).execute(&db_pool).await?; }
        Args::Locations(StringDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_locations (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id, value).execute(&db_pool).await?; }
        Args::Profiles(UserIdDbSubcommand::List) => {
            let mut profiles = sqlx::query_scalar!("SELECT snowflake FROM users").fetch(&db_pool);
            while let Some(id) = profiles.try_next().await? {
                println!("{}", id as u64);
            }
        }
        Args::Profiles(UserIdDbSubcommand::Get { id }) => if let Some(row) = sqlx::query!(r#"SELECT discriminator, joined, nick, roles AS "roles: sqlx::types::Json<BTreeSet<RoleId>>", username FROM users WHERE snowflake = $1"#, id.0 as i64).fetch_optional(&db_pool).await? {
            serde_json::to_writer(stdout(), &Profile {
                discriminator: row.discriminator.map(Discriminator),
                joined: row.joined,
                nick: row.nick,
                roles: row.roles.0,
                snowflake: id,
                username: row.username,
            })?;
        } else {
            return Ok(2)
        },
        Args::Profiles(UserIdDbSubcommand::Set { id, value }) => {
            let Json::Object(mut value) = value else { return Err(Error::JsonFormat) };
            sqlx::query!("
                INSERT INTO users
                (snowflake, discriminator, joined, nick, roles, username)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (snowflake) DO UPDATE SET
                discriminator = EXCLUDED.discriminator,
                joined = EXCLUDED.joined,
                nick = EXCLUDED.nick,
                roles = EXCLUDED.roles,
                username = EXCLUDED.username
            ",
                id.0 as i64,
                value.remove("discriminator").and_then(|discrim| serde_json::from_value::<Option<i16>>(discrim).transpose()).transpose()?,
                value.remove("joined").and_then(|joined| serde_json::from_value::<Option<DateTime<Utc>>>(joined).transpose()).transpose()?,
                value.remove("nick").and_then(|nick| serde_json::from_value::<Option<String>>(nick).transpose()).transpose()?,
                value.remove("roles").unwrap_or_default(),
                serde_json::from_value::<String>(value.remove("username").ok_or(Error::JsonFormat)?)?,
            ).execute(&db_pool).await?;
        }
        Args::Profiles(UserIdDbSubcommand::SetIfNotExists { id, value }) => {
            let Json::Object(mut value) = value else { return Err(Error::JsonFormat) };
            sqlx::query!("
                INSERT INTO users
                (snowflake, discriminator, joined, nick, roles, username)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (snowflake) DO NOTHING
            ",
                id.0 as i64,
                value.remove("discriminator").and_then(|discrim| serde_json::from_value::<Option<i16>>(discrim).transpose()).transpose()?,
                value.remove("joined").and_then(|joined| serde_json::from_value::<Option<DateTime<Utc>>>(joined).transpose()).transpose()?,
                value.remove("nick").and_then(|nick| serde_json::from_value::<Option<String>>(nick).transpose()).transpose()?,
                value.remove("roles").unwrap_or_default(),
                serde_json::from_value::<String>(value.remove("username").ok_or(Error::JsonFormat)?)?,
            ).execute(&db_pool).await?;
        }
        Args::UserData(UserIdDbSubcommand::List) => {
            let mut user_data = sqlx::query_scalar!("SELECT id FROM json_user_data").fetch(&db_pool);
            while let Some(id) = user_data.try_next().await? {
                println!("{}", id as u64);
            }
        }
        Args::UserData(UserIdDbSubcommand::Get { id }) => if let Some(value) = sqlx::query_scalar!("SELECT value FROM json_user_data WHERE id = $1", id.0 as i64).fetch_optional(&db_pool).await? {
            serde_json::to_writer(stdout(), &value)?;
        } else {
            return Ok(2)
        },
        Args::UserData(UserIdDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_user_data (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id.0 as i64, value).execute(&db_pool).await?; }
        Args::UserData(UserIdDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_user_data (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.0 as i64, value).execute(&db_pool).await?; }
    }
    Ok(0)
}

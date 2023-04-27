#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    std::{
        io::stdout,
        str::FromStr as _,
    },
    futures::stream::TryStreamExt as _,
    serde_json::Value as Json,
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
}

#[wheel::main]
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
            let mut profiles = sqlx::query_scalar!("SELECT id FROM json_profiles").fetch(&db_pool);
            while let Some(id) = profiles.try_next().await? {
                println!("{}", id as u64);
            }
        }
        Args::Profiles(UserIdDbSubcommand::Get { id }) => if let Some(value) = sqlx::query_scalar!("SELECT value FROM json_profiles WHERE id = $1", id.0 as i64).fetch_optional(&db_pool).await? {
            serde_json::to_writer(stdout(), &value)?;
        } else {
            return Ok(2)
        },
        Args::Profiles(UserIdDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_profiles (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id.0 as i64, value).execute(&db_pool).await?; }
        Args::Profiles(UserIdDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_profiles (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.0 as i64, value).execute(&db_pool).await?; }
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

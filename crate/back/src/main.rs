#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    std::{
        io::stdout,
        str::FromStr as _,
    },
    serde_json::Value as Json,
    serenity::model::prelude::*,
    sqlx::{
        PgPool,
        postgres::PgConnectOptions,
    },
};

#[derive(clap::Subcommand)]
enum StringDbSubcommand {
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
async fn main(args: Args) -> Result<(), Error> {
    let db_pool = PgPool::connect_with(PgConnectOptions::default().username("fenhl").database("gefolge").application_name("gefolge-web-back")).await?;
    match args {
        Args::Events(StringDbSubcommand::Get { id }) => serde_json::to_writer(stdout(), &sqlx::query_scalar!("SELECT value FROM json_events WHERE id = $1", id).fetch_one(&db_pool).await?)?,
        Args::Events(StringDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_events (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id, value).execute(&db_pool).await?; }
        Args::Events(StringDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_events (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id, value).execute(&db_pool).await?; }
        Args::Locations(StringDbSubcommand::Get { id }) => serde_json::to_writer(stdout(), &sqlx::query_scalar!("SELECT value FROM json_locations WHERE id = $1", id).fetch_one(&db_pool).await?)?,
        Args::Locations(StringDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_locations (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id, value).execute(&db_pool).await?; }
        Args::Locations(StringDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_locations (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id, value).execute(&db_pool).await?; }
        Args::Profiles(UserIdDbSubcommand::Get { id }) => serde_json::to_writer(stdout(), &sqlx::query_scalar!("SELECT value FROM json_profiles WHERE id = $1", id.0 as i64).fetch_one(&db_pool).await?)?,
        Args::Profiles(UserIdDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_profiles (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id.0 as i64, value).execute(&db_pool).await?; }
        Args::Profiles(UserIdDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_profiles (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.0 as i64, value).execute(&db_pool).await?; }
        Args::UserData(UserIdDbSubcommand::Get { id }) => serde_json::to_writer(stdout(), &sqlx::query_scalar!("SELECT value FROM json_user_data WHERE id = $1", id.0 as i64).fetch_one(&db_pool).await?)?,
        Args::UserData(UserIdDbSubcommand::Set { id, value }) => { sqlx::query!("INSERT INTO json_user_data (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", id.0 as i64, value).execute(&db_pool).await?; }
        Args::UserData(UserIdDbSubcommand::SetIfNotExists { id, value }) => { sqlx::query!("INSERT INTO json_user_data (id, value) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", id.0 as i64, value).execute(&db_pool).await?; }
    }
    Ok(())
}

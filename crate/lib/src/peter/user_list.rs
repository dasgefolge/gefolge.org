//! Helper functions for maintaining the guild member list on disk, which is used by gefolge.org to verify logins.

use {
    std::{
        convert::identity,
        future::Future,
        pin::Pin,
    },
    futures::future,
    serenity::{
        model::prelude::*,
        prelude::*,
    },
    sqlx::{
        PgPool,
        types::Json,
    },
    super::{
        Database,
        GEFOLGE,
    },
};

/// Add a Discord account to the list of Gefolge guild members.
pub async fn add(pool: &PgPool, member: &Member) -> sqlx::Result<()> {
    if member.user.bot { return Ok(()) }
    let join_date = sqlx::query_scalar(r#"SELECT joined FROM users WHERE snowflake = $1"#)
        .bind(member.user.id.get() as i64)
        .fetch_optional(pool).await?
        .and_then(identity);
    sqlx::query("INSERT INTO users
        (snowflake, discriminator, joined, nick, roles, username)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (snowflake) DO UPDATE SET
        discriminator = EXCLUDED.discriminator,
        joined = EXCLUDED.joined,
        nick = EXCLUDED.nick,
        roles = EXCLUDED.roles,
        username = EXCLUDED.username
    ")
    .bind(member.user.id.get() as i64)
    .bind(member.user.discriminator.map(|discrim| discrim.get() as i16))
    .bind(member.joined_at.map(|joined_at| *joined_at).or(join_date))
    .bind(member.nick.as_ref().or(member.user.global_name.as_ref()))
    .bind(Json(&member.roles))
    .bind(&member.user.name)
    .execute(pool).await?;
    Ok(())
}

pub enum Exporter {}

impl serenity_utils::handler::user_list::ExporterMethods for Exporter {
    fn upsert<'a>(ctx: &'a Context, member: &'a Member) -> Pin<Box<dyn Future<Output = Result<(), Box<dyn std::error::Error + Send + Sync>>> + Send + 'a>> {
        Box::pin(async move {
            if member.guild_id != GEFOLGE { return Ok(()) }
            let data = ctx.data.read().await;
            let pool = data.get::<Database>().expect("missing database connection");
            add(pool, member).await?;
            Ok(())
        })
    }

    fn replace_all<'a>(ctx: &'a Context, members: Vec<&'a Member>) -> Pin<Box<dyn Future<Output = Result<(), Box<dyn std::error::Error + Send + Sync>>> + Send + 'a>> {
        Box::pin(async move {
            let data = ctx.data.read().await;
            let pool = data.get::<Database>().expect("missing database connection");
            for member in members { //TODO parallel?
                if member.guild_id == GEFOLGE {
                    add(pool, member).await?;
                }
            }
            Ok(())
        })
    }

    fn remove<'a>(_: &'a Context, _: UserId, _: GuildId) -> Pin<Box<dyn Future<Output = Result<(), Box<dyn std::error::Error + Send + Sync>>> + Send + 'a>> {
        //TODO mark as non-member, remove entirely if no user data exists
        Box::pin(future::ok(()))
    }
}

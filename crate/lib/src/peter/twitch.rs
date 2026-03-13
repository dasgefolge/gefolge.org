use {
    std::{
        collections::BTreeMap,
        convert::Infallible as Never,
        iter,
        pin::pin,
        time::Duration,
    },
    futures::prelude::*,
    itertools::Itertools as _,
    serde::Deserialize,
    serenity::{
        all::{
            CreateEmbed,
            CreateMessage,
        },
        model::prelude::*,
        prelude::*,
        utils::MessageBuilder,
    },
    serenity_utils::RwFuture,
    tokio::time::sleep,
    twitch_helix::{
        Client,
        model::Stream,
    },
    super::Error,
};

const CHANNEL: ChannelId = ChannelId::new(668518137334857728);
const ROLE: RoleId = RoleId::new(668534306515320833);

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    #[serde(rename = "clientID")]
    client_id: String,
    client_secret: String,
    users: BTreeMap<UserId, twitch_helix::model::UserId>,
}

async fn client_and_users(ctx_fut: &RwFuture<Context>) -> Result<(Client<'static>, BTreeMap<UserId, twitch_helix::model::UserId>), Error> {
    let ctx = ctx_fut.read().await;
    let ctx_data = (*ctx).data.read().await;
    let config = ctx_data.get::<crate::config::Config>().ok_or(Error::MissingConfig)?;
    Ok((Client::new(
        concat!("peter-discord/", env!("CARGO_PKG_VERSION")),
        config.twitch.client_id.clone(),
        twitch_helix::Credentials::from_client_secret(&config.twitch.client_secret, iter::empty::<String>()),
    )?, config.twitch.users.clone()))
}

async fn get_users(ctx_fut: &RwFuture<Context>) -> Result<BTreeMap<UserId, twitch_helix::model::UserId>, Error> {
    let ctx = ctx_fut.read().await;
    let ctx_data = (*ctx).data.read().await;
    let config = ctx_data.get::<crate::config::Config>().ok_or(Error::MissingConfig)?;
    Ok(config.twitch.users.clone())
}

/// Notifies #twitch when a Gefolge member starts streaming.
pub async fn alerts(ctx_fut: RwFuture<Context>) -> Result<Never, Error> {
    let (client, users) = client_and_users(&ctx_fut).await?;
    let first_status = status(&client, users).await?;
    let mut last_status = first_status.keys().cloned().collect::<Vec<_>>();
    loop {
        let users = get_users(&ctx_fut).await?;
        let new_status = status(&client, users.clone()).await?;
        for (user_id, stream) in &new_status {
            if !last_status.iter().any(|iter_uid| user_id == iter_uid) {
                let game = stream.game(&client).await?;
                let ctx = ctx_fut.read().await;
                CHANNEL.send_message(&*ctx, CreateMessage::default()
                    .content(MessageBuilder::default().mention(user_id).push(" streamt jetzt auf ").mention(&ROLE).build())
                    .add_embed(CreateEmbed::default()
                        .color((0x77, 0x2c, 0xe8))
                        .title(stream.to_string())
                        .url(stream.url())
                        .description(game.to_string())
                    )
                ).await?;
            }
        }
        last_status = new_status.keys().cloned().collect();
        sleep(Duration::from_secs(60)).await;
    }
}

/// Returns the set of Gefolge members who are currently live on Twitch.
async fn status(client: &Client<'_>, users: BTreeMap<UserId, twitch_helix::model::UserId>) -> Result<BTreeMap<UserId, Stream>, Error> {
    let mut map = BTreeMap::default();
    let mut stream_infos = pin!(Stream::list(client, None, Some(users.values().cloned().collect()), None));
    while let Some(stream_info) = stream_infos.try_next().await? {
        let discord_id = *users.iter().filter(|&(_, twitch_id)| stream_info.user_id == *twitch_id).exactly_one().map_err(|_| Error::TwitchUserLookup)?.0;
        map.insert(discord_id, stream_info);
    }
    Ok(map)
}

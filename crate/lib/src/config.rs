use {
    std::collections::BTreeSet,
    serde::Deserialize,
    serenity::model::prelude::*,
};
#[cfg(unix)] use {
    xdg::BaseDirectories,
    wheel::fs,
};
#[cfg(windows)] use {
    tokio::process::Command,
    wheel::traits::AsyncCommandOutputExt as _,
};
#[cfg(feature = "peter")] use {
    std::collections::BTreeMap,
    serenity::prelude::*,
    crate::peter::{
        twitch,
        werewolf,
    },
};

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error(transparent)] Json(#[from] serde_json::Error),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[cfg(unix)]
    #[error("missing config file")]
    Missing,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub discord: Discord,
    pub github_webhook_secret: String,
    pub secret_key: String,
    #[cfg(feature = "peter")] pub(crate) twitch: twitch::Config,
}

#[cfg(feature = "peter")]
impl TypeMapKey for Config {
    type Value = Self;
}

impl Config {
    pub async fn load() -> Result<Self, Error> {
        #[cfg(unix)] {
            if let Some(config_path) = BaseDirectories::new().find_config_file("gefolge.json") {
                let buf = fs::read(config_path).await?;
                Ok(serde_json::from_slice(&buf)?)
            } else {
                Err(Error::Missing)
            }
        }
        #[cfg(windows)] { // allow testing without having rust-analyzer slow down production
            Ok(serde_json::from_slice(&Command::new("ssh").arg("gefolge.org").arg("cat").arg("/etc/xdg/gefolge.json").check("ssh").await?.stdout)?)
        }
    }
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Discord {
    pub bot_token: String,
    #[cfg(feature = "peter")] pub(crate) channels: Channels,
    #[serde(rename = "clientID")]
    pub client_id: ApplicationId,
    pub client_secret: String,
    #[cfg(feature = "peter")] pub(crate) self_assignable_roles: BTreeSet<RoleId>,
    #[cfg(feature = "peter")] pub(crate) werewolf: BTreeMap<GuildId, werewolf::Config>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Channels {
    pub ignored: BTreeSet<ChannelId>,
    pub voice: ChannelId,
}

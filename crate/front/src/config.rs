use {
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

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error(transparent)] Json(#[from] serde_json::Error),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[cfg(unix)] #[error(transparent)] Xdg(#[from] xdg::BaseDirectoriesError),
    #[cfg(unix)]
    #[error("missing config file")]
    Missing,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Config {
    pub(crate) discord: ConfigDiscord,
    pub(crate) secret_key: String,
}

impl Config {
    pub(crate) async fn load() -> Result<Self, Error> {
        #[cfg(unix)] {
            if let Some(config_path) = BaseDirectories::new()?.find_config_file("gefolge.json") {
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
pub(crate) struct ConfigDiscord {
    #[serde(rename = "clientID")]
    pub(crate) client_id: ApplicationId,
    pub(crate) client_secret: String,
}

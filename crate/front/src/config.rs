use {
    serde::Deserialize,
    serenity::model::prelude::*,
    xdg::BaseDirectories,
    wheel::fs,
};

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error(transparent)] Json(#[from] serde_json::Error),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[error(transparent)] Xdg(#[from] xdg::BaseDirectoriesError),
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
        if let Some(config_path) = BaseDirectories::new()?.find_config_file("gefolge.json") {
            let buf = fs::read(config_path).await?;
            Ok(serde_json::from_slice(&buf)?)
        } else {
            Err(Error::Missing)
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

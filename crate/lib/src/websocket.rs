use {
    async_proto::Protocol,
    chrono_tz::Tz,
    semver::Version,
};

#[derive(Protocol)]
pub enum ServerMessageV2 {
    Ping,
    Error {
        debug: String,
        display: String,
    },
    NoEvent,
    CurrentEvent {
        id: String,
        timezone: Tz,
    },
    LatestSilVersion(Version),
}

#[derive(Protocol)]
pub enum ClientMessageV2 {
    Auth {
        api_key: String,
    },
    /// Start receiving notifications about changes to ongoing events (including an event starting or ending), as well as updates to [`sil`](https://github.com/dasgefolge/sil).
    //
    /// Requires having authenticated as a Gefolge member (`Mensch` Discord role).
    CurrentEvent,
}

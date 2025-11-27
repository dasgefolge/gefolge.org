use {
    std::{
        collections::HashMap,
        convert::Infallible as Never,
        fmt,
        sync::{
            Arc,
            LazyLock,
        },
        time::Duration,
    },
    async_proto::Protocol,
    chrono::prelude::*,
    chrono_tz::{
        Europe,
        Tz,
    },
    futures::{
        future::FutureExt as _,
        stream::{
            FuturesUnordered,
            SplitSink,
            SplitStream,
            StreamExt as _,
        },
    },
    log_lock::*,
    rocket::{
        State,
        response::Redirect,
        uri,
    },
    rocket_ws::WebSocket,
    semver::Version,
    serde::Deserialize,
    sqlx::{
        PgPool,
        types::Json,
    },
    tokio::{
        process::Command,
        select,
        sync::watch,
        time::sleep,
    },
    wheel::{
        fs,
        traits::AsyncCommandOutputExt as _,
    },
    gefolge_web_lib::{
        event::Event,
        websocket::{
            ClientMessageV2,
            ServerMessageV2,
        },
    },
    crate::user::{
        Discriminator,
        User,
    },
};

pub(crate) static SIL_VERSION: LazyLock<watch::Sender<Option<Version>>> = LazyLock::new(|| watch::Sender::default());

#[derive(Deserialize)] pub(crate) struct PackageManifest { pub package: PackageData }
#[derive(Deserialize)] pub(crate) struct PackageData { pub version: Version }

type WsStream = SplitStream<rocket_ws::stream::DuplexStream>;
pub(crate) type WsSink = Arc<Mutex<SplitSink<rocket_ws::stream::DuplexStream, rocket_ws::Message>>>;

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error(transparent)] Event(#[from] gefolge_web_lib::event::Error),
    #[error(transparent)] Read(#[from] async_proto::ReadError),
    #[error(transparent)] RicochetRobots(#[from] ricochet_robots_websocket::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Task(#[from] tokio::task::JoinError),
    #[error(transparent)] Toml(#[from] toml::de::Error),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[error(transparent)] Write(#[from] async_proto::WriteError),
    #[error("there are multiple events currently ongoing (at least {} and {})", .0[0], .0[1])]
    MultipleCurrentEvents([String; 2]),
    #[error("you do not have permission to use this WebSocket message")]
    Permissions,
    #[error("unknown API key")]
    UnknownApiKey,
}

#[derive(Protocol)]
enum ServerMessageV1 {
    Ping,
    Error {
        debug: String,
        display: String,
    },
}

impl ServerMessageV1 {
    fn from_error(e: impl fmt::Debug + fmt::Display) -> Self {
        Self::Error {
            debug: format!("{e:?}"),
            display: e.to_string(),
        }
    }
}

#[derive(Protocol)]
enum SessionPurposeV1 {
    RicochetRobots,
    CurrentEvent,
}

#[derive(Debug, thiserror::Error)]
#[error("SessionPurpose::CurrentEvent is no longer available due to changes to sil self-updater")]
struct CurrentEventV1;

async fn client_session_v1(db_pool: PgPool, rr_lobbies: Arc<RwLock<HashMap<u64, ricochet_robots_websocket::Lobby<User>>>>, mut stream: WsStream, sink: WsSink) -> Result<(), Error> {
    let api_key = String::read_ws021(&mut stream).await?;
    let mut transaction = db_pool.begin().await?;
    let user = User::from_api_key(&mut transaction, &api_key).await?.ok_or(Error::UnknownApiKey)?;
    transaction.commit().await?;
    if !user.is_mensch() { return Err(Error::Permissions) }
    let ping_sink = Arc::clone(&sink);
    tokio::spawn(async move {
        loop {
            sleep(Duration::from_secs(30)).await;
            if lock!(ping_sink = ping_sink; ServerMessageV1::Ping.write_ws021(&mut *ping_sink).await).is_err() { break } //TODO better error handling
        }
    });
    match SessionPurposeV1::read_ws021(&mut stream).await? {
        SessionPurposeV1::RicochetRobots => ricochet_robots_websocket::client_session(&rr_lobbies, user, stream, sink).await?,
        SessionPurposeV1::CurrentEvent => lock!(sink = sink; ServerMessageV1::from_error(CurrentEventV1).write_ws021(&mut *sink).await)?,
    }
    Ok(())
}

impl ricochet_robots_websocket::PlayerId for User {
    fn id(&self) -> Result<u64, ricochet_robots_websocket::Error> {
        Ok(u64::from(self.id))
    }

    fn username(&self) -> Result<String, ricochet_robots_websocket::Error> {
        Ok(self.username.clone())
    }

    fn discrim(&self) -> Result<u16, ricochet_robots_websocket::Error> {
        Ok(self.discriminator.map(|Discriminator(discrim)| discrim as u16).unwrap_or_default())
    }

    fn nickname(&self) -> Result<Option<String>, ricochet_robots_websocket::Error> {
        Ok(self.nick.clone())
    }
}

#[rocket::get("/api/websocket")]
pub(crate) fn websocket_legacy() -> Redirect {
    Redirect::permanent(uri!(websocket_v1))
}

#[rocket::get("/api/v1/websocket")]
pub(crate) fn websocket_v1(db_pool: &State<PgPool>, rr_lobbies: &State<Arc<RwLock<HashMap<u64, ricochet_robots_websocket::Lobby<User>>>>>, ws: WebSocket) -> rocket_ws::Channel<'static> {
    let db_pool = (*db_pool).clone();
    let rr_lobbies = (*rr_lobbies).clone();
    ws.channel(move |stream| async move {
        let (sink, stream) = stream.split();
        let sink = Arc::new(Mutex::new(sink));
        if let Err(e) = client_session_v1(db_pool, rr_lobbies, stream, Arc::clone(&sink)).await {
            let _ = lock!(sink = sink; ServerMessageV1::from_error(e).write_ws021(&mut *sink).await);
        }
        Ok(())
    }.boxed())
}

async fn client_session_v2(db_pool: PgPool, mut rocket_shutdown: rocket::Shutdown, mut stream: WsStream, sink: WsSink) -> Result<(), Error> {
    let mut user = None;
    let mut subscription_join_handles = FuturesUnordered::<tokio::task::JoinHandle<Result<Never, Error>>>::default();
    loop {
        select! {
            Some(res) = subscription_join_handles.next() => match res?? {},
            () = &mut rocket_shutdown => break Ok(()),
            res = ClientMessageV2::read_ws021(&mut stream) => match res? {
                ClientMessageV2::Auth { api_key } => {
                    let mut transaction = db_pool.begin().await?;
                    user = Some(User::from_api_key(&mut transaction, &api_key).await?.ok_or(Error::UnknownApiKey)?);
                    transaction.commit().await?;
                }
                ClientMessageV2::CurrentEvent => {
                    let Some(user) = &user else { return Err(Error::Permissions) };
                    if !user.is_mensch() { return Err(Error::Permissions) }
                    {
                        let db_pool = db_pool.clone();
                        let sink = sink.clone();
                        subscription_join_handles.push(tokio::spawn(async move {
                            #[derive(PartialEq)]
                            struct EventData {
                                id: String,
                                timezone: Tz,
                            }

                            let mut prev_event = None;
                            loop {
                                let now = Utc::now();
                                let mut current_event = None;
                                for row in sqlx::query!(r#"SELECT id, value AS "value: Json<Event>" FROM json_events"#).fetch_all(&db_pool).await? {
                                    if let (Some(start), Some(end)) = (row.value.start(&db_pool).await?, row.value.end(&db_pool).await?) {
                                        if start <= now && now < end {
                                            if let Some(other) = current_event.replace(EventData {
                                                id: row.id.clone(),
                                                timezone: row.value.timezone(&db_pool).await?.unwrap_or(Europe::Berlin),
                                            }) {
                                                return Err(Error::MultipleCurrentEvents([row.id, other.id]).into())
                                            }
                                        }
                                    }
                                }
                                if prev_event.is_none_or(|prev_state| prev_state != current_event) {
                                    if let Some(EventData { ref id, timezone }) = current_event {
                                        lock!(sink = sink; ServerMessageV2::CurrentEvent { id: id.clone(), timezone }.write_ws021(&mut *sink).await)?;
                                    } else {
                                        lock!(sink = sink; ServerMessageV2::NoEvent.write_ws021(&mut *sink).await)?;
                                    }
                                }
                                prev_event = Some(current_event);
                                sleep(Duration::from_secs(10)).await;
                            }
                        }));
                    }
                    let sink = sink.clone();
                    subscription_join_handles.push(tokio::spawn(async move {
                        let mut sil_version = SIL_VERSION.subscribe();
                        let mut prev_version = sil_version.borrow_and_update().clone();
                        if prev_version.is_none() {
                            Command::new("git").arg("pull").current_dir("/opt/git/github.com/dasgefolge/sil/main").check("git pull").await?;
                            let PackageManifest { package: PackageData { version } } = toml::from_slice(&fs::read("/opt/git/github.com/dasgefolge/sil/main/Cargo.toml").await?)?;
                            SIL_VERSION.send_replace(Some(version));
                            prev_version = sil_version.wait_for(Option::is_some).await.expect("static channel closed").clone();
                        }
                        let mut prev_version = prev_version.expect("checked above");
                        lock!(sink = sink; ServerMessageV2::LatestSilVersion(prev_version.clone()).write_ws021(&mut *sink).await)?;
                        loop {
                            sil_version.changed().await.expect("static channel closed");
                            let current_version = sil_version.borrow_and_update().clone().expect("None explicitly written to SIL_VERSION");
                            if prev_version != current_version {
                                lock!(sink = sink; ServerMessageV2::LatestSilVersion(current_version.clone()).write_ws021(&mut *sink).await)?;
                                prev_version = current_version;
                            }
                        }
                    }));
                }
            },
        }
    }
}

#[rocket::get("/api/v2/websocket")]
pub(crate) fn websocket_v2(db_pool: &State<PgPool>, rocket_shutdown: rocket::Shutdown, ws: WebSocket) -> rocket_ws::Channel<'static> {
    let db_pool = (*db_pool).clone();
    ws.channel(move |stream| async move {
        let (sink, stream) = stream.split();
        let sink = Arc::new(Mutex::new(sink));
        let ping_sink = sink.clone();
        let ping_loop = tokio::spawn(async move {
            loop {
                sleep(Duration::from_secs(30)).await;
                if lock!(ping_sink = ping_sink; ServerMessageV2::Ping.write_ws021(&mut *ping_sink).await).is_err() { break } //TODO better error handling
            }
        });
        if let Err(e) = client_session_v2(db_pool, rocket_shutdown, stream, WsSink::clone(&sink)).await {
            let _ = lock!(sink = sink; ServerMessageV2::Error {
                debug: format!("{e:?}"),
                display: String::default(),
            }.write_ws021(&mut *sink).await);
        }
        ping_loop.abort();
        Ok(())
    }.boxed())
}

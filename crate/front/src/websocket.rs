use {
    std::{
        collections::HashMap,
        fmt,
        sync::Arc,
        time::Duration,
    },
    async_proto::Protocol,
    futures::stream::{
        SplitSink,
        SplitStream,
        StreamExt as _,
    },
    rocket::State,
    rocket_ws::WebSocket,
    sqlx::PgPool,
    tokio::{
        sync::{
            Mutex,
            RwLock,
        },
        time::sleep,
    },
    crate::user::{
        Discriminator,
        User,
    },
};

type WsStream = SplitStream<rocket_ws::stream::DuplexStream>;
pub(crate) type WsSink = Arc<Mutex<SplitSink<rocket_ws::stream::DuplexStream, rocket_ws::Message>>>;

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error(transparent)] Event(#[from] gefolge_web_lib::event::Error),
    #[error(transparent)] Read(#[from] async_proto::ReadError),
    #[error(transparent)] RicochetRobots(#[from] ricochet_robots_websocket::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Write(#[from] async_proto::WriteError),
    #[error("you do not have permission to use the WebSocket endpoint")]
    Permissions,
    #[error("unknown API key")]
    UnknownApiKey,
}

#[derive(Protocol)]
enum ServerMessage {
    Ping,
    Error {
        debug: String,
        display: String,
    },
}

impl ServerMessage {
    fn from_error(e: impl fmt::Debug + fmt::Display) -> ServerMessage {
        ServerMessage::Error {
            debug: format!("{e:?}"),
            display: e.to_string(),
        }
    }
}

#[derive(Protocol)]
enum SessionPurpose {
    RicochetRobots,
    CurrentEvent,
}

async fn client_session(db_pool: PgPool, rr_lobbies: Arc<RwLock<HashMap<u64, ricochet_robots_websocket::Lobby<User>>>>, mut stream: WsStream, sink: WsSink) -> Result<(), Error> {
    let api_key = String::read_ws(&mut stream).await?;
    let mut transaction = db_pool.begin().await?;
    let user = User::from_api_key(&mut transaction, &api_key).await?.ok_or(Error::UnknownApiKey)?;
    transaction.commit().await?;
    if !user.is_mensch() { return Err(Error::Permissions) } //TODO allow special device API key for CurrentEvent purpose
    let ping_sink = Arc::clone(&sink);
    tokio::spawn(async move {
        loop {
            sleep(Duration::from_secs(30)).await;
            if ServerMessage::Ping.write_ws(&mut *ping_sink.lock().await).await.is_err() { break } //TODO better error handling
        }
    });
    match SessionPurpose::read_ws(&mut stream).await? {
        SessionPurpose::RicochetRobots => ricochet_robots_websocket::client_session(&rr_lobbies, user, stream, sink).await?,
        SessionPurpose::CurrentEvent => match crate::event::client_session(&db_pool, sink).await? {},
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
pub(crate) fn websocket(db_pool: &State<PgPool>, rr_lobbies: &State<Arc<RwLock<HashMap<u64, ricochet_robots_websocket::Lobby<User>>>>>, ws: WebSocket) -> rocket_ws::Channel<'static> {
    let db_pool = (*db_pool).clone();
    let rr_lobbies = (*rr_lobbies).clone();
    ws.channel(move |stream| Box::pin(async move {
        let (sink, stream) = stream.split();
        let sink = Arc::new(Mutex::new(sink));
        if let Err(e) = client_session(db_pool, rr_lobbies, stream, Arc::clone(&sink)).await {
            let _ = ServerMessage::from_error(e).write_ws(&mut *sink.lock().await).await;
        }
        Ok(())
    }))
}

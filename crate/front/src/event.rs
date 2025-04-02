use {
    std::{
        convert::Infallible as Never,
        time::Duration,
    },
    async_proto::Protocol,
    chrono::prelude::*,
    chrono_tz::{
        Europe,
        Tz,
    },
    sqlx::{
        PgPool,
        types::Json,
    },
    tokio::time::sleep,
    gefolge_web_lib::event::{
        Error,
        Event,
    },
    crate::websocket::WsSink,
};

#[derive(Protocol)]
enum ServerMessage {
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
    LatestVersion([u8; 20]),
}

pub(crate) async fn client_session(db_pool: &PgPool, sink: WsSink) -> Result<Never, crate::websocket::Error> {
    let mut prev_state = None;
    loop {
        let now = Utc::now();
        let mut current_event = None;
        for row in sqlx::query!(r#"SELECT id, value AS "value: Json<Event>" FROM json_events"#).fetch_all(db_pool).await? {
            if let (Some(start), Some(end)) = (row.value.start(db_pool).await?, row.value.end(db_pool).await?) {
                if start <= now && now < end {
                    if let Some((other_id, _)) = current_event.replace((row.id.clone(), row.value.timezone(db_pool).await?)) {
                        return Err(Error::MultipleCurrentEvents([row.id, other_id]).into())
                    }
                }
            }
        }
        if prev_state.map_or(true, |prev_state| prev_state != current_event) {
            if let Some((ref id, timezone)) = current_event {
                ServerMessage::CurrentEvent { id: id.clone(), timezone: timezone.unwrap_or(Europe::Berlin) }.write_ws021(&mut *sink.lock().await).await?;
            } else {
                ServerMessage::NoEvent.write_ws021(&mut *sink.lock().await).await?;
            }
        }
        prev_state = Some(current_event);
        sleep(Duration::from_secs(10)).await;
    }
}

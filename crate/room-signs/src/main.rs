use {
    base64::engine::{
        Engine as _,
        general_purpose::STANDARD as BASE64,
    },
    futures::future::FutureExt as _,
    rocket::{
        Rocket,
        State,
        config::SecretKey,
        data::{
            Limits,
            ToByteUnit as _,
        },
        response::content::RawHtml,
    },
    rocket_util::{
        Doctype,
        html,
    },
    serenity::model::prelude::*,
    sqlx::postgres::{
        PgConnectOptions,
        PgPool,
    },
    gefolge_web_lib::{
        config::Config,
        event::{
            self,
            AttendeeId,
            Event,
            LocationInfo,
            Season,
        },
        user::User,
    },
};

#[derive(Debug, thiserror::Error, rocket_util::Error)]
enum IndexError {
    #[error(transparent)] Event(#[from] event::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
}

#[rocket::get("/")]
async fn index(db_pool: &State<PgPool>) -> Result<Option<RawHtml<String>>, IndexError> {
    let mut transaction = db_pool.begin().await?;
    let event_id = event::Id { season: Season::Sommer, year: 2026 };
    let Some(event) = Event::load(&mut *transaction, event_id).await? else { return Ok(None) };
    let LocationInfo::Known(loc) = event.location_info(&mut transaction).await? else { return Ok(None) };
    Ok(Some(html! {
        : Doctype;
        head {
            style : RawHtml("
                @page {
                    size: landscape;
                }

                body {
                    columns: 2;
                    margin: 0;
                    font-family: \"DejaVu Sans\";
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    grid-auto-rows: 100vh;
                    gap: 1px; /* smaller gaps don't seem to be rendered, at least in preview */ /*TODO test on actual paper */
                    background: rgba(128, 128, 128, 0.5); /* cutting aid */
                }

                .room {
                    padding: 8px;
                    text-align: center;
                    display: flex;
                    flex-flow: column;
                    background: white;
                }

                h1,
                h2 {
                    font-size: 28pt;
                }

                table {
                    width: 45vw;
                    margin: 0 auto;
                }

                td {
                    padding-top: 4pt;
                    font-size: 21pt;
                    border-bottom: 1pt solid black;
                }

                img {
                    margin: auto auto;
                }

                h2 {
                    font-weight: normal;
                    margin-top: auto;
                }

                h2.xor {
                    margin-top: 0;
                }
            ");
        }
        body {
            @for (_, section) in loc.rooms {
                @for (name, room) in section {
                    @let mut attendees = event.attendees().iter().filter(|attendee| attendee.room.as_ref().is_some_and(|room| *room == name)).fuse();
                    div(class = "room") {
                        h1 {
                            : "Zimmer ";
                            : name;
                        }
                        table {
                            tbody {
                                @for _ in 0..room.beds {
                                    tr {
                                        td {
                                            @if let Some(attendee) = attendees.next() {
                                                @match attendee.id {
                                                    AttendeeId::EventGuest(_) => : attendee.name;
                                                    AttendeeId::Discord(user_id) => {
                                                        @let user = User::from_id(&mut transaction, user_id).await?.unwrap();
                                                        : user.nick.unwrap_or(user.username);
                                                    }
                                                }
                                            } else {
                                                : RawHtml("&nbsp;");
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        @let is_xor = room.beds == 1 && event.attendees().iter().filter(|attendee| attendee.room.as_ref().is_some_and(|room| *room == name)).all(|attendee| attendee.id == AttendeeId::Discord(UserId::new(148148020259717120)));
                        @if is_xor {
                            img(src = "https://gefolge.org/static/xor_approves.png"); //TODO use static_uri macro
                        }
                        h2(class? = is_xor.then_some("xor")) {
                            : event.name(event_id);
                        }
                    }
                }
            }
        }
    }))
}

#[derive(Debug, thiserror::Error)]
enum MainError {
    #[error(transparent)] Base64(#[from] base64::DecodeError),
    #[error(transparent)] Config(#[from] gefolge_web_lib::config::Error),
    #[error(transparent)] Rocket(#[from] rocket::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Task(#[from] tokio::task::JoinError),
}

async fn rocket(config: &Config) -> Result<Rocket<rocket::Ignite>, MainError> {
    Ok(rocket::custom(rocket::Config::figment().merge(rocket::Config {
        secret_key: SecretKey::from(&BASE64.decode(&config.secret_key)?),
        log_level: Some(rocket::config::Level::ERROR),
        limits: Limits::default()
            .limit("bytes", 2.mebibytes()), // for proxied wiki edits
        ..rocket::Config::default()
    }).merge(("port", 24817))) //TODO report issue for lack of typed interface to set port, see https://github.com/rwf2/Rocket/commit/fd294049c784cb52680a423616fadc29d57fa25b
    .mount("/", rocket::routes![
        index,
    ])
    .manage(PgPool::connect_with(PgConnectOptions::default().username("fenhl").database("gefolge").application_name("gefolge-web")).await?)
    .launch().await?)
}

#[wheel::main(rocket)]
async fn main() -> Result<(), MainError> {
    let config = Config::load().await?;
    let rocket = rocket(&config).await?;
    let () = tokio::spawn(rocket.launch()).map(|res| match res {
        Ok(Ok(Rocket { .. })) => Ok(()),
        Ok(Err(e)) => Err(MainError::from(e)),
        Err(e) => Err(MainError::from(e)),
    }).await?;
    Ok(())
}

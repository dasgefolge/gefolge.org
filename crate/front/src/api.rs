use {
    chrono::prelude::*,
    rocket::{
        State,
        http::Status,
        response::content::RawHtml,
        serde::json::Json,
        uri,
    },
    rocket_util::{
        Origin,
        html,
    },
    serde::Serialize,
    serde_with::{
        BoolFromInt,
        serde_as,
    },
    serenity::model::prelude::*,
    sqlx::PgPool,
    gefolge_web_lib::{
        event::{
            AttendeeId,
            Event,
            Going,
        },
        user::{
            Mensch,
            User,
        },
    },
    crate::{
        PageError,
        StatusOrError,
        event,
        page,
        wiki,
    },
};

#[rocket::get("/api")]
pub(crate) async fn docs(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>) -> Result<RawHtml<String>, PageError> {
    let mut transaction = db_pool.begin().await?;
    let content = html! {
        p {
            : "Die ";
            strong : "gefolge.org API";
            : " ist ein Teil der website, der für Nutzung mit apps, die kein web browser sind, gedacht ist. Mit deinem API key kannst du die API auch ohne Anmeldung über Discord verwenden. Falls du nach Anmeldedaten gefragt wirst, verwende ";
            code : "api";
            : " als Benutzername und deinen API key als Passwort.";
        }
        p {
            : "Dein API key: ";
            code(class = "spoiler") : me.api_key(&mut transaction).await?;
        }
        p {
            : "Falls dein API key in falsche Hände gerät, kannst du jederzeit einen ";
            a(class = "button", href = format!("/mensch/{}/reset-key", me.id)) : "neuen API key generieren";
            : ". Du musst dich dann überall, wo du dich mit dem alten API key angemeldet hast, mit dem neuen anmelden.";
        }
        h1 : "Endpoints";
        h2 {
            a(href = "/api/calendar/signups.ics") {
                code : "/api/calendar/signups.ics";
            }
        }
        p {
            : "Ein Kalender im ";
            a(href = "https://en.wikipedia.org/wiki/ICalendar") : "iCalendar";
            : "-Format mit allen events und Programmpunkten, für die du angemeldet bist.";
        }
        p {
            : "In Mozilla Thunderbird und Apple Calendar muss folgende Adresse verwendet werden, um einen dieser Kalender zu abonnieren: ";
            code {
                : "https://api:";
                i : "apikey";
                : "@gefolge.org/api/calendar/signups.ics";
            }
            : ", wobei ";
            code {
                i : "apikey";
            }
            : " durch deinen API key ersetzt werden sollte.";
        }
        h2 {
            a(href = "/api/discord/voice-state.json") {
                code : "/api/discord/voice-state.json";
            }
        }
        p : "Infos, wer gerade in welchen voice channels ist."; //TODO document JSON schema
        h2 {
            code {
                : "/api/event/";
                i : "event";
                : "/calendar/all.ics";
            }
        }
        p : "Ein Kalender im iCalendar-Format mit allen Programmpunkten von diesem event.";
        p {
            : "In Mozilla Thunderbird und Apple Calendar muss folgende Adresse verwendet werden, um einen dieser Kalender zu abonnieren: ";
            code {
                : "https://api:";
                i : "apikey";
                : "@gefolge.org/api/event/";
                i : "event";
                : "/calendar/all.ics";
            }
            : ", wobei ";
            code {
                i : "apikey";
            }
            : " durch deinen API key ersetzt werden sollte.";
        }
        h2 {
            code {
                : "/api/event/";
                i : "event";
                : "/doli-attendees.json";
            }
        }
        p : "Infos zu den Anmeldungen für dieses Event in einem für die Vereinsdatenbank geeigneten Format. Zugriff nur für den Vorstand.";
        h2 {
            code {
                : "/api/event/";
                i : "event";
                : "/overview.json";
            }
        }
        p {
            : "Infos zu diesem event im auf ";
            a(href = uri!(wiki::namespaced_article("event-json", "meta"))) : uri!("https://gefolge.org", wiki::namespaced_article("event-json", "meta"));
            : " dokumentierten Format.";
        }
        h2 {
            a(href = "/api/websocket") {
                code : "/api/websocket";
            }
        }
        p {
            : "Ein WebSocket server für länger dauernde Verbindungen. Dokumentation siehe ";
            a(href = "https://github.com/dasgefolge/gefolge-websocket") : "https://github.com/dasgefolge/gefolge-websocket"; //TODO display docs on endpoint's Bad Request error page
        }
    };
    page(transaction, me, &uri, crate::PageKind::Sub(vec![
        html! {
            : "API";
        },
    ]), "gefolge.org API", content).await
}

#[serde_as]
#[derive(Serialize)]
pub(crate) struct DoliAttendee {
    full_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    email: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    user_id: Option<UserId>,
    application_id: String,
    #[serde_as(as = "BoolFromInt")]
    accepted: bool,
    days: usize,
    participation_fee: u64,
    status_updated_at: DateTime<Utc>,
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum DoliAttendeesError {
    #[error(transparent)] Event(#[from] gefolge_web_lib::event::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] TryFromInt(#[from] std::num::TryFromIntError),
    #[error("missing last-updated data")]
    LastUpdated,
    #[error("attendee without ticket option")]
    MissingTicketOption,
    #[error("this endpoint is not yet implemented for events without ticket options")]
    NoTicketOptions,
    #[error("ticket option does not cost a whole number of Euros")]
    TicketOptionCost,
    #[error("unknown ticket option")]
    UnknownTicketOption,
}

impl<E: Into<DoliAttendeesError>> From<E> for StatusOrError<DoliAttendeesError> {
    fn from(e: E) -> Self {
        Self::Err(e.into())
    }
}

#[rocket::get("/api/event/<id>/doli-attendees.json")]
pub(crate) async fn doli_attendees(db_pool: &State<PgPool>, me: Mensch, id: event::NewId) -> Result<Json<Vec<DoliAttendee>>, StatusOrError<DoliAttendeesError>> {
    if !me.is_vorstand() { return Err(StatusOrError::Status(Status::Unauthorized)) };
    let event::NewId(id) = id;
    let mut transaction = db_pool.begin().await?;
    let Some(event) = Event::load(&mut *transaction, id).await? else { return Err(StatusOrError::Status(Status::NotFound)) };
    let mut buf = Vec::with_capacity(event.attendees().len());
    for attendee in event.attendees() {
        buf.push(DoliAttendee {
            full_name: match attendee.id {
                AttendeeId::EventGuest(_) => attendee.name.clone().unwrap(),
                AttendeeId::Discord(user_id) => {
                    let user = User::from_id(&mut transaction, user_id).await?.expect("nonexistent attendee");
                    user.nick.unwrap_or(user.username)
                }
            },
            email: attendee.email.clone(),
            user_id: match attendee.id {
                AttendeeId::EventGuest(_) => None,
                AttendeeId::Discord(user_id) => Some(user_id),
            },
            application_id: match attendee.id {
                AttendeeId::EventGuest(attendee_id) => format!("{id}-{attendee_id}"),
                AttendeeId::Discord(user_id) => format!("{id}-{user_id}"),
            },
            accepted: true,
            days: event.attendee_nights(&mut transaction, attendee).await?.ok_or(StatusOrError::Status(Status::NotFound))?.filter(|(_, night)| match night.going {
                Going::Yes | Going::Maybe => true,
                Going::No => false,
            }).count(),
            participation_fee: {
                let ticket = attendee.ticket.as_deref().ok_or(DoliAttendeesError::MissingTicketOption)?;
                let cost = event.ticket_options().ok_or(DoliAttendeesError::NoTicketOptions)?.iter().find(|option| option.id == ticket).ok_or(DoliAttendeesError::UnknownTicketOption)?.cost;
                if cost.cents % 100 != 0 { return Err(StatusOrError::Err(DoliAttendeesError::TicketOptionCost)) }
                (cost.cents / 100).try_into()?
            },
            status_updated_at: event.attendee_nights(&mut transaction, attendee).await?.ok_or(StatusOrError::Status(Status::NotFound))?.filter_map(|(_, night)| night.last_updated).max().ok_or(DoliAttendeesError::LastUpdated)?,
        });
    }
    Ok(Json(buf))
}

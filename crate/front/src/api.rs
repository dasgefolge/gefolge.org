use {
    chrono::prelude::*,
    rocket::{
        State,
        http::Status,
        serde::json::Json,
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
        StatusOrError,
        event,
    },
};

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
    #[error("missing or invalid ticket option")]
    TicketOption,
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
                let ticket_option = attendee.ticket_option.as_deref().ok_or(DoliAttendeesError::TicketOption)?;
                let cost = event.ticket_options().ok_or(DoliAttendeesError::TicketOption)?.iter().find(|option| option.id == ticket_option).ok_or(DoliAttendeesError::TicketOption)?.cost;
                if cost.cents % 100 != 0 { return Err(StatusOrError::Err(DoliAttendeesError::TicketOption)) }
                (cost.cents / 100).try_into()?
            },
            status_updated_at: event.attendee_nights(&mut transaction, attendee).await?.ok_or(StatusOrError::Status(Status::NotFound))?.filter_map(|(_, night)| night.last_updated).max().ok_or(DoliAttendeesError::LastUpdated)?,
        });
    }
    Ok(Json(buf))
}

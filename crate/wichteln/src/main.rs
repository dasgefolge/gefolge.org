use {
    std::{
        collections::HashMap,
        iter,
    },
    chrono::prelude::*,
    chrono_tz::Europe,
    itertools::Itertools as _,
    rand::{
        prelude::*,
        rng,
    },
    serenity::model::prelude::*,
    sqlx::{
        PgPool,
        Postgres,
        Transaction,
        postgres::PgConnectOptions,
        types::Json,
    },
    wheel::traits::LocalResultExt as _,
    gefolge_web_lib::{
        event::{
            self,
            AttendeeId,
            Event,
            Season,
        },
        user::User,
    },
};

macro_rules! template {
    () => {
        "Hallo und willkommen beim diesjährigen Wichteln auf {event}!

Im Prinzip läuft es so ab wie immer. Hier die wichtigsten Infos:

• Deine Person beim Wichteln ist: **{target}**. Wenn dir dieser Name nichts sagt, wende dich bitte an {fenhl}.
• Bitte besorge für diese Person ein nettes und am besten persönliches Geschenk im Wert von ca. 10–15€. Falls du Ideen brauchst, kannst du natürlich auch andere Leute fragen, aber bitte sorge dafür, dass möglichst wenige Leute erfahren, wen du hast. (Tipp: Am besten VOR Silvester etwas besorgen und nicht erst vor Ort.)
• Die Geschenke werden vor Ort gesammelt und dann voraussichtlich am Silvesterabend verteilt. Falls du oder dein Ziel an dem Abend nicht da sein sollten, finden wir eine andere Lösung für diese Ausnahmen. Bisher hat noch immer jeder sein Geschenk erhalten.
• **Bitte bringe den Namen der Zielperson gut außen sichtbar am Geschenk an!** Da es Leute mit gleichem Namen geben könnte, am besten eindeutig markieren (z.B. mit Nachnamen).

*Ich bin ein bot, Antworten an mich werden nicht gelesen!* Bei irgendwelchen Fragen über das Wichteln wende dich stattdessen bitte direkt an {orga}.

Viel Spaß beim Geschenk suchen, finden, verschenken und bekommen!"
    };
}

const FENHL: UserId = UserId::new(86841168427495424);

async fn dm_mention(transaction: &mut Transaction<'_, Postgres>, event: &Event, attendee: AttendeeId) -> Result<String, Error> {
    Ok(match attendee {
        AttendeeId::EventGuest(guest_id) => event.attendee(AttendeeId::EventGuest(guest_id)).unwrap().name.as_ref().unwrap().clone(),
        AttendeeId::Discord(user_id) => {
            let user = User::from_id(transaction, user_id).await?.unwrap();
            user.nick.unwrap_or(user.username)
        }
    })
}

async fn gen_map(db_pool: &PgPool, event_id: event::Id, external_signups: &[UserId]) -> Result<HashMap<AttendeeId, AttendeeId>, Error> {
    let Json(mut menschen) = sqlx::query_scalar!(r#"SELECT value -> 'programm' -> 'wichteln' -> 'signups' AS "signups!: Json<Vec<_>>" FROM json_events WHERE id = $1"#, event_id as _).fetch_one(db_pool).await?;
    menschen.extend(external_signups.iter().map(|signup| AttendeeId::Discord(*signup)));
    if menschen.is_empty() { return Ok(HashMap::default()) }
    menschen.shuffle(&mut rng());
    Ok(
        menschen.iter()
            .zip_eq(menschen[1..].iter().chain(iter::once(&menschen[0])))
            .map(|(k, v)| (*k, *v))
            .collect()
    )
}

#[derive(clap::Parser)]
struct Args {
    #[clap(long, conflicts_with("date"))]
    now: bool,
    #[clap(required_unless_present("now"))]
    date: Option<NaiveDate>,
    external_signups: Vec<UserId>,
}

#[derive(Debug, thiserror::Error)]
enum Error {
    #[error(transparent)] Heliocron(#[from] heliocron::sleep::Error),
    #[error(transparent)] Peter(#[from] peter_ipc::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] TimeFromLocal(#[from] wheel::traits::TimeFromLocalError<DateTime<chrono_tz::Tz>>),
    #[error("no Sil event defined for {year}")]
    NoEvent {
        year: i32
    },
}

#[wheel::main]
async fn main(Args { now, date, external_signups }: Args) -> Result<(), Error> {
    let year = match (now, date) {
        (false, None) => unreachable!("should be prevented by #[clap(required_unless_present)]"),
        (false, Some(date)) => {
            heliocron::sleep::sleep_until(date.and_time(NaiveTime::MIN).and_local_timezone(Europe::Berlin).single_ok()?).await?;
            date.year()
        }
        (true, None) => Utc::now().with_timezone(&Europe::Berlin).year(),
        (true, Some(_)) => unreachable!("should be prevented by #[clap(conflicts_with)]"),
    };
    let db_pool = PgPool::connect_with(PgConnectOptions::default().username("fenhl").database("gefolge").application_name("gefolge-wichteln")).await?;
    let mut transaction = db_pool.begin().await?;
    let event_id = event::Id { season: Season::Winter, year };
    let event = Event::load(&db_pool, event_id).await?.ok_or_else(|| Error::NoEvent { year })?;
    let Json(orga) = sqlx::query_scalar!(r#"SELECT value -> 'programm' -> 'wichteln' -> 'orga' AS "orga!: _" FROM json_events WHERE id = $1"#, event_id as _).fetch_one(&db_pool).await?;
    sqlx::query!("UPDATE json_events SET value = JSONB_SET(value, '{programm,wichteln,closed}', 'true') WHERE id = $1", event_id as _).execute(&db_pool).await?;
    let map = if let Some(Json(map)) = sqlx::query_scalar!(r#"SELECT value -> 'programm' -> 'wichteln' -> 'targets' AS "targets: Json<HashMap<_, _>>" FROM json_events WHERE id = $1"#, event_id as _).fetch_one(&db_pool).await? {
        map
    } else {
        let mut map = gen_map(&db_pool, event_id, &external_signups).await?;
        while map.iter().any(|(mensch, target)| event.attendee(*mensch).unwrap().via_id.is_some_and(|via_id| AttendeeId::Discord(via_id) == *target)) {
            map = gen_map(&db_pool, event_id, &external_signups).await?
        }
        sqlx::query!("UPDATE json_events SET value = JSONB_SET(value, '{programm,wichteln,targets}', $1) WHERE id = $2", Json(&map) as _, event_id as _).execute(&db_pool).await?;
        map
    };
    for (mensch, target) in map.into_iter().sorted_unstable_by_key(|(mensch, _)| std::cmp::Reverse(*mensch)) { //TODO reverse order was originally intended to ensure proxies get their own message before their guests', needs adjustment for Discord guests
        let mut messages = HashMap::new();
        if let AttendeeId::Discord(mensch) = mensch {
            messages.insert(mensch, format!(
                template!(),
                target = dm_mention(&mut transaction, &event, target).await?,
                fenhl = dm_mention(&mut transaction, &event, AttendeeId::Discord(FENHL)).await?,
                orga = dm_mention(&mut transaction, &event, orga).await?,
                event = event.name(event_id),
            ));
        }
        if let Some(via) = event.attendee(mensch).unwrap().via(&mut transaction).await? {
            let message = if let AttendeeId::Discord(_) = mensch {
                format!(
                    concat!("**Kopie der Nachricht für {mensch} (bitte sicherstellen, dass sie gelesen wird):**\n\n", template!()),
                    mensch = dm_mention(&mut transaction, &event, mensch).await?,
                    target = dm_mention(&mut transaction, &event, target).await?,
                    fenhl = dm_mention(&mut transaction, &event, AttendeeId::Discord(FENHL)).await?,
                    orga = dm_mention(&mut transaction, &event, orga).await?,
                    event = event.name(event_id),
                )
            } else {
                format!(
                    concat!("**Bitte an {mensch} weiterleiten:**\n\n", template!()),
                    mensch = dm_mention(&mut transaction, &event, mensch).await?,
                    target = dm_mention(&mut transaction, &event, target).await?,
                    fenhl = dm_mention(&mut transaction, &event, AttendeeId::Discord(FENHL)).await?,
                    orga = dm_mention(&mut transaction, &event, orga).await?,
                    event = event.name(event_id),
                )
            };
            messages.insert(via.id, message);
        }
        for (rcpt, message) in messages {
            peter_ipc::msg(rcpt, message)?;
            println!("message sent to {rcpt}");
        }
    }
    transaction.commit().await?;
    Ok(())
}

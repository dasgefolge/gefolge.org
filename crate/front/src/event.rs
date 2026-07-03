use {
    chrono::prelude::*,
    itertools::Itertools as _,
    lazy_regex::regex_is_match,
    rocket::{
        FromForm,
        State,
        UriDisplayPath,
        form::{
            self,
            Context,
            Contextual,
            Form,
        },
        http::Status,
        request::FromParam,
        response::{
            Redirect,
            content::RawHtml,
        },
        uri,
    },
    rocket_csrf::CsrfToken,
    rocket_util::{
        ContextualExt as _,
        CsrfForm,
        Origin,
        html,
    },
    serde_json::json,
    serenity::{
        all::Context as DiscordCtx,
        utils::MessageBuilder,
    },
    serenity_utils::RwFuture,
    sqlx::{
        PgPool,
        Postgres,
        Transaction,
        types::Json,
    },
    gefolge_web_lib::{
        config::Config,
        event::{
            AnimalProducts,
            AttendeeId,
            Event,
            Going,
            Id,
            IdParseError,
            LocationInfo,
        },
        lang,
        peter::GEFOLGE,
        time::{
            MaybeAwareDateTime,
            MaybeLocalDateTime,
            iter_date_range,
        },
        user::{
            Mensch,
            User,
        },
    },
    crate::{
        IndexError,
        PageKind,
        RedirectOrContent,
        StatusOrError,
        form::{
            form_field,
            full_form,
        },
        page,
        time::{
            format_date_range,
            format_datetime_range,
            format_datetime,
        },
    },
};

pub(crate) struct EventOverview {
    pub(crate) id: String,
    pub(crate) start: Option<MaybeLocalDateTime>,
    pub(crate) end: Option<MaybeLocalDateTime>,
    pub(crate) event: Event,
}

pub(crate) struct EventsOverview {
    past: Vec<EventOverview>,
    pub(crate) ongoing: Vec<EventOverview>,
    pub(crate) upcoming: Vec<EventOverview>,
}

pub(crate) async fn load_events(transaction: &mut Transaction<'_, Postgres>) -> Result<EventsOverview, IndexError> {
    let now = Utc::now();
    let mut past = Vec::default();
    let mut upcoming = Vec::default();
    for row in sqlx::query!(r#"SELECT id, value AS "value: Json<Event>" FROM json_events"#).fetch_all(&mut **transaction).await? {
        let start = row.value.0.start(&mut *transaction).await?;
        let end = row.value.0.end(&mut *transaction).await?;
        if end.is_none_or(|end| end > now) { &mut upcoming } else { &mut past }.push(EventOverview { id: row.id, start, end, event: row.value.0 });
    }
    upcoming.sort_unstable_by(|EventOverview { id: id1, start: start1, .. }, EventOverview { id: id2, start: start2, ..}|
        start1.is_none().cmp(&start2.is_none()) // nulls last
            .then_with(|| start1.cmp(start2))
            .then_with(|| id1.cmp(id2))
    );
    let ongoing = upcoming.extract_if(.., |eo| eo.start.is_some_and(|start| start <= now)).collect();
    past.sort_unstable_by(|EventOverview { id: id1, end: end1, .. }, EventOverview { id: id2, end: end2, .. }|
        end2.is_none().cmp(&end1.is_none()) // nulls last
            .then_with(|| end2.cmp(end1))
            .then_with(|| id2.cmp(id1))
    );
    Ok(EventsOverview { past, ongoing, upcoming })
}

#[rocket::get("/event")]
pub(crate) async fn index(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>) -> Result<RawHtml<String>, IndexError> {
    let mut transaction = db_pool.begin().await?;
    let events = load_events(&mut transaction).await?;
    let content = html! {
        @let viewer_data = me.data(&mut transaction).await?;
        h1 : "Events";
        @if !events.ongoing.is_empty() {
            h2 : "laufende Events";
            ul {
                @for EventOverview { id, start, end, event } in events.ongoing {
                    li {
                        : event.to_html(&id);
                        @if let (Some(start), Some(end)) = (start, end) {
                            : " (";
                            : format_datetime_range(&viewer_data, start, end);
                            : ")";
                        }
                    }
                }
            }
        }
        @if !events.upcoming.is_empty() {
            h2 : "zukünftige Events";
            ul {
                @for EventOverview { id, start, end, event } in events.upcoming {
                    li {
                        : event.to_html(&id);
                        @if let (Some(start), Some(end)) = (start, end) {
                            : " (";
                            : format_datetime_range(&viewer_data, start, end);
                            : ")";
                        }
                    }
                }
            }
        }
        @if !events.past.is_empty() {
            h2 : "vergangene Events";
            ul {
                @for EventOverview { id, start, end, event } in events.past {
                    li {
                        : event.to_html(&id);
                        @if let (Some(start), Some(end)) = (start, end) {
                            : " (";
                            : format_datetime_range(&viewer_data, start, end);
                            : ")";
                        }
                    }
                }
            }
        }
    };
    Ok(page(transaction, me, &uri, PageKind::Sub(vec![
        html! {
            : "events";
        },
    ]), "Events — Das Gefolge", content).await?)
}

/// Eine ID für ein event, das ab 2026 stattfindet und daher über den Verein organisiert wird.
///
/// For now, we only handle these events in Rust and forward to Python for older events.
#[derive(UriDisplayPath)]
pub(crate) struct NewId(Id);

#[derive(Debug, thiserror::Error)]
pub(crate) enum NewIdFromParamError {
    #[error(transparent)] Parse(#[from] IdParseError),
    #[error("events that started in 2025 or earlier are not yet handled in Rust")]
    Old,
}

impl FromParam<'_> for NewId {
    type Error = NewIdFromParamError;

    fn from_param(param: &str) -> Result<Self, Self::Error> {
        let id = param.parse::<Id>()?;
        if id.year < 2026 { return Err(NewIdFromParamError::Old) }
        Ok(Self(id))
    }
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum GetError {
    #[error(transparent)] Event(#[from] gefolge_web_lib::event::Error),
    #[error(transparent)] Page(#[from] crate::PageError),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] ToMaybeLocal(#[from] gefolge_web_lib::time::ToMaybeLocalError),
    #[error(transparent)] Wiki(#[from] crate::wiki::Error),
}

impl<E: Into<GetError>> From<E> for StatusOrError<GetError> {
    fn from(e: E) -> Self {
        Self::Err(e.into())
    }
}

async fn overview_page(config: &Config, db_pool: &PgPool, me: User, uri: Origin<'_>, csrf: Option<&CsrfToken>, new_id: NewId, ctx: &Context<'_>) -> Result<RawHtml<String>, StatusOrError<GetError>> {
    let now = Utc::now();
    let NewId(id) = new_id;
    let mut transaction = db_pool.begin().await?;
    let viewer_data = me.data(&mut transaction).await?;
    let Some(event) = Event::load(&mut *transaction, id).await? else { return Err(StatusOrError::Status(Status::NotFound)) };
    if !me.is_mensch() && event.attendee(AttendeeId::Discord(me.id)).is_none() { return Err(StatusOrError::Status(Status::Unauthorized)) }
    let location_info = event.location_info(&mut transaction).await?;
    let content = html! {
        p {
            strong : event.name(id);
            @if let Some(start) = event.start(&mut transaction).await? {
                @if let Some(end) = event.end(&mut transaction).await? {
                    @if end < now {
                        : " fand vom ";
                    } else {
                        : " findet vom ";
                    }
                    : format_datetime(&viewer_data, start, false);
                    : " bis zum ";
                    : format_datetime(&viewer_data, end, false);
                    @match &location_info {
                        LocationInfo::Unknown => : " statt. Der Ort steht noch nicht fest.";
                        LocationInfo::Online => : " online statt.";
                        LocationInfo::Known(loc) => {
                            : " ";
                            : loc;
                            : " statt.";
                        }
                    }
                } else {
                    @if start < now {
                        : " begann am ";
                    } else {
                        : " beginnt am ";
                    }
                    : format_datetime(&viewer_data, start, false);
                    @match &location_info {
                        LocationInfo::Unknown => : ". Ort und Enddatum stehen noch nicht fest.";
                        LocationInfo::Online => : " und findet online statt. Das Enddatum steht noch nicht fest.";
                        LocationInfo::Known(loc) => {
                            : " und findet ";
                            : loc;
                            : " statt. Das Enddatum steht noch nicht fest.";
                        }
                    }
                }
            } else {
                : " ist geplant aber hat noch keinen Termin.";
            }
        }
        @let orga_unassigned = event.orga_unassigned(id);
        @if matches!(location_info, LocationInfo::Unknown | LocationInfo::Known(_)) && !orga_unassigned.is_empty() {
            p {
                : "Wir suchen noch Orga-Menschen für folgende Aufgaben: ";
                : lang::join_opt(orga_unassigned).expect("checked above");
                : ".";
                @if me.is_mensch() {
                    : " Wenn du etwas davon übernehmen möchtest, melde dich bitte bei ";
                    : config.admin(&mut transaction).await?;
                    : ". ";
                    a(href = uri!(_, crate::wiki::main_article("sil-faq"), "#orga")) : "Weitere Infos";
                }
            }
        }
        /*
        <p>
            {% if event.location is not none and event.location.is_online %}
                {# Programmpunkte #}
                {% set num_programm = event.programm | selectattr('listed') | length %}
                {% if num_programm > 0 %}
                    Aktuell {% if num_programm == 1 %}ist{% else %}sind{% endif %} <a href="{{(g.view_node / 'programm').url}}">{% if num_programm == 1 %}ein Programmpunkt{% else %}{{num_programm}} Programmpunkte{% endif %}</a> geplant.
                {% else %}
                    Aktuell sind noch keine Programmpunkte geplant.
                {% endif %}
            {% elif event.signups | length > 0 %}
                {# Programmpunkte #}
                {% set num_programm = event.programm | selectattr('listed') | length %}
                {% if num_programm > 0 %}
                    Aktuell {% if num_programm == 1 %}ist{% else %}sind{% endif %} <a href="{{(g.view_node / 'programm').url}}">{% if num_programm == 1 %}ein Programmpunkt{% else %}{{num_programm}} Programmpunkte{% endif %}</a> geplant und
                {% else %}
                    Aktuell {% if event.signups | length == 1 %}ist{% else %}sind{% endif %}
                {% endif %}
                {# Menschen #}
                <a href="{{(g.view_node / 'mensch').url}}">{% if event.signups | length == 1 %}ein Mensch{% else %}{{event.signups | length}} Menschen{% endif %}</a> {% if num_programm > 1 and event.signups | length < 2 %}ist{% elif num_programm == 1 and event.signups | length > 1 %}sind{% endif %} angemeldet.
                {# freie Plätze #}
                {% if 'capacity' in event.data %}
                    {% macro block_overview(block_start, block_end, capacity, free) %}
                        Vom {{block_start | dm(event.timezone)}} bis zum {{block_end | dm(event.timezone)}} gibt es {{capacity}} Betten,
                        {% if free > 0 %}
                            von denen noch {% if free > 1 %}{{free}} frei sind{% else %}eins frei ist{% endif %}.
                        {% else %}
                            die mindestens in einer Nacht alle belegt sind.
                        {% endif %}
                    {% endmacro %}
                    {% set ns = namespace(block_start=event.start.date()) %}
                    {% for block_end in event.nights %}
                        {% if event.capacity(block_end) != event.capacity(ns.block_start) %}
                            {{block_overview(ns.block_start, block_end, event.capacity(ns.block_start), event.free(ns.block_start, block_end))}}
                            {% set ns.block_start = block_end %}
                        {% endif %}
                    {% endfor %}
                    {{block_overview(ns.block_start, event.end.date(), event.capacity(ns.block_start), event.free(ns.block_start, event.end.date()))}}
                {% elif event.location is not none and 'capacity' in event.location.data %}
                    {% set capacity = event.location.data['capacity'].value() %}
                    {% set naive_free = capacity - (event.signups | length) %}
                    {% set free = event.free() %}
                    {% if free != naive_free %}
                        Wegen „vielleicht“s und Menschen, die an verschiedenen Tagen da sind, sind aber erst {{capacity - free}} Plätze belegt.
                    {% endif %}
                    {% if free > 0 %}
                        Das Haus hat {{capacity}} Betten, es {% if free > 1 %}sind{% else %}ist{% endif %} also noch {{free}} Bett{% if free > 1 %}en{% endif %} frei.
                    {% else %}
                        Damit ist das Haus zumindest zeitweise voll. {#TODO check for free nights, adjust message accordingly #}
                    {% endif %}
                {% endif %}
            {% else %}
                Aktuell ist noch niemand angemeldet.
            {% endif %}
        </p>
        */
        @if let Some(source) = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = 'event' ORDER BY timestamp DESC LIMIT 1", id as _).fetch_optional(&mut *transaction).await? {
            : crate::wiki::render_wiki_page(&mut transaction, &source).await?;
        } else {
            p : "Eventbeschreibung coming soon™";
        }
        h1(id = "signup") : "Anmeldung";
        @if let Some(attendee) = event.attendee(AttendeeId::Discord(me.id)) {
            p {
                @if let Some(via) = attendee.via(&mut transaction).await? {
                    : via;
                    : " hat";
                } else {
                    : "Du hast";
                }
                : " dich am ";
                : format_datetime(&viewer_data, attendee.signup.to_maybe_local(event.timezone(&mut transaction).await?)?, false);
                : " angemeldet.";
            }
            p {
                : "Du kannst ";
                a(href = format!("/event/{id}/mensch/{}", me.id)) : "deine Anmeldungsdaten";
                : " jederzeit ";
                a(href = format!("/event/{id}/mensch/{}/edit", me.id)) : "bearbeiten";
                : ". Einige Teile der Eventanmeldung sind noch in Arbeit (z.B. Bettwäsche-Börse). Wenn etwas Neues fertig ist, wirst du auf Discord angepingt."; //TODO
            }
            /*
            {% if g.user in event.menschen %}
                {% if event.guests | selectattr("via", "equalto", g.user) | length > 0 %}
                    <h2>Gäste</h2>
                    <ul>
                        {% for guest in event.guests | selectattr("via", "equalto", g.user) %}
                            {% if guest in event.signups %}
                                <li><a href="{{(g.view_node / 'mensch' / guest).url}}">{{guest}}</a>: Anmeldung bestätigt</li>
                            {% else %}
                                <li>{{guest}}: noch nicht angemeldet</li> {#TODO link to event/guest-confirm.html.j2 #}
                            {% endif %}
                        {% endfor %}
                    </ul>
                    {% if event.guest_signup_block_reason is not none %}
                        {{event.guest_signup_block_reason | markdown}}
                    {% elif g.user is admin or (event.end is not none and event.end > g.now) %}
                        <p><a href="{{(g.view_node / 'guest').url}}">Weiteren Gast anmelden</a></p>
                    {% endif %}
                {% elif event.guest_signup_block_reason is not none %}
                    {{event.guest_signup_block_reason | markdown}}
                {% elif g.user is admin or (event.end is not none and event.end > g.now) %}
                    <p><a href="{{(g.view_node / 'guest').url}}">Gast anmelden</a></p>
                {% endif %}
            {% endif %}
            */
        } else if me.is_mensch() {
            @if let Some(nights) = event.nights(&mut transaction).await? {
                @let mut errors = ctx.errors().collect_vec();
                : full_form(uri!(post(new_id)), csrf, html! {
                    //TODO lookup user in dolibarr, only ask for email address if not found
                    : form_field("email", &mut errors, html! {
                        label(for = "email") : "Email-Adresse:";
                        input(type = "email", name = "email", value? = ctx.field_value("email"));
                        label(class = "help") : "(Für die Rechnung.)";
                    });
                    h2 : "Zeitraum";
                    @for (night_idx, night) in iter_date_range(nights).enumerate() {
                        @let field_id = format!("nights[{night_idx}]");
                        : form_field(&field_id, &mut errors, html! {
                            label(for = field_id) {
                                : format_date_range(night, night.succ_opt().expect("reached end of time"));
                                : ":";
                            }
                            input(id = format!("{field_id}-yes"), type = "radio", name = field_id, value = "yes", checked? = ctx.field_value(&*field_id).is_some_and(|val| val == "yes"));
                            label(for = format!("{field_id}-yes")) : "Ja";
                            input(id = format!("{field_id}-maybe"), type = "radio", name = field_id, value = "maybe", checked? = ctx.field_value(&*field_id).is_none_or(|val| val == "maybe"));
                            label(for = format!("{field_id}-maybe")) : "Vielleicht";
                            input(id = format!("{field_id}-no"), type = "radio", name = field_id, value = "no", checked? = ctx.field_value(&*field_id).is_some_and(|val| val == "no"));
                            label(for = format!("{field_id}-no")) : "Nein";
                        });
                    }
                    //TODO include remaining fields from gefolge_web.event.forms.ProfileForm:
                    // section_room, section_room_intro, room, section_travel, section_travel_intro
                    h2 : "Essen";
                    p : "Bitte trage hier Informationen zu deiner Ernährung ein. Diese Daten werden nur der Orga angezeigt.";
                    : form_field("animal_products", &mut errors, html! {
                        label(for = "animal_products") : "tierische Produkte:";
                        input(id = "animal_products-yes", type = "radio", name = "animal_products", value = "yes", checked? = ctx.field_value("animal_products").is_none_or(|val| val == "yes"));
                        label(for = "animal_products-yes") : "uneingeschränkt";
                        input(id = "animal_products-vegetarian", type = "radio", name = "animal_products", value = "vegetarian", checked? = ctx.field_value("animal_products").is_some_and(|val| val == "vegetarian"));
                        label(for = "animal_products-vegetarian") : "vegetarisch";
                        input(id = "animal_products-vegan", type = "radio", name = "animal_products", value = "vegan", checked? = ctx.field_value("animal_products").is_some_and(|val| val == "vegan"));
                        label(for = "animal_products-vegan") : "vegan";
                    });
                    : form_field("allergies", &mut errors, html! {
                        label(for = "allergies") : "Allergien, Unverträglichkeiten:";
                        input(type = "text", name = "allergies", value? = ctx.field_value("allergies"));
                    });
                    //TODO include remaining fields from gefolge_web.event.forms.ProfileForm:
                    // section_programm, section_programm_intro
                    h2 : "Anmeldung";
                    @if let LocationInfo::Known(loc) = &location_info {
                        @if let Some(hausordnung) = &loc.hausordnung {
                            //TODO track last-changed event and hide if current version has already been accepted. Also show last-changed date
                            : form_field("hausordnung", &mut errors, html! {
                                input(type = "checkbox", id = "hausordnung", name = "hausordnung", checked? = ctx.field_value("hausordnung").is_some_and(|value| value == "on"));
                                label(for = "hausordnung") {
                                    : "Ich habe die ";
                                    a(href = hausordnung) : "Hausordnung";
                                    : " zur Kenntnis genommen.";
                                }
                            });
                        }
                    }
                }, errors, "Anmelden");
            } else {
                p : "Coming soon™";
            }
        } else {
            : "Als Gast kannst du dich nicht selbst anmelden.";
        }
        /*
        {% if event.location is not none and event.location.is_online %}
            <p>Es gibt keine Anmeldung für das event insgesamt. Du kannst dich einfach für <a href="{{(g.view_node / 'programm').url}}">Programmpunkte</a> als interessiert eintragen.</p>
        {% else %}
            {% if event.location is none %}
                <div class="alert alert-warning">
                    <strong>Achtung:</strong> Das Haus für dieses event steht noch nicht fest. Je nachdem, wie viele Plätze es hat, kommst du auf die Warteliste. Wenn jemand absagt, rückt der erste Mensch auf der Warteliste nach.
                    {% if event.anzahlung is none or event.anzahlung.value > 0 %}
                        Falls kein Platz für dich frei wird, bekommst du deine Anzahlung natürlich zurück.
                    {% endif %}
                </div>
            {% elif 'capacity' in event.location.data and event.free() <= 0 %}
                <div class="alert alert-warning">
                    <strong>Achtung:</strong> Das Haus ist zumindest zeitweise schon voll. Du kannst dich trotzdem anmelden und kommst dann auf die Warteliste. Wenn jemand absagt, rückt der erste Mensch auf der Warteliste nach. {#TODO check for free nights, adjust message accordingly #}
                    {% if event.anzahlung is none or event.anzahlung.value > 0 %}
                        Falls kein Platz für dich frei wird, bekommst du deine Anzahlung natürlich zurück.
                    {% endif %}
                </div>
            {% endif %}
            {% if event.signup_block_reason is not none %}
                {{event.signup_block_reason | markdown}}
            {% elif event.end is none %}
                <p>Der Termin für dieses event steht noch nicht fest.</p>
            {% elif event.end < g.now %}
                <p>Dieses event ist schon vorbei.</p>
            {% elif event.orga('Abrechnung') is none %}
                <p>Das Orga-Team ist noch nicht vollständig, wir suchen noch jemanden für die Abrechnung. Wenn du das übernehmen möchtest, melde dich bitte bei {{g.admin}}.</p>
            {% elif event.anzahlung is none %}
                <p>{{event.orga('Abrechnung')}} hat die Höhe der Anzahlung noch nicht eingetragen.</p>
            {% elif event.anzahlung.value == 0 %}
                {{gen_form(profile_form, g.view_node.url)}}
            {% elif event.orga('Abrechnung') is treasurer %}
                <p>Die Anmeldung ist mit einer Anzahlung von {{event.anzahlung}} verbunden, die von deinem Guthaben abgezogen wird.</p>
                {% if g.user is admin or g.user is treasurer or g.user.balance >= event.anzahlung %}
                    {{gen_form(profile_form, g.view_node.url)}}
                {% else %}
                    <p>Dein aktuelles Guthaben ist {{g.user.balance}}, es fehlen also noch {{event.anzahlung - g.user.balance}} für die Anzahlung. Auf <a href="{{g.user.profile_url}}">deiner Profilseite</a> steht, wie du Guthaben aufladen kannst.</p>
                {% endif %}
            {% else %}
                {% if 'konto' in event.attendee_data(event.orga('Abrechnung')) %}
                    <p>Um dich anzumelden, überweise bitte die Anzahlung von {{event.anzahlung}} an:</p>
                    <p>
                        {{event.attendee_data(event.orga('Abrechnung'))['konto']['name']}}<br />
                        IBAN: {{event.attendee_data(event.orga('Abrechnung'))['konto']['iban']}}<br />
                        BIC: {{event.attendee_data(event.orga('Abrechnung'))['konto']['bic']}}<br />
                        Verwendungszweck: Anzahlung {{event.event_id}} {{g.user.snowflake}}
                    </p>
                {% else %}
                    <p>Um dich anzumelden, gib bitte {{event.orga('Abrechnung')}} die Anzahlung von {{event.anzahlung}}.</p>
                {% endif %}
                <p>Details zu deiner Anmeldung kannst du eintragen, wenn die Anzahlung angekommen ist. Du wirst dazu auf Discord angepingt.</p> {#TODO reverse signup flow #}
            {% endif %}
        {% endif %}
        {% if g.user is admin or (g.user in event.menschen and event.attendee_data(g.user).get('orga', []) | length > 0) %}
            <h1 id="orga">Orga</h1>
            {% if g.user is admin or event.orga('Abrechnung') == g.user %}
                <h2>Abrechnung</h2>
                {% if event.orga('Abrechnung') is none %}
                    <p>Dieses Event hat noch keine Abrechnungsorga.</p>
                {% elif event.orga('Abrechnung') is treasurer %}
                    <p>Dieses Event läuft über das Guthabensystem.</p>
                {% elif 'konto' in event.attendee_data(event.orga('Abrechnung')) %}
                    <p>Bitte überprüfe regelmäßig dein Konto {{event.attendee_data(g.user)['konto']['iban']}} auf Anzahlungen.</p>
                    {{gen_form(confirm_signup_form, g.view_node.url)}}
                {% else %}
                    <p>Um die Anmeldungen zu eröffnen, gib bitte {{g.admin}} deine Kontodaten.</p>
                {% endif %}
                {% if event.end is not none and event.end <= g.now %}
                    <p>Abrechnungsübersicht coming soon™</p> {#TODO#}
                {% endif %}
            {% endif %}
            {% if g.user is admin or event.orga('Buchung') == g.user %}
                <h2>Buchung</h2>
                {% if event.ausfall > event.anzahlung_total %}
                    {% if event.ausfall_date is none %}
                        <p>Wir können erst buchen, wenn die Ausfallgebühr von {{event.ausfall}} gesichert ist. Dazu fehlen noch {{event.ausfall - event.anzahlung_total}}, also {{((event.ausfall - event.anzahlung_total).value / event.anzahlung.value) | round(0, 'ceil') | int}} Anmeldungen.</p>
                    {% else %}
                        <p>Bis zum {{event.ausfall_date | dmy(event.timezone)}} müssen wir die Ausfallgebühr von {{event.ausfall}} abdecken. Dazu fehlen noch {{event.ausfall - event.anzahlung_total}}, also {{((event.ausfall - event.anzahlung_total).value / event.anzahlung.value) | round(0, 'ceil') | int}} Anmeldungen.</p>
                    {% endif %}
                {% else %}
                    <p>Die Ausfallgebühr von {{event.ausfall}} ist jetzt durch die Anzahlungen abgedeckt. Das Haus kann also gebucht werden.</p>
                {% endif %}
            {% endif %}
            {% if g.user is admin or event.orga('Essen') == g.user %}
                <h2>Essen</h2>
                <p>Trage bitte jeweils als Programmpunktbeschreibung ein, was es an dem Abend gibt.</p>
                <ul>
                    {% for date in event.nights %}
                        {% set date_info = event.essen(date) %}
                        <li>
                            <a href="{{url_for('event_programmpunkt', event=event.event_id, programmpunkt=date_info.url_part)}}">{{date | dm(event.timezone)}}</a>:
                            {% if date_info.description == '' %}
                                noch nicht eingetragen
                            {% else %}
                                {{date_info.description}}
                            {% endif %}
                            (Orga: {% if date_info.orga is none %}noch nicht eingetragen{% else %}{{date_info.orga}}{% endif %})
                            — <a href="{{url_for('event_programmpunkt_edit', event=event.event_id, programmpunkt='abendessen{:%Y-%m-%d}'.format(date))}}">bearbeiten</a>
                        </li>
                    {% endfor %}
                </ul>
            {% endif %}
            {% if g.user is admin or event.orga('Programm') == g.user %}
                <h2>Programm</h2>
                <h3>Programmpunkt erstellen</h3>
                {{gen_form(programm_form, g.view_node.url)}}
            {% endif %}
            {% if g.user is admin or event.orga('Schlüssel') == g.user %}
                <h2>Schlüssel</h2>
                <p>Coming soon™</p> {#TODO#}
            {% endif %}
        {% endif %}
        */ //TODO translate to Horrorshow
    };
    Ok(page(transaction, me, &uri, PageKind::Sub(vec![
        html! {
            : "events";
        },
        html! {
            : event.name(id);
        },
    ]), &event.name(id), content).await?)
}

#[rocket::get("/event/<id>")]
pub(crate) async fn get(config: &State<Config>, db_pool: &State<PgPool>, me: User, uri: Origin<'_>, csrf: Option<CsrfToken>, id: NewId) -> Result<RawHtml<String>, StatusOrError<GetError>> {
    overview_page(config, db_pool, me, uri, csrf.as_ref(), id, &Context::default()).await
}

#[derive(FromForm, CsrfForm)]
pub(crate) struct SignupForm {
    #[field(default = String::new())]
    csrf: String,
    email: String,
    nights: Vec<Going>,
    animal_products: AnimalProducts,
    allergies: String,
    hausordnung: bool,
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum PostError {
    #[error(transparent)] Event(#[from] gefolge_web_lib::event::Error),
    #[error(transparent)] Form(#[from] GetError),
    #[error(transparent)] Serenity(#[from] serenity::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
}

impl<E: Into<PostError>> From<E> for StatusOrError<PostError> {
    fn from(e: E) -> Self {
        Self::Err(e.into())
    }
}

#[rocket::post("/event/<id>", data = "<form>")]
pub(crate) async fn post(config: &State<Config>, discord_ctx: &State<RwFuture<DiscordCtx>>, db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, csrf: Option<CsrfToken>, id: NewId, form: Form<Contextual<'_, SignupForm>>) -> Result<RedirectOrContent, StatusOrError<PostError>> {
    let mut transaction = db_pool.begin().await?;
    let Some(event) = Event::load(&mut *transaction, id.0).await? else { return Err(StatusOrError::Status(Status::NotFound)) };
    let location_info = event.location_info(&mut transaction).await?;
    let mut form = form.into_inner();
    form.verify(&csrf);
    Ok(if let Some(ref value) = form.value {
        if event.attendee(AttendeeId::Discord(me.id)).is_some() {
            form.context.push_error(form::Error::validation("Du bist schon angemeldet."));
        }
        //TODO port more validation from Python
        if value.email.is_empty() {
            form.context.push_error(form::Error::validation("Wir benötigen deine Email-Adresse für die Rechnung.").with_name("email"));
        } else if !regex_is_match!(r"^[a-zA-Z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$", &value.email) { //FROM https://html.spec.whatwg.org/multipage/input.html#valid-e-mail-address
            form.context.push_error(form::Error::validation("Das ist keine Email-Adresse.").with_name("email"));
        }
        if let Some(nights) = event.nights(&mut transaction).await? {
            if value.nights.len().try_into().ok().is_none_or(|num_nights| nights.start.checked_add_days(chrono::Days::new(num_nights)).is_none_or(|end| end != nights.end)) {
                form.context.push_error(form::Error::validation("Falsche Anzahl Übernachtungsinfos im Formular. Bitte melde diesen Fehler im #dev."));
            }
        } else {
            form.context.push_error(form::Error::validation("Die Anmeldungen für dieses Event sind noch nicht offen, weil der Zeitraum noch nicht fest steht."));
        }
        if let LocationInfo::Known(loc) = &location_info {
            if loc.hausordnung.is_some() && !value.hausordnung {
                form.context.push_error(form::Error::validation("Lies bitte die Hausordnung, bevor du dich anmeldest.").with_name("hausordnung"));
            }
        }
        if form.context.errors().next().is_some() {
            RedirectOrContent::Content(overview_page(config, db_pool, me.into(), uri, csrf.as_ref(), id, &form.context).await.map_err(StatusOrError::err_into)?)
        } else {
            let now = MaybeAwareDateTime::Aware(Utc::now());
            let mut menschen = sqlx::query_scalar!(r#"SELECT value -> 'menschen' AS "menschen: Json<Vec<serde_json::Value>>" FROM json_events WHERE id = $1"#, id.0 as _).fetch_one(&mut *transaction).await?.map(|Json(menschen)| menschen).unwrap_or_default();
            menschen.push(json!({ // using untyped JSON here to avoid deleting any data that's not yet deserialized into the Attendee struct
                "id": me.id,
                "email": value.email,
                "food": {
                    "allergies": value.allergies,
                    "animalProducts": value.animal_products,
                },
                "hausordnung": value.hausordnung,
                "nights": iter_date_range(event.nights(&mut transaction).await?.expect("validated")).zip_eq(&value.nights).map(|(night, going)| (night.format("%Y-%m-%d").to_string(), json!({
                    "going": going,
                    "lastUpdated": now,
                    "log": [
                        {
                            "time": now,
                            "going": going,
                        },
                    ],
                }))).collect::<serde_json::Map<_, _>>(),
                "signup": now,
            }));
            sqlx::query!("UPDATE json_events SET value = JSONB_SET(value, '{menschen}', $1) WHERE id = $2", Json(menschen) as _, id.0 as _).execute(&mut *transaction).await?;
            if let Some(role) = event.discord_role() {
                GEFOLGE.member(&*discord_ctx.read().await, me.id).await?.add_role(&*discord_ctx.read().await, role).await?;
            }
            let mut content = MessageBuilder::default();
            content.mention(&me.id);
            content.push(": du bist jetzt für ");
            content.push(event.name(id.0));
            content.push(" angemeldet. Fülle bitte bei Gelegenheit noch dein Profil auf <https://gefolge.org/event/"); //TODO remove this part once signup form is fully ported
            content.push(id.0.to_string());
            content.push("/me/edit> aus. Außerdem kannst du dich auf <https://gefolge.org/event/");
            content.push(id.0.to_string());
            content.push("/programm> für Programmpunkte als interessiert eintragen");
            event.discord_channel().say(&*discord_ctx.read().await, content.build()).await?;
            transaction.commit().await?;
            RedirectOrContent::Redirect(Redirect::to(format!("/event/{}/mensch/{}", id.0, me.id)))
        }
    } else {
        RedirectOrContent::Content(overview_page(config, db_pool, me.into(), uri, csrf.as_ref(), id, &form.context).await.map_err(StatusOrError::err_into)?)
    })
}

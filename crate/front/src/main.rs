#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    std::{
        collections::HashMap,
        sync::Arc,
        time::Duration,
    },
    base64::engine::{
        Engine as _,
        general_purpose::STANDARD as BASE64,
    },
    chrono::prelude::*,
    itertools::Itertools as _,
    rocket::{
        Responder,
        Rocket,
        State,
        config::SecretKey,
        data::{
            Limits,
            ToByteUnit as _,
        },
        fs::FileServer,
        http::{
            Header,
            Status,
            uri::{
                Segments,
                fmt::Path,
            },
        },
        request::{
            self,
            FromRequest,
            Request,
        },
        response::content::{
            RawHtml,
            RawText,
        },
        uri,
    },
    rocket_oauth2::{
        OAuth2,
        OAuthConfig,
    },
    rocket_util::{
        Doctype,
        Origin,
        Response,
        ToHtml,
        html,
    },
    sqlx::{
        PgPool,
        postgres::PgConnectOptions,
        types::Json,
    },
    tokio::sync::RwLock,
    url::Url,
    gefolge_web_lib::event::Event,
    crate::{
        auth::DiscordUser,
        config::Config,
        time::format_date_range,
        user::{
            User,
            html_mention,
        },
    },
};

include!(concat!(env!("OUT_DIR"), "/static_files.rs"));

mod auth;
mod config;
mod event;
mod time;
mod user;
mod websocket;

#[derive(Default)]
enum PageKind {
    Splash,
    Index,
    #[default]
    Other,
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
enum PageError {
    #[error(transparent)] Sql(#[from] sqlx::Error),
}

async fn page(db_pool: &PgPool, me: Option<DiscordUser>, uri: &Origin<'_>, kind: PageKind, title: &str, content: impl ToHtml) -> Result<RawHtml<String>, PageError> {
    let footer = html! {
        footer {
            p {
                : "hosted by ";
                a(href = "https://fenhl.net/") : "Fenhl"; //TODO link to Fenhl's profile if user can view it
                : " • ";
                a(href = "https://fenhl.net/disc") : "disclaimer";
                : " • ";
                a(href = "https://github.com/dasgefolge/gefolge.org") : "source code";
            }
            p {
                : "Bild ";
                a(href = "https://creativecommons.org/licenses/by-sa/2.5/deed.en") : "CC-BY-SA 2.5";
                : " Ronald Preuss, aus Wikimedia Commons (";
                a(href = "https://commons.wikimedia.org/wiki/File:Ritter_gefolge.jpg") : "Link";
                : ")";
            }
        }
    };
    Ok(html! {
        : Doctype;
        html {
            head {
                meta(charset = "utf-8");
                title : title;
                meta(name = "viewport", content = "width=device-width, initial-scale=1, shrink-to-fit=no");
                meta(name = "description", content = "Das Gefolge");
                meta(name = "author", content = "Fenhl & contributors");
                link(rel = "preconnect", href = "https://fonts.googleapis.com");
                link(rel = "preconnect", href = "https://fonts.gstatic.com", crossorigin);
                //TODO at which size should the entire logo be displayed?
                link(rel = "icon", sizes = "16x16", type = "image/png", href = static_url!("favicon-16.png"));
                link(rel = "icon", sizes = "32x32", type = "image/png", href = static_url!("favicon-32.png"));
                link(rel = "icon", sizes = "64x64", type = "image/png", href = static_url!("favicon-64.png"));
                link(rel = "icon", sizes = "128x128", type = "image/png", href = static_url!("favicon-128.png"));
                link(rel = "icon", sizes = "256x256", type = "image/png", href = static_url!("favicon-256.png"));
                link(rel = "stylesheet", href = static_url!("riir.css"));
                link(rel = "stylesheet", href = static_url!("dejavu-sans.css"));
                link(rel = "stylesheet", href = "https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;700&display=swap");
                script(defer, src = static_url!("common.js"));
            }
            @if let PageKind::Splash = kind {
                body(class = "splash") {
                    img(src = static_url!("gefolge.png"));
                    main : content;
                    : footer;
                }
            } else {
                body {
                    div {
                        nav(class? = matches!(kind, PageKind::Index).then_some("index")) {
                            a(class = "nav") {
                                img(class = "logo", src = static_url!("gefolge.png"));
                                h1 : "Das Gefolge";
                            }
                            div(id = "login") {
                                @if let Some(me) = me {
                                    @let user = User::from_id(db_pool, me.id).await?;
                                    @let is_mensch_or_guest = user.as_ref().map_or(false, User::is_mensch_or_guest);
                                    : "Angemeldet als ";
                                    : html_mention(db_pool, me.id).await?;
                                    br;
                                    @if is_mensch_or_guest {
                                        a(href = format!("/mensch/{}/edit", me.id)) : "Einstellungen";
                                        : " • ";
                                    }
                                    a(href = uri!(auth::logout).to_string()) : "Abmelden";
                                } else {
                                    a(href = uri!(auth::discord_login(Some(uri))).to_string()) : "Mit Discord anmelden";
                                }
                            }
                        }
                        main : content;
                    }
                    : footer;
                }
            }
        }
    })
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
enum IndexError {
    #[error(transparent)] Event(#[from] gefolge_web_lib::event::Error),
    #[error(transparent)] Page(#[from] PageError),
    #[error(transparent)] Sql(#[from] sqlx::Error),
}

#[rocket::get("/")]
async fn index(db_pool: &State<PgPool>, me: Option<DiscordUser>, uri: Origin<'_>) -> Result<RawHtml<String>, IndexError> {
    Ok(if let Some(DiscordUser { id }) = me {
        let now = Utc::now();
        let mut transaction = db_pool.begin().await?;
        let mut upcoming_events = Vec::default();
        for row in sqlx::query!(r#"SELECT id, value AS "value: Json<Event>" FROM json_events"#).fetch_all(&mut *transaction).await? {
            let start = row.value.0.start(&mut *transaction).await?;
            let end = row.value.0.end(&mut *transaction).await?;
            if end.map_or(true, |end| end > now) {
                upcoming_events.push((row.id, start, end, row.value.0));
            }
        }
        upcoming_events.sort_unstable_by(|(id1, start1, _, _), (id2, start2, _, _)|
            start1.is_none().cmp(&start2.is_none()) // nulls last
                .then_with(|| start1.cmp(start2))
                .then_with(|| id1.cmp(id2))
        );
        let mut ongoing_events = Vec::default();
        for (id, start, end, event) in upcoming_events.drain(..).collect_vec() {
            if start.map_or(true, |start| start <= now) { &mut ongoing_events } else { &mut upcoming_events }.push((id, start, end, event));
        }
        let content = html! {
            @let user = User::from_id(db_pool, id).await?;
            @let is_mensch_or_guest = user.as_ref().map_or(false, User::is_mensch_or_guest);
            @if is_mensch_or_guest {
                @let viewer_data = user.as_ref().expect("just checked (is_mensch_or_guest)").data(db_pool).await?;
                p {
                    a(href = "/api") : "API";
                    : " • ";
                    a(href = "/event") : "events";
                    : " • ";
                    a(href = "/games") : "Spiele";
                    : " • ";
                    a(href = "/mensch") : "Menschen und Gäste";
                    : " • ";
                    a(href = "/wiki") : "wiki";
                }
                h1 : "Events";
                @if !ongoing_events.is_empty() {
                    h2 : "laufende Events";
                    ul {
                        @for (id, start, end, event) in ongoing_events {
                            li {
                                : event.to_html(&id);
                                @if let (Some(start), Some(end)) = (start, end) {
                                    : " (";
                                    : format_date_range(&viewer_data, start, end);
                                    : ")";
                                }
                            }
                        }
                    }
                }
                @if !upcoming_events.is_empty() {
                    h2 : "zukünftige Events";
                    ul {
                        @for (id, start, end, event) in upcoming_events {
                            li {
                                : event.to_html(&id);
                                @if let (Some(start), Some(end)) = (start, end) {
                                    : " (";
                                    : format_date_range(&viewer_data, start, end);
                                    : ")";
                                }
                            }
                        }
                    }
                }
                p {
                    a(href = "/event") : "vergangene Events";
                }
            } else if user.is_some() {
                p : "Dein Account wurde noch nicht freigeschaltet. Stelle dich doch bitte einmal kurz im ";
                : "#general"; //TODO link
                : " vor und warte, bis ein admin dich bestätigt.";
            } else {
                p : "Du hast dich erfolgreich mit Discord angemeldet, bist aber nicht im Gefolge Discord server.";
            }
        };
        transaction.commit().await?; //TODO move transaction into `page`?
        page(db_pool, me, &uri, PageKind::Index, "Das Gefolge", content).await?
    } else {
        page(db_pool, me, &uri, PageKind::Splash, "Das Gefolge", html! {
            p {
                : "Das ";
                strong : "Gefolge";
                : " ist eine lose Gruppe von Menschen, die sich größtenteils über die ";
                a(href = "https://mensa.de/kiju/camps") : "Mensa Juniors Camps";
                : " zwischen ca. 2008 und 2012 kennen.";
            }
            p {
                : "Wir haben einen ";
                a(href = "https://discord.com/") : "Discord";
                : " server (Einladung für Gefolgemenschen auf Anfrage).";
            }
            p {
                : "Wenn du schon auf dem Discord server bist, kannst du dich ";
                a(href = uri!(auth::discord_login(Some(uri!(index)))).to_string()) : "hier mit Discord anmelden";
                : ", um Zugriff auf die internen Bereiche dieser website zu bekommen, z.B. unser wiki und die Anmeldung für Silvester.";
            }
        }).await?
    })
}

struct ProxyHttpClient(reqwest::Client);

struct Headers(reqwest::header::HeaderMap);

#[rocket::async_trait]
impl<'r> FromRequest<'r> for Headers {
    type Error = FlaskProxyError;

    async fn from_request(req: &'r Request<'_>) -> request::Outcome<Self, Self::Error> {
        let mut reqwest_headers = reqwest::header::HeaderMap::default();
        for header in req.headers().iter() {
            reqwest_headers.append(
                match header.name.as_str().parse::<reqwest::header::HeaderName>() {
                    Ok(name) => name,
                    Err(e) => return request::Outcome::Error((Status::InternalServerError, e.into())),
                },
                match header.value.parse::<reqwest::header::HeaderValue>() {
                    Ok(value) => value,
                    Err(e) => return request::Outcome::Error((Status::InternalServerError, e.into())),
                },
            );
        }
        request::Outcome::Success(Self(reqwest_headers))
    }
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
enum FlaskProxyError {
    #[error(transparent)] InvalidHeaderName(#[from] reqwest::header::InvalidHeaderName),
    #[error(transparent)] InvalidHeaderValue(#[from] reqwest::header::InvalidHeaderValue),
    #[error(transparent)] Reqwest(#[from] reqwest::Error),
    #[error(transparent)] Url(#[from] url::ParseError),
    #[error("internal server error in proxied Flask application:\n{0}")]
    InternalServerError(String),
}

fn proxy_headers(headers: Headers, discord_user: Option<DiscordUser>) -> Result<reqwest::header::HeaderMap, FlaskProxyError> {
    let mut headers = headers.0;
    headers.insert(reqwest::header::HOST, reqwest::header::HeaderValue::from_static("gefolge.org"));
    headers.insert(reqwest::header::HeaderName::from_static("x-forwarded-proto"), reqwest::header::HeaderValue::from_static("https"));
    if let Some(discord_user) = discord_user {
        headers.insert(reqwest::header::HeaderName::from_static("x-gefolge-authorized-discord-id"), discord_user.id.to_string().parse()?);
    } else {
        headers.remove(reqwest::header::HeaderName::from_static("x-gefolge-authorized-discord-id"));
    }
    Ok(headers)
}

#[derive(Responder)]
enum FlaskProxyResponse {
    Proxied(Response<reqwest::Response>),
    Status(Status),
    #[response(status = 401)]
    Authenticate {
        inner: (),
        www_authenticate: Header<'static>,
    },
}

#[rocket::get("/api")]
async fn flask_proxy_get_api(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers) -> Result<FlaskProxyResponse, FlaskProxyError> {
    if me.is_none() {
        return Ok(FlaskProxyResponse::Authenticate {
            inner: (),
            www_authenticate: Header::new("WWW-Authenticate", "Basic realm=\"Gefolge\", charset=\"UTF-8\""),
        })
    }
    let mut url = Url::parse("http://127.0.0.1:18822/api")?;
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.get(url).headers(proxy_headers(headers, me)?).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(FlaskProxyError::InternalServerError(response.text().await?))
    }
    Ok(FlaskProxyResponse::Proxied(Response(response)))
}

#[rocket::get("/api/<path..>")]
async fn flask_proxy_get_api_children(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>) -> Result<FlaskProxyResponse, FlaskProxyError> {
    if me.is_none() {
        return Ok(FlaskProxyResponse::Authenticate {
            inner: (),
            www_authenticate: Header::new("WWW-Authenticate", "Basic realm=\"Gefolge\", charset=\"UTF-8\""),
        })
    }
    let mut url = Url::parse("http://127.0.0.1:18822/api")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.get(url).headers(proxy_headers(headers, me)?).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(FlaskProxyError::InternalServerError(response.text().await?))
    }
    Ok(FlaskProxyResponse::Proxied(Response(response)))
}

#[rocket::get("/<path..>")]
async fn flask_proxy_get(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>) -> Result<FlaskProxyResponse, FlaskProxyError> {
    if Segments::<Path>::get(&path, 0).map_or(true, |prefix| !matches!(prefix, "event" | "games" | "me" | "mensch" | "wiki")) {
        // only forward the directories that are actually served by the proxy to prevent internal server errors on malformed requests from spambots
        return Ok(FlaskProxyResponse::Status(Status::NotFound))
    }
    let mut url = Url::parse("http://127.0.0.1:18822/")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.get(url).headers(proxy_headers(headers, me)?).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(FlaskProxyError::InternalServerError(response.text().await?))
    }
    Ok(FlaskProxyResponse::Proxied(Response(response)))
}

#[rocket::post("/<path..>", data = "<data>")]
async fn flask_proxy_post(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>, data: Vec<u8>) -> Result<FlaskProxyResponse, FlaskProxyError> {
    if Segments::<Path>::get(&path, 0).map_or(true, |prefix| !matches!(prefix, "event" | "games" | "me" | "mensch" | "wiki")) {
        // only forward the directories that are actually served by the proxy to prevent internal server errors on malformed requests from spambots
        return Ok(FlaskProxyResponse::Status(Status::NotFound))
    }
    let mut url = Url::parse("http://127.0.0.1:18822/")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.post(url).headers(proxy_headers(headers, me)?).body(data).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(FlaskProxyError::InternalServerError(response.text().await?))
    }
    Ok(FlaskProxyResponse::Proxied(Response(response)))
}

#[rocket::get("/robots.txt")]
async fn robots_txt() -> RawText<&'static str> {
    RawText("User-agent: *\nDisallow: /static/\n")
}

#[rocket::catch(400)]
async fn bad_request(request: &Request<'_>) -> Result<RawHtml<String>, PageError> {
    let db_pool = request.guard::<&State<PgPool>>().await.expect("missing database pool");
    let me = request.guard::<DiscordUser>().await.succeeded();
    let uri = request.guard::<Origin<'_>>().await.succeeded().unwrap_or_else(|| Origin(uri!(index)));
    page(db_pool, me, &uri, PageKind::default(), "Bad Request — Das Gefolge", html! {
        h1 : "Fehler 400: Bad Request";
        p : "Anmeldung fehlgeschlagen. Falls du Hilfe brauchst, kannst du auf Discord im #dev nachfragen.";
        p {
            a(href = uri!(index).to_string()) : "Zurück zur Hauptseite von gefolge.org";
        }
    }).await
}

#[rocket::catch(404)]
async fn not_found(request: &Request<'_>) -> Result<RawHtml<String>, PageError> {
    let db_pool = request.guard::<&State<PgPool>>().await.expect("missing database pool");
    let me = request.guard::<DiscordUser>().await.succeeded();
    let uri = request.guard::<Origin<'_>>().await.succeeded().unwrap_or_else(|| Origin(uri!(index)));
    page(db_pool, me, &uri, PageKind::default(), "Not Found — Das Gefolge", html! {
        h1 : "Fehler 404: Not Found";
        p : "Diese Seite existiert nicht.";
        p {
            a(href = uri!(index).to_string()) : "Zurück zur Hauptseite von gefolge.org";
        }
    }).await
}

#[rocket::catch(500)]
async fn internal_server_error(request: &Request<'_>) -> Result<RawHtml<String>, PageError> {
    let db_pool = request.guard::<&State<PgPool>>().await.expect("missing database pool");
    let me = request.guard::<DiscordUser>().await.succeeded();
    let uri = request.guard::<Origin<'_>>().await.succeeded().unwrap_or_else(|| Origin(uri!(index)));
    let is_reported = wheel::night_report("/net/gefolge/error", Some("internal server error")).await.is_ok();
    page(db_pool, me, &uri, PageKind::default(), "Internal Server Error — Das Gefolge", html! {
        h1 : "Fehler 500: Internal Server Error";
        p {
            : "Beim Laden dieser Seite ist ein Fehler aufgetreten. ";
            @if is_reported {
                : "Fenhl wurde informiert.";
            } else {
                : "Bitte melde diesen Fehler im ";
                a(href = "https://discord.com/channels/355761290809180170/397832322432499712") : "#dev";
                : ".";
            }
        }
        p {
            a(href = uri!(index).to_string()) : "Zurück zur Hauptseite von gefolge.org";
        }
    }).await
}

#[rocket::catch(default)]
async fn fallback_catcher(status: Status, request: &Request<'_>) -> Result<RawHtml<String>, PageError> {
    let db_pool = request.guard::<&State<PgPool>>().await.expect("missing database pool");
    let me = request.guard::<DiscordUser>().await.succeeded();
    let uri = request.guard::<Origin<'_>>().await.succeeded().unwrap_or_else(|| Origin(uri!(index)));
    let is_reported = wheel::night_report("/net/gefolge/error", Some("responding with unexpected HTTP status code")).await.is_ok();
    page(db_pool, me, &uri, PageKind::default(), &format!("{} — Das Gefolge", status.reason_lossy()), html! {
        h1 {
            : "Fehler ";
            : status.code;
            : ": ";
            : status.reason_lossy();
        }
        p {
            : "Beim Laden dieser Seite ist ein Fehler aufgetreten. ";
            @if is_reported {
                : "Fenhl wurde informiert.";
            } else {
                : "Bitte melde diesen Fehler im ";
                a(href = "https://discord.com/channels/355761290809180170/397832322432499712") : "#dev";
                : ".";
            }
        }
        p {
            a(href = uri!(index).to_string()) : "Zurück zur Hauptseite von gefolge.org";
        }
    }).await
}

#[derive(Debug, thiserror::Error)]
enum MainError {
    #[error(transparent)] Base64(#[from] base64::DecodeError),
    #[error(transparent)] Config(#[from] config::Error),
    #[error(transparent)] Reqwest(#[from] reqwest::Error),
    #[error(transparent)] Rocket(#[from] rocket::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
}

#[wheel::main(rocket, debug)]
async fn main() -> Result<(), MainError> {
    let config = Config::load().await?;
    let http_client = reqwest::Client::builder()
        .user_agent(concat!("GefolgeWeb/", env!("CARGO_PKG_VERSION")))
        .timeout(Duration::from_secs(30))
        .use_rustls_tls()
        .hickory_dns(true)
        .https_only(true)
        .build()?;
    let proxy_http_client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("GefolgeWeb/", env!("CARGO_PKG_VERSION")))
        .timeout(Duration::from_secs(90))
        .build()?;
    let Rocket { .. } = rocket::custom(rocket::Config {
        secret_key: SecretKey::from(&BASE64.decode(&config.secret_key)?),
        log_level: rocket::config::LogLevel::Critical,
        port: 24817,
        limits: Limits::default()
            .limit("bytes", 2.mebibytes()), // for proxied wiki edits
        ..rocket::Config::default()
    })
    .mount("/", rocket::routes![
        index,
        flask_proxy_get,
        flask_proxy_get_api,
        flask_proxy_get_api_children,
        flask_proxy_post,
        robots_txt,
        auth::discord_callback,
        auth::discord_login,
        auth::logout,
        websocket::websocket,
    ])
    .mount("/static", FileServer::new("assets/static", rocket::fs::Options::None))
    .register("/", rocket::catchers![
        bad_request,
        not_found,
        internal_server_error,
        fallback_catcher,
    ])
    .attach(OAuth2::<auth::Discord>::custom(rocket_oauth2::HyperRustlsAdapter::default(), OAuthConfig::new(
        rocket_oauth2::StaticProvider { //TODO use built-in constant once https://github.com/jebrosen/rocket_oauth2/pull/42 is released
            auth_uri: "https://discord.com/oauth2/authorize".into(),
            token_uri: "https://discord.com/api/oauth2/token".into(),
        },
        config.discord.client_id.to_string(),
        config.discord.client_secret.to_string(),
        Some(uri!("https://gefolge.org", auth::discord_callback).to_string()),
    )))
    .manage(PgPool::connect_with(PgConnectOptions::default().username("fenhl").database("gefolge").application_name("gefolge-web")).await?)
    .manage(http_client)
    .manage(ProxyHttpClient(proxy_http_client))
    .manage(Arc::<RwLock<HashMap<u64, ricochet_robots_websocket::Lobby<User>>>>::default())
    .launch().await?;
    Ok(())
}

#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    std::time::Duration,
    base64::engine::{
        Engine as _,
        general_purpose::STANDARD as BASE64,
    },
    rocket::{
        Rocket,
        State,
        config::SecretKey,
        http::{
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
        uri,
    },
    rocket_oauth2::{
        OAuth2,
        OAuthConfig,
    },
    rocket_util::{
        Origin,
        Response,
    },
    url::Url,
    crate::{
        auth::DiscordUser,
        config::Config,
    },
};

mod auth;
mod config;

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
                    Err(e) => return request::Outcome::Failure((Status::InternalServerError, e.into())),
                },
                match header.value.parse::<reqwest::header::HeaderValue>() {
                    Ok(value) => value,
                    Err(e) => return request::Outcome::Failure((Status::InternalServerError, e.into())),
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

#[rocket::get("/")]
async fn index(proxy_http_client: &State<ProxyHttpClient>, discord_user: Option<DiscordUser>, headers: Headers) -> Result<Response<reqwest::Response>, FlaskProxyError> {
    let url = Url::parse("http://127.0.0.1:18822/")?;
    Ok(Response(proxy_http_client.0.get(url).headers(proxy_headers(headers, discord_user)?).send().await?))
}

#[rocket::get("/<path..>")]
async fn flask_proxy_get(proxy_http_client: &State<ProxyHttpClient>, discord_user: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>) -> Result<Response<reqwest::Response>, FlaskProxyError> {
    let mut url = Url::parse("http://127.0.0.1:18822/")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    Ok(Response(proxy_http_client.0.get(url).headers(proxy_headers(headers, discord_user)?).send().await?))
}

#[rocket::post("/<path..>", data = "<data>")]
async fn flask_proxy_post(proxy_http_client: &State<ProxyHttpClient>, discord_user: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>, data: Vec<u8>) -> Result<Response<reqwest::Response>, FlaskProxyError> {
    let mut url = Url::parse("http://127.0.0.1:18822/")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    Ok(Response(proxy_http_client.0.post(url).headers(proxy_headers(headers, discord_user)?).body(data).send().await?))
}

#[derive(Debug, thiserror::Error)]
enum Error {
    #[error(transparent)] Base64(#[from] base64::DecodeError),
    #[error(transparent)] Config(#[from] config::Error),
    #[error(transparent)] Reqwest(#[from] reqwest::Error),
    #[error(transparent)] Rocket(#[from] rocket::Error),
}

#[wheel::main(rocket, debug)]
async fn main() -> Result<(), Error> {
    let config = Config::load().await?;
    let http_client = reqwest::Client::builder()
        .user_agent(concat!("GefolgeWeb/", env!("CARGO_PKG_VERSION")))
        .timeout(Duration::from_secs(30))
        .use_rustls_tls()
        .trust_dns(true)
        .https_only(true)
        .build()?;
    let proxy_http_client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("GefolgeWeb/", env!("CARGO_PKG_VERSION")))
        .timeout(Duration::from_secs(30))
        .build()?;
    let Rocket { .. } = rocket::custom(rocket::Config {
        secret_key: SecretKey::from(&BASE64.decode(&config.secret_key)?),
        log_level: rocket::config::LogLevel::Critical,
        port: 24817,
        ..rocket::Config::default()
    })
    .mount("/", rocket::routes![
        index,
        flask_proxy_get,
        flask_proxy_post,
        auth::discord_callback,
        auth::discord_login,
        auth::logout,
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
    .manage(http_client)
    .manage(ProxyHttpClient(proxy_http_client))
    .launch().await?;
    Ok(())
}

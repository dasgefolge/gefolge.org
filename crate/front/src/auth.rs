use {
    std::time::Duration,
    futures::future::TryFutureExt as _,
    rocket::{
        State,
        http::{
            Cookie,
            CookieJar,
            SameSite,
            Status,
            ext::IntoOwned as _,
        },
        outcome::Outcome,
        request::{
            self,
            FromRequest,
            Request,
        },
        response::Redirect,
        uri,
    },
    rocket_basicauth::BasicAuth,
    rocket_oauth2::{
        OAuth2,
        TokenResponse,
    },
    rocket_util::Origin,
    serde::Deserialize,
    serenity::model::prelude::*,
    sqlx::{
        PgPool,
        types::Json,
    },
    wheel::traits::ReqwestResponseExt as _,
};

macro_rules! guard_try {
    ($res:expr) => {
        match $res {
            Ok(x) => x,
            Err(e) => return Outcome::Error((Status::InternalServerError, e.into())),
        }
    };
}

pub(crate) enum Discord {}

#[derive(Debug, thiserror::Error)]
pub(crate) enum UserFromRequestError {
    #[error(transparent)] BasicAuth(#[from] rocket_basicauth::BasicAuthError),
    #[error(transparent)] OAuth(#[from] rocket_oauth2::Error),
    #[error(transparent)] Reqwest(#[from] reqwest::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Time(#[from] rocket::time::error::ConversionRange),
    #[error(transparent)] TryFromInt(#[from] std::num::TryFromIntError),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[error("invalid API key")]
    ApiKey,
    #[error("HTTP Basic auth with username not matching \"api\"")]
    BasicUsername,
    #[error("missing discord_token cookie")]
    Cookie,
    #[error("missing database connection")]
    Database,
    #[error("missing HTTP client")]
    HttpClient,
}

async fn handle_discord_token_response(http_client: &reqwest::Client, cookies: &CookieJar<'_>, token: &TokenResponse<Discord>) -> Result<DiscordUser, UserFromRequestError> {
    let mut cookie = Cookie::build(("discord_token", token.access_token().to_owned()))
        .same_site(SameSite::Lax);
    if let Some(expires_in) = token.expires_in() {
        cookie = cookie.max_age(Duration::from_secs(u64::try_from(expires_in)?.saturating_sub(60)).try_into()?);
    }
    cookies.add_private(cookie);
    if let Some(refresh_token) = token.refresh_token() {
        cookies.add_private(Cookie::build(("discord_refresh_token", refresh_token.to_owned()))
            .same_site(SameSite::Lax)
            .permanent());
    }
    Ok(http_client.get("https://discord.com/api/v10/users/@me")
        .bearer_auth(token.access_token())
        .send().await?
        .detailed_error_for_status().await?
        .json_with_text_in_error().await?)
}

#[derive(Deserialize)]
pub(crate) struct DiscordUser {
    pub(crate) id: UserId,
}

#[rocket::async_trait]
impl<'r> FromRequest<'r> for DiscordUser {
    type Error = UserFromRequestError;

    async fn from_request(req: &'r Request<'_>) -> request::Outcome<Self, UserFromRequestError> {
        let outcome = match req.guard().await {
            Outcome::Success(BasicAuth { username, password }) if username == "api" => match req.guard::<&State<PgPool>>().await {
                Outcome::Success(pool) => if let Some(id) = guard_try!(sqlx::query_scalar!("SELECT id FROM json_user_data WHERE value -> 'apiKey' = $1", Json(password) as _).fetch_optional(&**pool).await) {
                    Outcome::Success(DiscordUser { id: UserId::from(id as u64) })
                } else {
                    Outcome::Error((Status::Unauthorized, UserFromRequestError::ApiKey))
                },
                Outcome::Error((status, ())) => Outcome::Error((status, UserFromRequestError::Database)),
                Outcome::Forward(status) => Outcome::Forward(status),
            },
            Outcome::Success(_) => Outcome::Error((Status::Unauthorized, UserFromRequestError::BasicUsername)),
            Outcome::Error((status, e)) => Outcome::Error((status, e.into())),
            Outcome::Forward(_) => match req.guard::<&CookieJar<'_>>().await {
                Outcome::Success(cookies) => match req.guard::<&State<reqwest::Client>>().await {
                    Outcome::Success(http_client) => if let Some(token) = cookies.get_private("discord_token") {
                        match http_client.get("https://discord.com/api/v10/users/@me")
                            .bearer_auth(token.value())
                            .send()
                            .err_into::<UserFromRequestError>()
                            .and_then(|response| response.detailed_error_for_status().err_into())
                            .await
                        {
                            Ok(response) => Outcome::Success(guard_try!(response.json_with_text_in_error().await)),
                            Err(e) => Outcome::Error((Status::BadGateway, e.into())),
                        }
                    } else if let Some(token) = cookies.get_private("discord_refresh_token") {
                        match req.guard::<OAuth2<Discord>>().await {
                            Outcome::Success(oauth) => Outcome::Success(guard_try!(handle_discord_token_response(http_client, cookies, &guard_try!(oauth.refresh(token.value()).await)).await)),
                            Outcome::Error((status, ())) => Outcome::Error((status, UserFromRequestError::Cookie)),
                            Outcome::Forward(status) => Outcome::Forward(status),
                        }
                    } else {
                        Outcome::Error((Status::Unauthorized, UserFromRequestError::Cookie))
                    },
                    Outcome::Error((status, ())) => Outcome::Error((status, UserFromRequestError::HttpClient)),
                    Outcome::Forward(status) => Outcome::Forward(status),
                },
                Outcome::Error((_, never)) => match never {},
                Outcome::Forward(status) => Outcome::Forward(status),
            },
        };
        if let Outcome::Success(found_user) = outcome {
            match req.guard::<&State<PgPool>>().await {
                Outcome::Success(pool) => if let Some(id) = guard_try!(sqlx::query_scalar!("SELECT view_as FROM view_as WHERE viewer = $1", i64::from(found_user.id)).fetch_optional(&**pool).await) {
                    Outcome::Success(DiscordUser { id: UserId::from(id as u64) })
                } else {
                    Outcome::Success(found_user)
                },
                Outcome::Error((status, ())) => Outcome::Error((status, UserFromRequestError::Database)),
                Outcome::Forward(status) => Outcome::Forward(status),
            }
        } else {
            outcome
        }
    }
}

#[rocket::get("/login/discord?<redirect_to>")]
pub(crate) fn discord_login(oauth: OAuth2<Discord>, cookies: &CookieJar<'_>, redirect_to: Option<Origin<'_>>) -> Result<Redirect, rocket_util::Error<rocket_oauth2::Error>> {
    if let Some(redirect_to) = redirect_to {
        if redirect_to.0.path() != uri!(discord_callback).path() { // prevent showing login error page on login success
            cookies.add(Cookie::build(("redirect_to", redirect_to)).same_site(SameSite::Lax));
        }
    }
    oauth.get_redirect(cookies, &["identify"]).map_err(rocket_util::Error)
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum DiscordCallbackError {
    #[error(transparent)] UserFromRequest(#[from] UserFromRequestError),
}

#[rocket::get("/login/discord/authorized")]
pub(crate) async fn discord_callback(http_client: &State<reqwest::Client>, token: TokenResponse<Discord>, cookies: &CookieJar<'_>) -> Result<Redirect, DiscordCallbackError> {
    handle_discord_token_response(http_client, cookies, &token).await?;
    let redirect_uri = cookies.get("redirect_to").and_then(|cookie| rocket::http::uri::Origin::try_from(cookie.value()).ok()).map_or_else(|| uri!(crate::index), |uri| uri.into_owned());
    Ok(Redirect::to(redirect_uri))
}

#[rocket::get("/logout")]
pub(crate) fn logout(cookies: &CookieJar<'_>) -> Redirect {
    cookies.remove_private(Cookie::from("discord_token"));
    cookies.remove_private(Cookie::from("discord_refresh_token"));
    Redirect::to(uri!(crate::index))
}

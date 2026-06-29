use {
    rocket::{
        State,
        http::{
            Cookie,
            CookieJar,
            SameSite,
            ext::IntoOwned as _,
        },
        response::Redirect,
        uri,
    },
    rocket_oauth2::{
        OAuth2,
        TokenResponse,
    },
    rocket_util::Origin,
    gefolge_web_lib::auth::{
        Discord,
        UserFromRequestError,
        handle_discord_token_response,
    },
};

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

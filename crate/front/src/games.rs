use {
    rocket::{
        State,
        http::uri::{
            Segments,
            fmt::Path,
        },
        response::content::RawHtml,
        uri,
    },
    rocket_util::{
        Origin,
        Response,
        html,
    },
    sqlx::PgPool,
    url::Url,
    crate::{
        Headers,
        PageError,
        PageKind,
        ProxyError,
        ProxyHttpClient,
        ProxyResponse,
        auth::DiscordUser,
        page,
        proxy_headers,
        user::Mensch,
    },
};

#[rocket::get("/games")]
pub(crate) async fn index(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>) -> Result<RawHtml<String>, PageError> {
    page(db_pool.begin().await?, me, &uri, PageKind::Sub(vec![
        html! {
            : "Spiele";
        },
    ]), "Spiele — Das Gefolge", html! {
        h1 : "Spiele";
        ul {
            li {
                a(href = "/games/rr") : "Rasende Roboter";
            }
            li {
                a(href = "/games/space-alert") : "Space Alert";
            }
            li {
                a(href = uri!(werewolf_proxy_get_index)) : "Werwölfe";
            }
        }
    }).await
}

#[rocket::get("/games/werewolf")]
pub(crate) async fn werewolf_proxy_get_index(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers) -> Result<ProxyResponse, ProxyError> {
    let mut url = Url::parse("http://127.0.0.1:18831/games/werewolf")?;
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.get(url).headers(proxy_headers(headers, me)?).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(ProxyError::InternalServerError(response.text().await?))
    }
    Ok(ProxyResponse::Proxied(Response(response)))
}

#[rocket::get("/games/werewolf/<path..>")]
pub(crate) async fn werewolf_proxy_get_children(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>) -> Result<ProxyResponse, ProxyError> {
    let mut url = Url::parse("http://127.0.0.1:18831/games/werewolf")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.get(url).headers(proxy_headers(headers, me)?).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(ProxyError::InternalServerError(response.text().await?))
    }
    Ok(ProxyResponse::Proxied(Response(response)))
}

#[rocket::post("/games/werewolf/<path..>", data = "<data>")]
pub(crate) async fn werewolf_proxy_post(proxy_http_client: &State<ProxyHttpClient>, me: Option<DiscordUser>, origin: Origin<'_>, headers: Headers, path: Segments<'_, Path>, data: Vec<u8>) -> Result<ProxyResponse, ProxyError> {
    let mut url = Url::parse("http://127.0.0.1:18831/games/werewolf")?;
    url.path_segments_mut().expect("proxy URL is cannot-be-a-base").extend(path);
    url.set_query(origin.0.query().map(|query| query.as_str()));
    let response = proxy_http_client.0.post(url).headers(proxy_headers(headers, me)?).body(data).send().await?;
    if response.status() == reqwest::StatusCode::INTERNAL_SERVER_ERROR {
        return Err(ProxyError::InternalServerError(response.text().await?))
    }
    Ok(ProxyResponse::Proxied(Response(response)))
}

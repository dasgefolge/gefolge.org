use {
    lazy_regex::regex_captures,
    rocket::{
        State,
        http::Status,
        response::content::RawHtml,
        uri,
    },
    rocket_util::{
        Origin,
        ToHtml,
        html,
    },
    sqlx::{
        PgPool,
        Postgres,
        Transaction,
    },
    url::Url,
    crate::{
        PageKind,
        StatusOrError,
        page,
        user::{
            Mensch,
            User,
        },
    },
};

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum Error {
    #[error(transparent)] Page(#[from] crate::PageError),
    #[error(transparent)] ParseInt(#[from] std::num::ParseIntError),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Url(#[from] url::ParseError),
}

impl<E: Into<Error>> From<E> for StatusOrError<Error> {
    fn from(e: E) -> Self {
        Self::Err(e.into())
    }
}

async fn link_open_tag(transaction: &mut Transaction<'_, Postgres>, article: &str, namespace: &str) -> sqlx::Result<RawHtml<String>> {
    let exists = sqlx::query_scalar!(r#"SELECT EXISTS (SELECT 1 FROM wiki WHERE title = $1 AND namespace = $2) AS "exists!""#, article, namespace).fetch_one(&mut **transaction).await?;
    Ok(RawHtml(format!("<a{} href=\"{}\">", if exists { "" } else { " class=\"redlink\"" }, if namespace == "wiki" { uri!(main_article(article)) } else { uri!(namespaced_article(article, namespace)) })))
}

#[rocket::get("/wiki")]
pub(crate) async fn index(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>) -> Result<RawHtml<String>, Error> {
    Ok(page(db_pool.begin().await?, me, &uri, PageKind::Sub(vec![
        html! {
            : "wiki";
        },
    ]), "GefolgeWiki", html! {
        h1 : "GefolgeWiki";
        @let namespaces = sqlx::query_scalar!("SELECT name FROM wiki_namespaces ORDER BY name ASC").fetch_all(&**db_pool).await?;
        @if namespaces.is_empty() {
            p : "In diesem wiki sind noch keine Artikel.";
        } else {
            @for namespace in namespaces {
                h2 : namespace;
                ul {
                    @let articles = sqlx::query_scalar!("SELECT DISTINCT title FROM wiki WHERE namespace = $1 ORDER BY title ASC", namespace).fetch_all(&**db_pool).await?;
                    @if articles.is_empty() {
                        li : "(Dieser namespace ist leer.)";
                    } else {
                        @for article in articles {
                            li {
                                a(href = if namespace == "wiki" { uri!(main_article(&article)) } else { uri!(namespaced_article(&article, &namespace)) }.to_string()) : article;
                            }
                        }
                    }
                }
            }
        }
    }).await?)
}

struct Markdown<'a>(Vec<pulldown_cmark::Event<'a>>);

impl<'a> ToHtml for Markdown<'a> {
    fn to_html(&self) -> RawHtml<String> {
        let mut rendered = RawHtml(String::default());
        pulldown_cmark::html::push_html(&mut rendered.0, self.0.iter().cloned());
        rendered
    }

    fn push_html(&self, buf: &mut RawHtml<String>) {
        pulldown_cmark::html::push_html(&mut buf.0, self.0.iter().cloned());
    }
}

async fn render_wiki_page<'a>(transaction: &mut Transaction<'_, Postgres>, source: &'a str) -> Result<Markdown<'a>, Error> {
    let mut events = Vec::default();
    let mut parser = pulldown_cmark::Parser::new_ext(
        &source,
        pulldown_cmark::Options::ENABLE_TABLES | pulldown_cmark::Options::ENABLE_FOOTNOTES | pulldown_cmark::Options::ENABLE_STRIKETHROUGH | pulldown_cmark::Options::ENABLE_MATH | pulldown_cmark::Options::ENABLE_SUPERSCRIPT | pulldown_cmark::Options::ENABLE_SUBSCRIPT,
    ).peekable();
    while let Some(event) = parser.next() {
        events.push(match event {
            pulldown_cmark::Event::UserMention(mention) => if let Some(user) = User::from_id(&mut *transaction, mention.parse()?).await? {
                pulldown_cmark::Event::Html(user.to_html().0.into())
            } else {
                pulldown_cmark::Event::Text(format!("<@{mention}>").into())
            },
            pulldown_cmark::Event::Start(pulldown_cmark::Tag::Heading { level, mut id, classes, attrs }) => {
                if let Some(pulldown_cmark::Event::Text(text)) = parser.peek() {
                    id.get_or_insert(pulldown_cmark::CowStr::Boxed(text.chars().filter_map(|c| if c == ' ' { Some('-') } else if c.is_ascii_alphanumeric() { Some(c.to_ascii_lowercase()) } else { None }).collect::<Box<str>>()));
                }
                pulldown_cmark::Event::Start(pulldown_cmark::Tag::Heading { level, id, classes, attrs })
            }
            pulldown_cmark::Event::Start(pulldown_cmark::Tag::Link { link_type, dest_url, title, id }) => {
                let dest_url = Url::options().base_url(Some(&"https://gefolge.org/wiki/".parse()?)).parse(&dest_url)?;
                if let Some(relative) = Url::parse("https://gefolge.org/wiki/")?.make_relative(&dest_url) {
                    if let Some((_, title)) = regex_captures!("^([0-9a-z_-]+)$", &relative) {
                        pulldown_cmark::Event::Html(link_open_tag(&mut *transaction, title, "wiki").await?.0.into())
                    } else if let Some((_, title, namespace)) = regex_captures!("^([0-9a-z_-]+)/([0-9a-z_-]+)$", &relative) {
                        pulldown_cmark::Event::Html(link_open_tag(&mut *transaction, title, namespace).await?.0.into())
                    } else {
                        pulldown_cmark::Event::Start(pulldown_cmark::Tag::Link { link_type, dest_url: dest_url.to_string().into(), title, id })
                    }
                } else {
                    pulldown_cmark::Event::Start(pulldown_cmark::Tag::Link { link_type, dest_url: dest_url.to_string().into(), title, id })
                }
            }
            _ => event,
        });
    }
    Ok(Markdown(events))
}

#[rocket::get("/wiki/<title>")]
pub(crate) async fn main_article(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str) -> Result<RawHtml<String>, StatusOrError<Error>> {
    let mut transaction = db_pool.begin().await?;
    let source = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = 'wiki' ORDER BY timestamp DESC LIMIT 1", title).fetch_optional(&**db_pool).await?.ok_or_else(|| StatusOrError::Status(Status::NotFound))?;
    let content = render_wiki_page(&mut transaction, &source).await?;
    Ok(page(transaction, me, &uri, PageKind::Sub(vec![
        html! {
            : "wiki";
        },
        html! {
            : title;
        },
    ]), &format!("{title} — GefoleWiki"), html! {
        h1 {
            : title;
            : " ";
            a(href = format!("/wiki/{title}/wiki/edit"), class = "btn btn-primary") : "Bearbeiten";
            a(href = format!("/wiki/{title}/wiki/history"), class = "btn btn-link") : "Versionsgeschichte";
        }
        : content;
    }).await?)
}

#[rocket::get("/wiki/<title>/<namespace>")]
pub(crate) async fn namespaced_article(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str, namespace: &str) -> Result<RawHtml<String>, StatusOrError<Error>> {
    let mut transaction = db_pool.begin().await?;
    let source = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = $2 ORDER BY timestamp DESC LIMIT 1", title, namespace).fetch_optional(&**db_pool).await?.ok_or_else(|| StatusOrError::Status(Status::NotFound))?;
    let content = render_wiki_page(&mut transaction, &source).await?;
    Ok(page(transaction, me, &uri, PageKind::Sub(vec![
        html! {
            : "wiki";
        },
        html! {
            : title;
        },
        html! {
            : namespace;
        },
    ]), &format!("{title} ({namespace}) — GefolgeWiki"), html! {
        h1 {
            : title;
            : " (";
            : namespace;
            : ") ";
            a(href = format!("/wiki/{title}/{namespace}/edit"), class = "btn btn-primary") : "Bearbeiten";
            a(href = format!("/wiki/{title}/{namespace}/history"), class = "btn btn-link") : "Versionsgeschichte";
        }
        : content;
    }).await?)
}

#[rocket::get("/wiki/<title>/<namespace>/history/<rev>")]
pub(crate) async fn revision(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str, namespace: &str, rev: Option<i32>) -> Result<RawHtml<String>, StatusOrError<Error>> {
    let Some(rev) = rev else { return Err(StatusOrError::Status(Status::NotFound)) }; // don't forward to Flask on wrong revision format, prevents an internal server error
    let mut transaction = db_pool.begin().await?;
    let source = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = $2 AND id = $3", title, namespace, rev).fetch_optional(&**db_pool).await?.ok_or_else(|| StatusOrError::Status(Status::NotFound))?;
    let content = render_wiki_page(&mut transaction, &source).await?;
    Ok(page(transaction, me, &uri, PageKind::Sub(vec![
        html! {
            : "wiki";
        },
        html! {
            : title;
        },
        html! {
            : namespace;
        },
        html! {
            : "Versionsgeschichte";
        },
        html! {
            : rev;
        },
    ]), &format!("Version von {title}{} — GefolgeWiki", if namespace == "wiki" { String::default() } else { format!(" ({namespace})") }), html! {
        h1 {
            : "Version von ";
            : title;
            @if namespace != "wiki" {
                : " (";
                : namespace;
                : ")";
            }
            : " ";
            a(href = if namespace == "wiki" { uri!(main_article(title)) } else { uri!(namespaced_article(title, namespace)) }.to_string(), class = "btn btn-primary") : "Neuste Version anzeigen";
            a(href = format!("/wiki/{title}/{namespace}/history"), class = "btn btn-link") : "Versionsgeschichte";
        }
        : content;
    }).await?)
}

use {
    chrono::prelude::*,
    lazy_regex::regex_captures,
    rocket::{
        FromForm,
        State,
        form::{
            self,
            Context,
            Contextual,
            Form,
        },
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
        ToHtml,
        html,
    },
    serenity::{
        all::{
            Context as DiscordCtx,
            CreateAllowedMentions,
            CreateMessage,
            MessageBuilder,
        },
        model::prelude::*,
    },
    serenity_utils::RwFuture,
    sqlx::{
        PgPool,
        Postgres,
        Transaction,
    },
    url::Url,
    gefolge_web_lib::{
        time::MaybeLocalDateTime,
        user::{
            Mensch,
            User,
        },
    },
    crate::{
        PageKind,
        RedirectOrContent,
        base_uri,
        form::{
            form_field,
            full_form,
        },
        page,
        time::format_datetime,
    },
};

const CHANNEL: ChannelId = ChannelId::new(739623881719021728);

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum Error {
    #[error(transparent)] Page(#[from] crate::PageError),
    #[error(transparent)] ParseInt(#[from] std::num::ParseIntError),
    #[error(transparent)] Serenity(#[from] serenity::Error),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Url(#[from] url::ParseError),
}

async fn mentions_to_tags(transaction: &mut Transaction<'_, Postgres>, mut text: String) -> Result<String, Error> {
    while let Some((_, prefix, bang, id, suffix)) = regex_captures!("^(.*?)<@(!?)([0-9]+)>(.*)$", &text) {
        if let Some(user) = User::from_id(transaction, id.parse()?).await? {
            let tag = if let Some(discriminator) = user.discriminator {
                format!("@{}#{discriminator:04}", user.username)
            } else {
                format!("@{}#", user.username)
            };
            text = format!("{prefix}{tag}{suffix}");
        } else {
            // skip this mention but convert the remaining text recursively
            return Ok(format!("{prefix}<@{bang}{id}>{}", Box::pin(mentions_to_tags(transaction, suffix.to_owned())).await?))
        }
    }
    Ok(text)
}

async fn tags_to_mentions(transaction: &mut Transaction<'_, Postgres>, mut text: String) -> sqlx::Result<String> {
    while let Some((_, prefix, username, discriminator, suffix)) = regex_captures!("^(.*?)@([^@#:\n]{2,32})#((?:[0-9]{4})?)(.*)$", &text) { // see https://discord.com/developers/docs/resources/user
        if let Some(user) = User::from_tag(transaction, username, discriminator.parse().ok()).await? {
            text = format!("{prefix}<@{}>{suffix}", user.id);
        } else {
            // skip this tag but convert the remaining text recursively
            return Ok(format!("{prefix}@{username}#{discriminator}{}", Box::pin(tags_to_mentions(transaction, suffix.to_owned())).await?))
        }
    }
    Ok(text)
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
            div(class = "section-list") {
                @for namespace in namespaces {
                    div {
                        h2 : namespace;
                        ul {
                            @let articles = sqlx::query_scalar!("SELECT DISTINCT title FROM wiki WHERE namespace = $1 ORDER BY title ASC", namespace).fetch_all(&**db_pool).await?;
                            @if articles.is_empty() {
                                li : "(Dieser namespace ist leer.)";
                            } else {
                                @for article in articles {
                                    li {
                                        a(href = if namespace == "wiki" { uri!(main_article(&article)) } else { uri!(namespaced_article(&article, &namespace)) }) : article;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }).await?)
}

pub(crate) struct Markdown<'a>(Vec<pulldown_cmark::Event<'a>>);

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

pub(crate) async fn render_wiki_page<'a>(transaction: &mut Transaction<'_, Postgres>, source: &'a str) -> Result<Markdown<'a>, Error> {
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
pub(crate) async fn main_article(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str) -> Result<Option<RawHtml<String>>, Error> {
    let mut transaction = db_pool.begin().await?;
    let Some(source) = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = 'wiki' ORDER BY timestamp DESC LIMIT 1", title).fetch_optional(&**db_pool).await? else { return Ok(None) };
    let content = render_wiki_page(&mut transaction, &source).await?;
    Ok(Some(page(transaction, me, &uri, PageKind::Sub(vec![
        html! {
            : "wiki";
        },
        html! {
            : title;
        },
    ]), &format!("{title} — GefoleWiki"), html! {
        div(class = "header-with-buttons") {
            h1 : title;
            span(class = "button-row") {
                a(href = format!("/wiki/{title}/wiki/edit"), class = "button") : "Bearbeiten";
                a(href = uri!(history(title, "wiki")), class = "button") : "Versionsgeschichte";
            }
        }
        : content;
    }).await?))
}

#[rocket::get("/wiki/<title>/<namespace>")]
pub(crate) async fn namespaced_article(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str, namespace: &str) -> Result<Option<RawHtml<String>>, Error> {
    let mut transaction = db_pool.begin().await?;
    let Some(source) = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = $2 ORDER BY timestamp DESC LIMIT 1", title, namespace).fetch_optional(&**db_pool).await? else { return Ok(None) };
    let content = render_wiki_page(&mut transaction, &source).await?;
    Ok(Some(page(transaction, me, &uri, PageKind::Sub(vec![
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
        div(class = "header-with-buttons") {
            h1 {
                : title;
                : " (";
                : namespace;
                : ")";
            }
            span(class = "button-row") {
                a(href = format!("/wiki/{title}/{namespace}/edit"), class = "button") : "Bearbeiten";
                a(href = uri!(history(title, namespace)), class = "button") : "Versionsgeschichte";
            }
        }
        : content;
    }).await?))
}

enum EditFormDefaults<'v> {
    Context(Context<'v>),
    Values {
        source: Option<String>,
    },
}

impl<'v> EditFormDefaults<'v> {
    fn errors(&self) -> Vec<&form::Error<'v>> {
        match self {
            Self::Context(ctx) => ctx.errors().collect(),
            Self::Values { .. } => Vec::default(),
        }
    }

    fn field_value(&self, field_name: &str) -> Option<&str> {
        match self {
            Self::Context(ctx) => ctx.field_value(field_name),
            Self::Values { .. } => None,
        }
    }

    fn source(&self) -> Option<&str> {
        match self {
            Self::Context(ctx) => ctx.field_value("source"),
            Self::Values { source } => source.as_deref(),
        }
    }
}

async fn edit_form(mut transaction: Transaction<'_, Postgres>, me: Mensch, uri: Origin<'_>, csrf: Option<&CsrfToken>, title: &str, namespace: &str, defaults: EditFormDefaults<'_>) -> Result<RawHtml<String>, Error> {
    let content = {
        let api_key = me.api_key(&mut transaction).await?;
        let mut errors = defaults.errors();
        html! {
            div(class = "header-with-buttons") {
                h1 {
                    : "Wiki-Artikel ";
                    : title;
                    @if namespace != "wiki" {
                        : " (";
                        : namespace;
                        : ")";
                    }
                    @if defaults.source().is_some() {
                        : " bearbeiten";
                    } else {
                        : " erstellen";
                    }
                }
                span(class = "button-row") {
                    a(href = if namespace == "wiki" { uri!(main_article(title)) } else { uri!(namespaced_article(title, namespace)) }, class = "button") : "Abbrechen";
                }
            }
            : full_form(uri!(edit_post(title, namespace)), csrf, html! {
                : form_field("source", &mut errors, html! {
                    label(for = "source") : "Text";
                    textarea(class = "markdown-input", id = "markdown-wiki", data_apikey = api_key, name = "source") : defaults.source().unwrap_or_default();
                });
                div(id = "markdown-wiki-preview") : "Vorschau wird geladen…";
                : form_field("summary", &mut errors, html! {
                    label(for = "summary") : "Zusammenfassung";
                    input(type = "text", name = "summary", placeholder = "optional", value = defaults.field_value("summary"));
                });
            }, errors, "Speichern");
        }
    };
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
            : "bearbeiten";
        },
    ]), &format!("bearbeiten — {title}{} — GefolgeWiki", if namespace == "wiki" { String::default() } else { format!(" ({namespace})") }), content).await?)
}

#[rocket::get("/wiki/<title>/<namespace>/edit")]
pub(crate) async fn edit_get(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, csrf: Option<CsrfToken>, title: &str, namespace: &str) -> Result<RawHtml<String>, Error> {
    let mut transaction = db_pool.begin().await?;
    let source = if let Some(source) = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = $2 ORDER BY timestamp DESC LIMIT 1", title, namespace).fetch_optional(&**db_pool).await? {
        Some(mentions_to_tags(&mut transaction, source).await?)
    } else {
        None
    };
    Ok(edit_form(transaction, me, uri, csrf.as_ref(), title, namespace, EditFormDefaults::Values { source }).await?)
}

#[derive(FromForm, CsrfForm)]
pub(crate) struct EditForm {
    #[field(default = String::new())]
    csrf: String,
    source: String,
    summary: String,
}

#[rocket::post("/wiki/<title>/<namespace>/edit", data = "<form>")]
pub(crate) async fn edit_post(discord_ctx: &State<RwFuture<DiscordCtx>>, db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, csrf: Option<CsrfToken>, title: &str, namespace: &str, form: Form<Contextual<'_, EditForm>>) -> Result<RedirectOrContent, Error> {
    let mut form = form.into_inner();
    form.verify(&csrf);
    let mut transaction = db_pool.begin().await?;
    Ok(if let Some(ref value) = form.value {
        if form.context.errors().next().is_some() {
            RedirectOrContent::Content(edit_form(transaction, me, uri, csrf.as_ref(), title, namespace, EditFormDefaults::Context(form.context)).await?)
        } else {
            let exists = sqlx::query_scalar!(r#"SELECT EXISTS (SELECT 1 FROM wiki WHERE title = $1 AND namespace = $2) AS "exists!""#, title, namespace).fetch_one(&mut *transaction).await?;
            sqlx::query!("INSERT INTO wiki (title, namespace, text, author, timestamp, summary) VALUES ($1, $2, $3, $4, NOW(), $5)", title, namespace, tags_to_mentions(&mut transaction, value.source.clone()).await?, me.id.get() as i64, value.summary).execute(&mut *transaction).await?;
            transaction.commit().await?;
            let url = if namespace == "wiki" { uri!(base_uri(), main_article(title)) } else { uri!(base_uri(), namespaced_article(title, namespace)) };
            let mut content = MessageBuilder::default();
            content.push('<');
            content.push(url.to_string());
            content.push("> wurde von ");
            content.mention(&me.id);
            content.push(if exists { " bearbeitet" } else { " erstellt" });
            if !value.summary.is_empty() {
                content.push_line(':');
                content.push_quote_safe(&value.summary);
            }
            CHANNEL.send_message(&*discord_ctx.read().await, CreateMessage::default().content(content.build()).allowed_mentions(CreateAllowedMentions::default())).await?;
            RedirectOrContent::Redirect(Redirect::to(if namespace == "wiki" { uri!(main_article(title)) } else { uri!(namespaced_article(title, namespace)) }))
        }
    } else {
        RedirectOrContent::Content(edit_form(transaction, me, uri, csrf.as_ref(), title, namespace, EditFormDefaults::Context(form.context)).await?)
    })
}

#[rocket::get("/wiki/<title>/<namespace>/history")]
pub(crate) async fn history(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str, namespace: &str) -> Result<Option<RawHtml<String>>, Error> {
    let revisions = sqlx::query!(r#"SELECT id, timestamp AS "timestamp: DateTime<Utc>", author, summary FROM wiki WHERE title = $1 AND namespace = $2 ORDER BY timestamp DESC"#, title, namespace).fetch_all(&**db_pool).await?;
    if revisions.is_empty() { return Ok(None) }
    let mut transaction = db_pool.begin().await?;
    let viewer_data = me.data(&mut transaction).await?;
    let content = html! {
        h1 {
            : "Versionsgeschichte von ";
            : title;
            @if namespace != "wiki" {
                : " (";
                : namespace;
                : ")";
            }
        }
        table {
            thead {
                tr {
                    th : "Datum";
                    th : "Autor:in";
                    th : "Zusammenfassung";
                }
            }
            tbody {
                @for revision in revisions {
                    tr {
                        td {
                            a(href = uri!(revision(title, namespace, revision.id))) {
                                : format_datetime(&viewer_data, MaybeLocalDateTime::Nonlocal(revision.timestamp), false);
                            }
                        }
                        td {
                            @if let Some(author) = revision.author {
                                @if let Some(author) = User::from_id(&mut transaction, UserId::from(author as u64)).await? {
                                    : author;
                                } else {
                                    : "nicht gefunden";
                                }
                            } else {
                                : "unbekannt";
                            }
                        }
                        td : revision.summary;
                    }
                }
            }
        }
    };
    Ok(Some(page(transaction, me, &uri, PageKind::Sub(vec![
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
    ]), &format!("Versionsgeschichte von {title}{} — GefolgeWiki", if namespace == "wiki" { String::default() } else { format!(" ({namespace})") }), content).await?))
}

#[rocket::get("/wiki/<title>/<namespace>/history/<rev>")]
pub(crate) async fn revision(db_pool: &State<PgPool>, me: Mensch, uri: Origin<'_>, title: &str, namespace: &str, rev: Option<i32>) -> Result<Option<RawHtml<String>>, Error> {
    let Some(rev) = rev else { return Ok(None) }; // don't forward to Flask on wrong revision format, prevents an internal server error
    let mut transaction = db_pool.begin().await?;
    let Some(source) = sqlx::query_scalar!("SELECT text FROM wiki WHERE title = $1 AND namespace = $2 AND id = $3", title, namespace, rev).fetch_optional(&**db_pool).await? else { return Ok(None) };
    let content = render_wiki_page(&mut transaction, &source).await?;
    Ok(Some(page(transaction, me, &uri, PageKind::Sub(vec![
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
        div(class = "header-with-buttons") {
            h1 {
                : "Version von ";
                : title;
                @if namespace != "wiki" {
                    : " (";
                    : namespace;
                    : ")";
                }
            }
            span(class = "button-row") {
                a(href = if namespace == "wiki" { uri!(main_article(title)) } else { uri!(namespaced_article(title, namespace)) }, class = "button") : "Neuste Version anzeigen";
                a(href = uri!(history(title, namespace)), class = "button") : "Versionsgeschichte";
            }
        }
        : content;
    }).await?))
}

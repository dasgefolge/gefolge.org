use {
    async_proto::Protocol,
    chrono_tz::Tz,
    semver::Version,
    std::ops::Range,
};

#[derive(Protocol)]
pub enum ServerMessageV2 {
    Ping,
    Error {
        debug: String,
        display: String,
    },
    NoEvent,
    CurrentEvent {
        id: String,
        timezone: Tz,
    },
    LatestSilVersion(Version),
    MarkdownPreview(String),
}

#[derive(Protocol)]
pub enum ClientMessageV2 {
    Auth {
        api_key: String,
    },
    /// Start receiving notifications about changes to ongoing events (including an event starting or ending), as well as updates to [`sil`](https://github.com/dasgefolge/sil).
    //
    /// Requires having authenticated as a Gefolge member (`Mensch` Discord role).
    CurrentEvent,
    /// Request an HTML preview of the given Markdown document, and set that Markdown document as the base document for `PreviewMarkdownEdit` messages.
    //
    /// Requires having authenticated as a Gefolge member (`Mensch` Discord role).
    PreviewMarkdown(String),
    /// Update the base Markdown document (from the previous `PreviewMarkdown` or `PreviewMarkdownEdit` message) to replace the given range (which is counted in UTF-8 bytes and does not have to lie on character boundaries) with the given string, and request an HTML preview of the updated document.
    //
    /// Requires having authenticated as a Gefolge member (`Mensch` Discord role).
    PreviewMarkdownEdit {
        range: Range<u64>,
        text: Vec<u8>,
    },
}

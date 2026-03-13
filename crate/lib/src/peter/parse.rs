//! Utilities for parsing messages into commands and game actions

use {
    std::str::FromStr,
    serenity::model::prelude::*,
};

#[allow(missing_docs)]
pub fn eat_user_mention(subj: &mut &str) -> Option<UserId> {
    if !subj.starts_with('<') || !subj.contains('>') {
        return None;
    }
    let mut maybe_mention = String::default();
    let mut chars = subj.chars();
    while let Some(c) = chars.next() {
        maybe_mention.push(c);
        if c == '>' {
            if let Ok(id) = UserId::from_str(&maybe_mention) {
                *subj = &subj[maybe_mention.len()..]; // consume mention text
                return Some(id);
            }
            return None;
        }
    }
    None
}

#[allow(missing_docs)]
pub fn eat_whitespace(subj: &mut &str) {
    while subj.starts_with(' ') {
        *subj = &subj[1..];
    }
}

#[allow(missing_docs)]
pub fn next_word(subj: &str) -> Option<String> {
    let mut word = String::default();
    for c in subj.chars() {
        if c == ' ' { break; }
        word.push(c);
    }
    if word.is_empty() { None } else { Some(word) }
}

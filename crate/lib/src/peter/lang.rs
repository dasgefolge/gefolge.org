//! German language utilities.

#![allow(unused, missing_docs)] //TODO remove

use {
    std::{
        borrow::Cow,
        fmt
    },
    num_traits::One,
    quantum_werewolf::game::{
        Faction,
        Role
    },
    serenity::{
        model::user::User,
        utils::MessageBuilder
    }
};

pub enum Gender { M, F, N }
pub enum Case { Nom, Gen, Acc, Dat }

pub use self::Gender::*;
pub use self::Case::*;

pub trait MessageBuilderExt {
    fn dm_mention(&mut self, user: &User) -> &mut Self;
}

impl MessageBuilderExt for MessageBuilder {
    fn dm_mention(&mut self, user: &User) -> &mut Self {
        self.mention(user);
        if let Some(discriminator) = user.discriminator {
            self.push_safe(format!(" ({}#{discriminator:04})", user.name))
        } else {
            self.push_safe(format!(" (@{})", user.name))
        }
    }
}

pub fn article(case: Case, gender: Option<Gender>) -> &'static str {
    match (case, gender) {
        (Nom, Some(M)) | (Gen, Some(F)) | (Gen, None) | (Dat, Some(F)) => "der",
        (Nom, Some(F)) | (Nom, None) | (Acc, Some(F)) | (Acc, None) => "die",
        (Nom, Some(N)) | (Acc, Some(N)) => "das",
        (Gen, Some(M)) | (Gen, Some(N)) => "des",
        (Acc, Some(M)) | (Dat, None) => "den",
        (Dat, Some(M)) | (Dat, Some(N)) => "dem"
    }
}

pub fn cardinal<N: Eq + One + ToString>(n: N, case: Case, gender: Gender) -> Cow<'static, str> {
    if n == N::one() {
        match (case, gender) {
            (Nom, M) | (Nom, N) | (Acc, N) => "ein",
            (Nom, F) | (Acc, F) => "eine",
            (Gen, M) | (Gen, N) => "eines",
            (Gen, F) | (Dat, F) => "einer",
            (Acc, M) => "einen",
            (Dat, M) | (Dat, N) => "einem"
        }.into()
    } else {
        n.to_string().into()
    }
}

pub fn faction_gender(faction: Faction) -> Option<Gender> {
    match faction {
        Faction::Village => Some(N),
        Faction::Werewolves => None
    }
}

pub fn faction_name(faction: Faction, case: Case) -> &'static str {
    match faction {
        Faction::Village => match case {
            Gen => "Dorfes",
            _ => "Dorf"
        },
        Faction::Werewolves => match case {
            Dat => "Werwölfen",
            _ => "Werwölfe"
        }
    }
}

pub fn faction_name_sg(faction: Faction, case: Case) -> &'static str {
    match faction {
        Faction::Village => match case {
            Gen => "Dorfes",
            _ => "Dorf"
        },
        Faction::Werewolves => match case {
            Dat => "Werwolf",
            _ => "Werwolf"
        }
    }
}

pub fn join<D: fmt::Display, I: IntoIterator<Item=D>>(empty: Option<D>, words: I) -> String {
    let mut words = words.into_iter().map(|word| word.to_string()).collect::<Vec<_>>();
    match words.len() {
        0 => empty.expect("tried to join an empty list with no fallback").to_string(),
        1 => words.swap_remove(0),
        2 => format!("{} und {}", words.swap_remove(0), words.swap_remove(0)),
        _ => {
            let last = words.pop().unwrap();
            let first = words.remove(0);
            let builder = words.into_iter()
                .fold(first, |builder, word| format!("{}, {}", builder, word));
            format!("{} und {}", builder, last)
        }
    }
}

pub fn role_gender(role: Role) -> Gender {
    match role {
        Role::Detective => M,
        Role::Healer => M,
        Role::Villager => M,
        Role::Werewolf(_) => M
    }
}

pub fn role_name(role: Role, case: Case, plural: bool) -> Cow<'static, str> {
    match role {
        Role::Detective => match (case, plural) {
            (Gen, false) => "Detektivs",
            (_, false) => "Detektiv",
            (Dat, true) => "Detektiven",
            (_, true) => "Detektive"
        }.into(),
        Role::Healer => match (case, plural) {
            (Gen, false) => "Heilers",
            (Dat, true) => "Heilern",
            _ => "Heiler"
        }.into(),
        Role::Villager => match (case, plural) {
            (Gen, false) => "Dorfbewohners",
            (Dat, true) => "Dorfbewohnern",
            _ => "Dorfbewohner"
        }.into(),
        Role::Werewolf(rank) => format!("{} (Rollenrang {})", match (case, plural) {
            (Gen, false) => "Werwolfs",
            (_, false) => "Werwolf",
            (Dat, true) => "Werwölfen",
            (_, true) => "Werwölfe"
        }, rank + 1).into()
    }
}

pub fn zu(gender: Option<Gender>) -> Cow<'static, str> {
    match article(Dat, gender) {
        "dem" => "zum".into(),
        "der" => "zur".into(),
        art => format!("zu {}", art).into()
    }
}

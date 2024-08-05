use {
    chrono::prelude::*,
    serde::{
        Deserialize,
        Deserializer,
        Serialize,
        de::Error as _,
    },
    serenity::model::id::UserId,
    crate::money::Euro,
};

fn implicit_utc<'de, D: Deserializer<'de>>(deserializer: D) -> Result<DateTime<Utc>, D::Error> {
    let datetime = <&str>::deserialize(deserializer)?;
    if let Ok(aware) = DateTime::parse_from_rfc3339(datetime) {
        Ok(aware.with_timezone(&Utc))
    } else if let Ok(naive) = NaiveDateTime::parse_from_str(datetime, "%Y-%m-%dT%H:%M:%S").or_else(|_| NaiveDateTime::parse_from_str(datetime, "%Y-%m-%d %H:%M:%SZ")) {
        Ok(Utc.from_utc_datetime(&naive))
    } else if let Ok(naive) = NaiveDateTime::parse_from_str(datetime, "%Y-%m-%d %H:%M:%S").or_else(|_| NaiveDateTime::parse_from_str(datetime, "%Y-%m-%d %H:%M:%SZ")) {
        Ok(Utc.from_utc_datetime(&naive))
    } else {
        Err(D::Error::invalid_value(serde::de::Unexpected::Str(datetime), &"Gefolge JSON datetime"))
    }
}

fn make_true() -> bool { true }

#[derive(Deserialize, Serialize)]
#[serde(tag = "type", deny_unknown_fields, rename_all = "camelCase")]
pub enum AbrechnungDetail {
    Even {
        amount: Euro,
        label: String,
        people: u16,
        total: Euro,
    },
    Flat {
        amount: Euro,
        label: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        note: Option<String>,
        #[serde(skip_serializing_if = "Option::is_none")]
        snowflake: Option<UserId>,
    },
    #[serde(rename_all = "camelCase")]
    Weighted {
        amount: Euro,
        label: String,
        nights_attended: f64,
        nights_total: f64,
        total: Euro,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(untagged)]
pub enum EventPersonId {
    EventGuest(u8),
    Discord(UserId),
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "type", deny_unknown_fields, rename_all = "camelCase")]
pub enum Transaction {
    BankTransfer {
        amount: Euro,
        #[serde(deserialize_with = "implicit_utc")]
        time: DateTime<Utc>,
        #[serde(rename = "transactionID")]
        transaction_id: String,
    },
    EventAnzahlung {
        amount: Euro,
        default: Option<Euro>,
        event: String,
        guest: Option<EventPersonId>,
        #[serde(deserialize_with = "implicit_utc")]
        time: DateTime<Utc>,
    },
    #[serde(rename_all = "camelCase")]
    EventAnzahlungReturn {
        amount: Euro,
        event: String,
        extra_remaining: Euro,
        #[serde(deserialize_with = "implicit_utc")]
        time: DateTime<Utc>,
    },
    EventAbrechnung {
        amount: Euro,
        details: Vec<AbrechnungDetail>,
        event: String,
        guest: Option<EventPersonId>,
        #[serde(deserialize_with = "implicit_utc")]
        time: DateTime<Utc>,
    },
    #[serde(rename_all = "camelCase")]
    PayPal {
        amount: Euro,
        email: String,
        #[serde(deserialize_with = "implicit_utc")]
        time: DateTime<Utc>,
        transaction_code: String,
    },
    SponsorWerewolfCard {
        amount: Euro,
        faction: String, //TODO Faction enum or Option<Faction>?
        role: String,
        time: DateTime<Utc>,
    },
    Transfer {
        amount: Euro,
        comment: Option<String>,
        mensch: UserId,
        #[serde(deserialize_with = "implicit_utc")]
        time: DateTime<Utc>,
    },
}

#[derive(Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct UserData {
    api_key: Option<String>,
    #[serde(default = "make_true")]
    enable_dejavu: bool,
    #[serde(default = "make_true")]
    event_timezone_override: bool,
    twitch: Option<serde_json::Value>,
    #[serde(default)]
    pub transactions: Vec<Transaction>,
}

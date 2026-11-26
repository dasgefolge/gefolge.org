use {
    jiff::Timestamp,
    serde::{
        Deserialize,
        Serialize,
    },
    serenity::model::id::UserId,
    crate::money::Euro,
};

mod implicit_utc {
    use {
        jiff::{
            Timestamp,
            ZonedDateTime,
            civil,
            tz::TimeZone,
        },
        serde::{
            Deserialize as _,
            Deserializer,
            Serialize as _,
            Serializer,
            de::Error as _,
        },
    };

    pub(super) fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Timestamp, D::Error> {
        let datetime = <&str>::deserialize(deserializer)?;
        if let Ok(aware) = datetime.parse::<ZonedDateTime>() {
            Ok(aware.timestamp())
        } else if let Some(naive) = ["%FT%TZ", "%FT%T", "%F %TZ", "%F %T"].into_iter().find_map(|format| civil::DateTime::strptime(format, datetime).ok()) {
            Ok(naive.to_zoned_datetime(TimeZone::UTC).map_err(D::Error::custom)?.timestamp())
        } else {
            Err(D::Error::invalid_value(serde::de::Unexpected::Str(datetime), &"Gefolge JSON datetime"))
        }
    }

    pub(super) fn serialize<S: Serializer>(timestamp: &Timestamp, serializer: S) -> Result<S::Ok, S::Error> {
        timestamp.to_zoned_datetime(TimeZone::UTC).strftime("%FT%TZ").to_string().serialize(serializer)
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
        #[serde(with = "implicit_utc")]
        time: Timestamp,
        #[serde(rename = "transactionID")]
        transaction_id: String,
    },
    Bar {
        amount: Euro,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
    },
    EventAnzahlung {
        amount: Euro,
        default: Option<Euro>,
        event: String,
        guest: Option<EventPersonId>,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
    },
    #[serde(rename_all = "camelCase")]
    EventAnzahlungReturn {
        amount: Euro,
        event: String,
        extra_remaining: Euro,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
    },
    EventAbrechnung {
        amount: Euro,
        details: Vec<AbrechnungDetail>,
        event: String,
        guest: Option<EventPersonId>,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
    },
    #[serde(rename_all = "camelCase")]
    PayPal {
        amount: Euro,
        email: String,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
        transaction_code: String,
    },
    SponsorWerewolfCard {
        amount: Euro,
        faction: String, //TODO Faction enum or Option<Faction>?
        role: String,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
    },
    Transfer {
        amount: Euro,
        comment: Option<String>,
        mensch: UserId,
        #[serde(with = "implicit_utc")]
        time: Timestamp,
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

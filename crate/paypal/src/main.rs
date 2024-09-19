#![deny(rust_2018_idioms, unused, unused_crate_dependencies, unused_import_braces, unused_lifetimes, unused_qualifications, warnings)]
#![forbid(unsafe_code)]

use {
    std::{
        convert::Infallible as Never,
        process::Command,
    },
    chrono::prelude::*,
    gefolge_web::{
        db::{
            Transaction,
            UserData,
        },
        money::Euro,
    },
    serenity::model::prelude::*,
    sqlx::{
        PgPool,
        postgres::PgConnectOptions,
        types::Json,
    },
    wheel::traits::SyncCommandExt as _,
};

#[derive(Debug, thiserror::Error)]
enum Error {
    #[error(transparent)] ChronoParse(#[from] chrono::ParseError),
    #[error(transparent)] EuroParse(#[from] gefolge_web::money::EuroParseError),
    #[error(transparent)] Io(#[from] std::io::Error),
    #[error(transparent)] ParseInt(#[from] std::num::ParseIntError),
    #[error(transparent)] Sql(#[from] sqlx::Error),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[error("duplicate transaction ID")]
    DuplicateTransactionCode,
}

#[derive(clap::Parser)]
struct Args {
    #[clap(long)]
    amount: Option<Euro>,
    #[clap(long)]
    transaction_code: Option<String>,
    #[clap(long)]
    snowflake: Option<UserId>,
    #[clap(long)]
    email: Option<String>,
    #[clap(long, value_parser = DateTime::parse_from_rfc2822)]
    timestamp: Option<DateTime<FixedOffset>>,
}

#[wheel::main(debug)]
async fn main(args: Args) -> Result<Never, Error> {
    let (snowflake, msg) = {
        let amount = if let Some(amount) = args.amount { amount } else { wheel::input!("amount (€): ")?.trim().parse()? };
        let transaction_code = if let Some(transaction_code) = args.transaction_code { transaction_code } else { wheel::input!("transaction ID: ")? };
        let transaction_code = transaction_code.trim();
        let snowflake = if let Some(snowflake) = args.snowflake { snowflake } else { wheel::input!("snowflake: ")?.trim().parse()? };
        let email = if let Some(email) = args.email { email } else { wheel::input!("email: ")?.trim().to_owned() };
        let time = if let Some(timestamp) = args.timestamp { timestamp } else { DateTime::parse_from_rfc2822(&wheel::input!("timestamp: ")?.trim().replace("  ", " "))? }.with_timezone(&Utc);
        let transaction = Transaction::PayPal {
            transaction_code: transaction_code.to_owned(),
            amount, email, time,
        };
        let db_pool = PgPool::connect_with(PgConnectOptions::default().host("gefolge.org").username("fenhl").password(env!("PGPASSWORD")).database("gefolge").application_name("gefolge-paypal")).await?;
        let mut db_transaction = db_pool.begin().await?;
        let Json(mut value) = sqlx::query_scalar!(r#"SELECT value AS "value: Json<UserData>" FROM json_user_data WHERE id = $1"#, i64::from(snowflake)).fetch_optional(&mut *db_transaction).await?.unwrap_or_default();
        if value.transactions.iter().any(|iter_transaction| if let Transaction::PayPal { transaction_code: iter_transaction_code, .. } = iter_transaction { //TODO check all users, as well as wmb
            iter_transaction_code == transaction_code
        } else {
            false
        }) {
            return Err(Error::DuplicateTransactionCode)
        }
        value.transactions.push(transaction);
        sqlx::query!("INSERT INTO json_user_data (id, value) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value", i64::from(snowflake), Json(value) as _).execute(&mut *db_transaction).await?;
        db_transaction.commit().await?;
        (snowflake, if amount >= Euro::default() {
            format!("Deine PayPal-Überweisung von {} wurde als Guthaben auf gefolge.org eingetragen.", amount)
        } else {
            format!("Es wurden {} von deinem Guthaben auf gefolge.org abgezogen und dir auf PayPal überwiesen.", -amount)
        })
    };
    match Command::new("peter").arg("msg").arg(snowflake.to_string()).arg(msg).exec("peter")? {}
}

use {
    hmac::{
        Hmac,
        Mac as _,
    },
    itermore::IterArrayChunks as _,
    rocket::{
        State,
        async_trait,
        data::{
            self,
            Data,
            FromData,
            ToByteUnit as _,
        },
        http::Status,
        outcome::Outcome,
        request::Request,
    },
    sha2::Sha256,
    tokio::process::Command,
    wheel::{
        fs,
        traits::{
            AsyncCommandOutputExt as _,
            IoResultExt as _,
        },
    },
    crate::{
        config::Config,
        websocket,
    },
};

macro_rules! guard_try {
    ($res:expr) => {
        match $res {
            Ok(x) => x,
            Err(e) => return Outcome::Error((Status::InternalServerError, e.into())),
        }
    };
}

pub(crate) struct SignedPayload(String);

fn is_valid_signature(signature: &str, body: &str, secret: &str) -> bool {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("HMAC can take key of any size");
    mac.update(body.as_bytes());
    let Some((prefix, code)) = signature.split_once('=') else { return false };
    let Ok(code) = code.chars().arrays().map(|[c1, c2]| u8::from_str_radix(&format!("{c1}{c2}"), 16)).collect::<Result<Vec<_>, _>>() else { return false };
    prefix == "sha256" && mac.verify_slice(&code).is_ok()
}

#[test]
fn test_valid_signature() {
    assert!(is_valid_signature("sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17", "Hello, World!", "It's a Secret to Everybody"))
}

#[test]
fn test_invalid_signature() {
    assert!(!is_valid_signature("sha256=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "Hello, World!", "It's a Secret to Everybody"))
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum PayloadError {
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[error("config guard forwarded")]
    ConfigForward,
    #[error("value of X-Hub-Signature-256 header is not valid")]
    InvalidSignature,
    #[error("failed to get config")]
    MissingConfig,
    #[error("missing X-Hub-Signature-256 header")]
    MissingSignature,
}

#[async_trait]
impl<'r> FromData<'r> for SignedPayload {
    type Error = PayloadError;

    async fn from_data(req: &'r Request<'_>, data: Data<'r>) -> data::Outcome<'r, Self, Self::Error> {
        if let Some(signature) = req.headers().get_one("X-Hub-Signature-256") {
            let body = guard_try!(data.open(2.mebibytes()).into_string().await.at_unknown());
            match req.guard::<&State<Config>>().await {
                Outcome::Success(config) => if is_valid_signature(signature, &body, &config.github_webhook_secret) {
                    Outcome::Success(Self(body.value))
                } else {
                    Outcome::Error((Status::Unauthorized, PayloadError::InvalidSignature))
                },
                Outcome::Error((status, ())) => Outcome::Error((status, PayloadError::MissingConfig)),
                Outcome::Forward(status) => Outcome::Error((status, PayloadError::ConfigForward)), // can't return Outcome::Forward here since `data` has been moved
            }
        } else {
            Outcome::Error((Status::BadRequest, PayloadError::MissingSignature))
        }
    }
}

#[derive(Debug, thiserror::Error, rocket_util::Error)]
pub(crate) enum WebhookError {
    #[error(transparent)] Toml(#[from] toml::de::Error),
    #[error(transparent)] Wheel(#[from] wheel::Error),
}

#[rocket::post("/api/github-webhook", data = "<payload>")]
pub(crate) async fn github_webhook(payload: SignedPayload) -> Result<(), WebhookError> {
    let _ = payload.0; // the data guard has verified that the request came from GitHub and we've only configured the webhook for push events for the sil repo for now
    Command::new("git").arg("pull").current_dir("/opt/git/github.com/dasgefolge/sil/main").check("git pull").await?;
    let websocket::PackageManifest { package: websocket::PackageData { version } } = toml::from_slice(&fs::read("/opt/git/github.com/dasgefolge/sil/main/Cargo.toml").await?)?;
    websocket::SIL_VERSION.send_replace(Some(version));
    Ok(())
}

use {
    std::{
        fmt,
        ops::Neg,
        str::FromStr,
    },
    lazy_regex::regex_captures,
    serde::{
        Deserialize,
        Deserializer,
    },
    serde_with::SerializeDisplay,
};

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, SerializeDisplay)]
pub struct Euro {
    pub cents: i64,
}

impl Euro {
    pub fn is_negative(&self) -> bool {
        self.cents.is_negative()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum EuroParseError {
    #[error(transparent)] Int(#[from] std::num::ParseIntError),
    #[error("unexpected format")]
    Format,
    #[error("value out of range")]
    Range,
}

impl FromStr for Euro {
    type Err = EuroParseError;

    fn from_str(s: &str) -> Result<Self, EuroParseError> {
        let (_, sign, euros, cents) = regex_captures!("^([+−-]?)([0-9]+)(?:[.,]([0-9]{2}))?€?$", s).ok_or(EuroParseError::Format)?;
        let sign = match sign {
            "" | "+" => 1,
            "−" | "-" => -1,
            _ => unreachable!(),
        };
        let euros = euros.parse::<i64>()?;
        let cents = if cents.is_empty() {
            0
        } else {
            cents.parse::<i64>().expect("cents in i64 range")
        };
        Ok(Self {
            cents: euros.checked_mul(100).ok_or(EuroParseError::Range)?.checked_add(cents).ok_or(EuroParseError::Range)?.checked_mul(sign).ok_or(EuroParseError::Range)?,
        })
    }
}

impl<'de> Deserialize<'de> for Euro {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        use serde::de::*;

        struct EuroVisitor;

        impl<'de> Visitor<'de> for EuroVisitor {
            type Value = Euro;

            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(f, "a number with at most 2 fractional digits or a string thereof")
            }

            fn visit_i64<E: Error>(self, v: i64) -> Result<Euro, E> {
                v.checked_mul(100).ok_or_else(|| E::invalid_value(Unexpected::Signed(v), &self)).map(|cents| Euro { cents })
            }

            fn visit_i128<E: Error>(self, v: i128) -> Result<Euro, E> {
                i64::try_from(v).map_err(|_| E::invalid_value(Unexpected::Other("overflowing number"), &self))?
                    .checked_mul(100).ok_or_else(|| E::invalid_value(Unexpected::Other("overflowing number"), &self))
                    .map(|cents| Euro { cents })
            }

            fn visit_u64<E: Error>(self, v: u64) -> Result<Euro, E> {
                i64::try_from(v).map_err(|_| E::invalid_value(Unexpected::Unsigned(v), &self))?
                    .checked_mul(100).ok_or_else(|| E::invalid_value(Unexpected::Unsigned(v), &self))
                    .map(|cents| Euro { cents })
            }

            fn visit_u128<E: Error>(self, v: u128) -> Result<Euro, E> {
                i64::try_from(v).map_err(|_| E::invalid_value(Unexpected::Other("overflowing number"), &self))?
                    .checked_mul(100).ok_or_else(|| E::invalid_value(Unexpected::Other("overflowing number"), &self))
                    .map(|cents| Euro { cents })
            }

            fn visit_f64<E: Error>(self, v: f64) -> Result<Euro, E> {
                Ok(Euro { cents: (v * 100.0).round() as i64 })
            }

            fn visit_str<E: Error>(self, v: &str) -> Result<Euro, E> {
                v.parse().map_err(|_| E::invalid_value(Unexpected::Str(v), &self))
            }
        }

        deserializer.deserialize_any(EuroVisitor)
    }
}

impl Neg for Euro {
    type Output = Self;

    fn neg(self) -> Self {
        Self { cents: self.cents.checked_neg().expect("euro value out of range") }
    }
}

impl fmt::Display for Euro {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.cents < 0 {
            write!(f, "−")?;
        }
        let euros = self.cents.abs() / 100;
        let cents = self.cents.abs() % 100;
        write!(f, "{euros},{cents:02}€")
    }
}

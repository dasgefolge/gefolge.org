use {
    std::mem,
    rocket::{
        form,
        http::uri::Origin,
        response::content::RawHtml,
    },
    rocket_csrf::CsrfToken,
    rocket_util::{
        ToHtml,
        html,
    },
};

pub(crate) fn render_form_error(error: &form::Error<'_>) -> RawHtml<String> {
    html! {
        p(class = "error", data_error_field? = error.name.as_ref().map(|n| n.to_string())) : error;
    }
}

pub(crate) fn form_field(name: &str, errors: &mut Vec<&form::Error<'_>>, content: impl ToHtml) -> RawHtml<String> {
    let field_errors;
    (field_errors, *errors) = mem::take(errors).into_iter().partition(|error| error.is_for(name));
    html! {
        fieldset(class? = (!field_errors.is_empty()).then_some("error")) {
            @for error in field_errors {
                : render_form_error(error);
            }
            : content;
        }
    }
}

pub(crate) fn full_form(uri: Origin<'_>, csrf: Option<&CsrfToken>, content: impl ToHtml, errors: Vec<&form::Error<'_>>, submit_text: &str) -> RawHtml<String> {
    html! {
        form(action = uri.to_string(), method = "post") {
            : csrf;
            @for error in errors {
                : render_form_error(error);
            }
            : content;
            fieldset {
                input(type = "submit", value = submit_text);
            }
        }
    }
}

import datetime
import flask
import functools
import jinja2
import pytz
import re

_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')

def parse_iso_datetime(datetime_str, *, tz=pytz.utc):
    if isinstance(datetime_str, datetime.datetime):
        return datetime_str
    return tz.localize(datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S'), is_dst=None)

def setup(app):
    @app.template_filter()
    @jinja2.evalcontextfilter
    def nl2br(eval_ctx, value): #FROM http://flask.pocoo.org/snippets/28/
        result = u'\n\n'.join(u'<p>%s</p>' % p.replace('\n', '<br>\n') \
            for p in _paragraph_re.split(jinja2.escape(value)))
        if eval_ctx.autoescape:
            result = jinja2.Markup(result)
        return result

def template(template_name=None):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if template_name is None:
                template_path = '{}.html'.format(flask.request.endpoint.replace('.', '/'))
            else:
                template_path = '{}.html'.format(template_name.replace('.', '/'))
            context = f(*args, **kwargs)
            if context is None:
                context = {}
            elif not isinstance(context, dict):
                return context
            return flask.render_template(template_path, **context)

        return wrapper

    return decorator

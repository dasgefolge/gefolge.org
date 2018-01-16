import datetime
import flask
import functools
import jinja2
import pytz
import re

_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')

class Path:
    def __init__(self, parent, name, *args):
        if parent is None:
            self.parent = None
        else:
            self.parent = parent.make_path(*args)
        self.name = name

    def __iter__(self):
        if self.parent is not None:
            yield from self.parent
        yield self

    @property
    def url(self):
        if self.parent is None:
            result = '/'
        else:
            result = self.parent.url + '/'
        if hasattr(self.name, url_part):
            return result + self.name.url_part
        else:
            return result + str(self.name)

def parse_iso_datetime(datetime_str, *, tz=pytz.utc):
    if isinstance(datetime_str, datetime.datetime):
        return datetime_str
    return tz.localize(datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S'), is_dst=None)

def path(name, parent=None):
    def decorator(f):
        def make_path(*args):
            url_part = None
            if callable(parent):
                parent = parent(*args)
            if callable(name):
                name = name(*args)
            elif isinstance(name, tuple):
                url_part, name = name
            return Path(parent, name, url_part, *args)

        @functools.wraps(f)
        def wrapper(*args):
            flask.g.path = wrapper.make_path(*args)
            return f(*args)

        wrapper.make_path = make_path
        return wrapper

    return decorator

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

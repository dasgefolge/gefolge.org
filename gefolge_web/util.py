import copy
import datetime
import flask
import functools
import inspect
import jinja2
import lazyjson
import more_itertools
import pytz
import re

EDIT_LOG = lazyjson.File('/usr/local/share/fidera/log.json')
PARAGRAPH_RE = re.compile(r'(?:\r\n|\r|\n){2,}')

class Path:
    def __init__(self, parent, name, url_part, kwargs):
        if parent is None:
            self.parent = None
        else:
            self.parent = parent.make_path(**kwargs)
        self.name = name
        self.url_part = url_part

    @property
    def components(self):
        if self.parent is None:
            return [self]
        else:
            return self.parent.components + [self]

    @property
    def url(self):
        if self.parent is None:
            result = '/'
        else:
            result = self.parent.url + '/'
        if self.url_part is not None:
            return result + self.url_part
        elif hasattr(self.name, 'url_part'):
            return result + self.name.url_part
        else:
            return result + str(self.name)

def date_range(start, end):
    date = start
    while date < end:
        yield date
        date += datetime.timedelta(days=1)

def log(event_type, event):
    event = copy.copy(event)
    event['by'] = flask.g.user.snowflake
    event['time'] = '{:%Y-%m-%d %H:%M:%S}'.format(now())
    event['type'] = event_type
    EDIT_LOG.append(event)

def now(tz=pytz.timezone('Europe/Berlin')):
    return pytz.utc.localize(datetime.datetime.utcnow()).astimezone(tz)

def parse_iso_date(date_str):
    if isinstance(date_str, datetime.date):
        return date_str
    return datetime.date(*map(int, date_str.split('-')))

def parse_iso_datetime(datetime_str, *, tz=pytz.timezone('Europe/Berlin')):
    if isinstance(datetime_str, datetime.datetime):
        return datetime_str
    return tz.localize(datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S'), is_dst=None)

def path(name, parent=None):
    def decorator(f):
        def make_path(**kwargs):
            url_part = None
            if callable(name):
                filtered_kwargs = {
                    param_name: kwargs[param_name]
                    for param_name in inspect.signature(name).parameters
                    if param_name in kwargs
                }
                resolved_name = name(**filtered_kwargs)
            elif isinstance(name, tuple):
                url_part, resolved_name = name
            else:
                resolved_name = name
            return Path(parent, resolved_name, url_part, kwargs)

        @functools.wraps(f)
        def wrapper(**kwargs):
            flask.g.path = wrapper.make_path(**kwargs)
            return f(**kwargs)

        wrapper.make_path = make_path
        return wrapper

    return decorator

def setup(app):
    @app.template_filter()
    def dm(value):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        if isinstance(value, str):
            if ' ' in value:
                value = value.split(' ')[0]
            value = parse_iso_date(value)
        return '{:%d.%m.}'.format(value)

    @app.template_filter()
    def dmy(value):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        if isinstance(value, str):
            if ' ' in value:
                value = value.split(' ')[0]
            value = parse_iso_date(value)
        return '{:%d.%m.%Y}'.format(value)

    @app.template_filter()
    def dmy_hm(value):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        if isinstance(value, str):
            value = parse_iso_datetime(value)
        return '{:%d.%m.%Y %H:%M}'.format(value)

    @app.template_filter()
    def length(value):
        try:
            return len(value)
        except TypeError:
            return more_itertools.ilen(value)

    @app.template_filter()
    def natjoin(value):
        sequence = [str(elt) for elt in value]
        if len(sequence) == 0:
            raise IndexError('Tried to join empty sequence')
        elif len(sequence) == 1:
            return sequence[0]
        elif len(sequence) == 2:
            return '{} und {}'.format(sequence[0], sequence[1])
        else:
            return ', '.join(sequence[:-1]) + ' und {}'.format(sequence[-1])

    @app.template_filter()
    def next_date(value):
        if isinstance(value, lazyjson.Node):
           value = value.value()
        if isinstance(value, str):
           value = parse_iso_date(value)
        return value + datetime.timedelta(days=1)

    @app.template_filter()
    @jinja2.evalcontextfilter
    def nl2br(eval_ctx, value): #FROM http://flask.pocoo.org/snippets/28/
        result = u'\n\n'.join(u'<p>%s</p>' % p.replace('\n', '<br>\n') \
            for p in PARAGRAPH_RE.split(jinja2.escape(value)))
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

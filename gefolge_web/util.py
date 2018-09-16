import contextlib
import copy
import datetime
import decimal
import flask
import functools
import inspect
import jinja2
import json
import lazyjson
import more_itertools
import pathlib
import pytz
import re
import subprocess
import traceback

CONFIG_PATH = pathlib.Path('/usr/local/share/fidera/config.json')
EDIT_LOG = lazyjson.File('/usr/local/share/fidera/log.json')
PARAGRAPH_RE = re.compile(r'(?:\r\n|\r|\n){2,}')

CRASH_NOTICE = """To: fenhl@fenhl.net
From: {}@{}
Subject: gefolge.org internal server error

An internal server error occurred on gefolge.org
"""

@functools.total_ordering
class Euro:
    def __init__(self, value=0):
        self.value = decimal.Decimal(value)
        if self.value.quantize(decimal.Decimal('1.00')) != self.value:
            raise ValueError('Euro value contains fractional cents')

    def __eq__(self, other):
        return isinstance(other, Euro) and self.value == other.value

    def __lt__(self, other):
        if not isinstance(other, Euro):
            return NotImplemented
        return self.value < other.value

    def __repr__(self):
        return 'gefolge_web.event.Euro({!r})'.format(self.value)

    def __str__(self):
        return '{:.2f}€'.format(self.value).replace('.', ',')

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

def notify_crash(exc=None):
    whoami = subprocess.run(['whoami'], stdout=subprocess.PIPE, check=True).stdout.decode('utf-8').strip()
    hostname = subprocess.run(['hostname', '-f'], stdout=subprocess.PIPE, check=True).stdout.decode('utf-8').strip()
    mail_text = CRASH_NOTICE.format(whoami, hostname)
    if exc is not None:
        mail_text += '\n' + traceback.format_exc()
    return subprocess.run(['ssmtp', 'fenhl@fenhl.net'], input=mail_text.encode('utf-8'), check=True)

def now(tz=pytz.timezone('Europe/Berlin')):
    return pytz.utc.localize(datetime.datetime.utcnow()).astimezone(tz)

def parse_iso_date(date_str):
    if isinstance(date_str, datetime.date):
        return date_str
    return datetime.date(*map(int, date_str.split('-')))

def parse_iso_datetime(datetime_str, *, tz=pytz.timezone('Europe/Berlin')):
    if isinstance(datetime_str, datetime.datetime):
        return datetime_str
    if datetime_str.endswith('Z'):
        return pytz.utc.localize(datetime.datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%SZ'), is_dst=None).astimezone(tz)
    else:
        return tz.localize(datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S'), is_dst=None)

def setup(app):
    @app.errorhandler(500)
    def internal_server_error(e):
        with contextlib.suppress(Exception):
            notify_crash(e)
        return 'Internal Server Error', 500

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
    def hm(value):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        if isinstance(value, str):
            value = parse_iso_datetime(value)
        return '{:%H:%M}'.format(value)

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

    @app.before_request
    def current_time():
        flask.g.now = now()

    @app.before_request
    def prepare_reboot_notice():
        with pathlib.Path('/opt/dev/reboot.json').open() as reboot_info_f:
            reboot_info = json.load(reboot_info_f)
        if 'schedule' in reboot_info:
            flask.g.reboot_timestamp = parse_iso_datetime(reboot_info['schedule'])
            flask.g.reboot_upgrade = reboot_info.get('upgrade', False)
            flask.g.reboot_end_time = None if flask.g.reboot_upgrade else flask.g.reboot_timestamp + datetime.timedelta(minutes=15)
        else:
            flask.g.reboot_timestamp = None
            flask.g.reboot_upgrade = None
            flask.g.reboot_end_time = None

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

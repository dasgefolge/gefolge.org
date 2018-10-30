import class_key
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

BASE_PATH = pathlib.Path('/usr/local/share/fidera') #TODO use basedir
CONFIG_PATH = BASE_PATH / 'config.json'
EDIT_LOG = lazyjson.File(BASE_PATH / 'log.json')
PARAGRAPH_RE = re.compile(r'(?:\r\n|\r|\n){2,}')

CRASH_NOTICE = """To: fenhl@fenhl.net
From: {}@{}
Subject: gefolge.org internal server error

An internal server error occurred on gefolge.org
"""

@class_key.class_key()
class Euro:
    def __init__(self, value=0):
        self.value = decimal.Decimal(value)
        if self.value.quantize(decimal.Decimal('1.00')) != self.value:
            raise ValueError('Euro value contains fractional cents: {!r}'.format(self.value))

    def __abs__(self):
        return Euro(abs(self.value))

    def __add__(self, other):
        if isinstance(other, Euro):
            return Euro(self.value + other.value)
        return NotImplemented

    @property
    def __key__(self):
        return self.value

    def __mod__(self, other):
        if isinstance(other, Euro):
            return Euro(self.value % other.value)
        return NotImplemented

    def __mul__(self, other):
        if isinstance(other, int):
            return Euro(self.value * other)
        if isinstance(other, decimal.Decimal):
            return Euro(self.value * other)
        return NotImplemented

    def __neg__(self):
        return Euro(-self.value)

    def __pos__(self):
        return Euro(self.value)

    def __repr__(self):
        return 'gefolge_web.event.Euro({!r})'.format(self.value)

    def __str__(self):
        return '{:.2f}€'.format(self.value).replace('-', '−').replace('.', ',')

    def __sub__(self, other):
        if isinstance(other, Euro):
            return Euro(self.value - other.value)
        return NotImplemented

class Transaction:
    def __init__(self, json_data):
        self.json_data = json_data

    @classmethod
    def anzahlung(cls, event, amount=None, *, guest=None, time=None):
        if time is None:
            time = now()
        if amount is None:
            amount = -event.anzahlung
        json_data = {
            'type': 'eventAnzahlung',
            'amount': amount.value,
            'default': -event.anzahlung.value,
            'time': '{:%Y-%m-%d %H:%M:%S}'.format(time.astimezone(pytz.utc)),
            'event': event.event_id
        }
        if guest is not None:
            json_data['guest'] = guest.snowflake
        return cls(json_data)

    @classmethod
    def anzahlung_return(cls, event, remaining, amount):
        json_data = {
            'type': 'eventAnzahlungReturn',
            'amount': amount.value,
            'extraRemaining': remaining.value,
            'time': '{:%Y-%m-%d H:%M:%S}'.format(now(pytz.utc)),
            'event': event.event_id
        }

    @classmethod
    def sponsor_werewolf_card(cls, card, amount):
        return cls({
            'type': 'sponsorWerewolfCard',
            'amount': -amount.value,
            'time': '{:%Y-%m-%d %H:%M:%S}'.format(now().astimezone(pytz.utc)),
            'faction': card['faction'],
            'role': card['role']
        })

    def __html__(self):
        if self.json_data['type'] == 'bankTransfer':
            return jinja2.Markup('Überweisung')
        elif self.json_data['type'] == 'eventAbrechnung':
            import gefolge_web.event.model

            event = gefolge_web.event.model.Event(self.json_data['event'])
            if 'guest' in self.json_data:
                return jinja2.Markup('Abrechnung von {} für {}'.format(event.__html__(), jinja2.escape(event.person(self.json_data['guest']))))
            else:
                return jinja2.Markup('Abrechnung von {}'.format(event.__html__()))
        elif self.json_data['type'] == 'eventAnzahlung':
            import gefolge_web.event.model

            event = gefolge_web.event.model.Event(self.json_data['event'])
            if 'guest' in self.json_data:
                return jinja2.Markup('Anzahlung für {} für {}'.format(event.__html__(), jinja2.escape(event.person(self.json_data['guest']))))
            else:
                return jinja2.Markup('Anzahlung für {}'.format(event.__html__()))
        elif self.json_data['type'] == 'eventAnzahlungReturn':
            import gefolge_web.event.model

            event = gefolge_web.event.model.Event(self.json_data['event'])
            return jinja2.Markup('{}Rückzahlung der erhöhten Anzahlung für {}{}'.format('Teilweise ' if self.json_data['extraRemaining'] > 0 else '', event.__html__(), ' (noch {})'.format(Euro(self.json_data['extraRemaining'])) if self.json_data['extraRemaining'] > 0 else ''))
        elif self.json_data['type'] == 'payPal':
            return jinja2.Markup('PayPal-Überweisung')
        elif self.json_data['type'] == 'transfer':
            import gefolge_web.login

            mensch = gefolge_web.login.Mensch(self.json_data['mensch'])
            return jinja2.Markup('{} {} übertragen'.format('von' if self.amount > Euro() else 'an', mensch.__html__()))
        elif self.json_data['type'] == 'sponsorWerewolfCard':
            try:
                import werewolf_web
            except ImportError:
                return jinja2.Markup('<i>Werwölfe</i>-Karte gesponsert: {}'.format(jinja2.escape(self.json_data['role'])))
            else:
                return jinja2.Markup('<a href="{}"><i>Werwölfe</i>-Karte</a> gesponsert: <span style="color: {};">{}</span>'.format(flask.url_for('werewolf_cards'), werewolf_web.FACTION_COLORS.get(self.json_data['faction'], 'black'), jinja2.escape(self.json_data['role'])))
        else:
            raise NotImplementedError('transaction type {} not implemented'.format(self.json_data['type']))

    def __repr__(self):
        return 'gefolge_web.util.Transaction({!r})'.format(self.json_data)

    @property
    def amount(self):
        return Euro(self.json_data['amount'])

    @property
    def details(self):
        if 'details' in self.json_data:
            return jinja2.Markup('<ul>\n{}\n</ul>'.format('\n'.join(
                '<li>{}: {}</li>'.format(detail['label'], {
                    'flat': lambda detail: '{}'.format(Euro(detail['amount'])),
                    'even': lambda detail: '{} ({} / {} Menschen)'.format(Euro(detail['amount']), Euro(detail['total']), detail['people']),
                    'weighted': lambda detail: '{} ({} * {} / {} Übernachtungen)'.format(Euro(detail['amount']), Euro(detail['total']), detail['nightsAttended'], detail['nightsTotal'])
                }[detail['type']](detail))
                for detail in self.json_data['details']
            )))

    @property
    def time(self):
        return parse_iso_datetime(self.json_data['time'], tz=pytz.utc).astimezone(pytz.timezone('Europe/Berlin'))

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

def render_template(template_name=None, **kwargs):
    if template_name is None:
        template_path = '{}.html'.format(flask.request.endpoint.replace('.', '/'))
    else:
        template_path = '{}.html'.format(template_name.replace('.', '/'))
    return jinja2.Markup(flask.render_template(template_path, **kwargs))

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
    def dmy_hms(value):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        if isinstance(value, str):
            value = parse_iso_datetime(value)
        return '{:%d.%m.%Y %H:%M:%S}'.format(value)

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
        sequence = list(map(jinja2.escape, value))
        if len(sequence) == 0:
            raise IndexError('Tried to join empty sequence')
        elif len(sequence) == 1:
            return sequence[0]
        elif len(sequence) == 2:
            return jinja2.Markup('{} und {}'.format(sequence[0], sequence[1]))
        else:
            return jinja2.Markup(', '.join(sequence[:-1]) + ' und {}'.format(sequence[-1]))

    @app.template_filter()
    def next_date(value):
        if isinstance(value, lazyjson.Node):
           value = value.value()
        if isinstance(value, str):
           value = parse_iso_date(value)
        return value + datetime.timedelta(days=1)

    @app.template_filter()
    def nl2br(value): #FROM http://flask.pocoo.org/snippets/28/ (modified)
        return jinja2.Markup('\n'.join(
            '<p>{}</p>'.format(p.replace('\n', '<br />\n'))
            for p in PARAGRAPH_RE.split(jinja2.escape(value))
        ))

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
            context = f(*args, **kwargs)
            if context is None:
                context = {}
            elif not isinstance(context, dict):
                return context
            return render_template(template_name, **context)

        return wrapper

    return decorator

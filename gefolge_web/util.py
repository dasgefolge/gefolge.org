import copy
import datetime
import decimal
import enum
import functools
import inspect
import pathlib
import re
import subprocess
import traceback

import dateutil.parser # PyPI: python-dateutil
import flask # PyPI: Flask
import jinja2 # PyPI: Jinja2
import more_itertools # PyPI: more-itertools
import pytz # PyPI: pytz
import simplejson # PyPI: simplejson

import class_key # https://github.com/fenhl/python-class-key
import lazyjson # https://github.com/fenhl/lazyjson
import snowflake # https://github.com/fenhl/python-snowflake

BASE_PATH = pathlib.Path('/usr/local/share/fidera') #TODO use basedir
CONFIG_PATH = BASE_PATH / 'config.json'
DISCORD_EPOCH = 1420070400000
EDIT_LOG = BASE_PATH / 'web.jlog'
PARAGRAPH_RE = re.compile(r'(?:\r\n|\r|\n){2,}')

CRASH_NOTICE = """To: fenhl@fenhl.net
From: {whoami}@{hostname}
Subject: gefolge.org internal server error

An internal server error occurred on gefolge.org.
User: {user}
URL: {url}
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

class OrderedEnum(enum.Enum):
    def __ge__(self, other):
        if self.__class__ is other.__class__:
            return self.value >= other.value
        return NotImplemented

    def __gt__(self, other):
        if self.__class__ is other.__class__:
            return self.value > other.value
        return NotImplemented

    def __le__(self, other):
        if self.__class__ is other.__class__:
            return self.value <= other.value
        return NotImplemented

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented

class Transaction:
    def __init__(self, json_data):
        self.json_data = json_data

    @classmethod
    def anzahlung(cls, event, amount=None, *, guest=None, time=None):
        if time is None:
            time = now(pytz.utc)
        if amount is None:
            amount = -event.anzahlung
        json_data = {
            'type': 'eventAnzahlung',
            'amount': amount.value,
            'default': -event.anzahlung.value,
            'time': '{:%Y-%m-%dT%H:%M:%SZ}'.format(time.astimezone(pytz.utc)),
            'event': event.event_id
        }
        if guest is not None:
            json_data['guest'] = guest.snowflake
        return cls(json_data)

    @classmethod
    def anzahlung_return(cls, event, remaining, amount):
        return cls({
            'type': 'eventAnzahlungReturn',
            'amount': amount.value,
            'extraRemaining': remaining.value,
            'time': '{:%Y-%m-%d H:%M:%S}'.format(now(pytz.utc)),
            'event': event.event_id
        })

    @classmethod
    def sponsor_werewolf_card(cls, card, amount):
        return cls({
            'type': 'sponsorWerewolfCard',
            'amount': -amount.value,
            'time': '{:%Y-%m-%dT%H:%M:%SZ}'.format(now(pytz.utc)),
            'faction': card['faction'],
            'role': card['role']
        })

    @classmethod
    def transfer(cls, mensch, amount, comment=None):
        json_data = {
            'type': 'transfer',
            'amount': amount.value,
            'time': '{:%Y-%m-%dT%H:%M:%SZ}'.format(now(pytz.utc)),
            'mensch': mensch.snowflake
        }
        if comment:
            json_data['comment'] = comment
        return cls(json_data)

    @classmethod
    def wurstmineberg(cls, amount):
        return cls({
            'type': 'wurstmineberg',
            'amount': -amount.value,
            'time': '{:%Y-%m-%dT%H:%M:%SZ}'.format(now(pytz.utc))
        })

    def __html__(self):
        if self.json_data['type'] == 'bankTransfer':
            return jinja2.Markup('Überweisung')
        elif self.json_data['type'] == 'bar':
            return jinja2.Markup('bar')
        elif self.json_data['type'] == 'eventAbrechnung':
            import gefolge_web.event.model

            try:
                event = gefolge_web.event.model.Event(self.json_data['event'])
            except FileNotFoundError:
                event = jinja2.Markup('abgesagtes event <code>{}</code>'.format(jinja2.escape(self.json_data['event'])))
            if 'guest' in self.json_data:
                return jinja2.Markup('Abrechnung von {} für {}'.format(event.__html__(), jinja2.escape(event.person(self.json_data['guest']))))
            else:
                return jinja2.Markup('Abrechnung von {}'.format(event.__html__()))
        elif self.json_data['type'] == 'eventAnzahlung':
            import gefolge_web.event.model

            try:
                event = gefolge_web.event.model.Event(self.json_data['event'])
            except FileNotFoundError:
                event = jinja2.Markup('abgesagtes event <code>{}</code>'.format(jinja2.escape(self.json_data['event'])))
            if 'guest' in self.json_data:
                return jinja2.Markup('Anzahlung für {} für {}'.format(event.__html__(), jinja2.escape(event.person(self.json_data['guest']))))
            else:
                return jinja2.Markup('Anzahlung für {}'.format(event.__html__()))
        elif self.json_data['type'] == 'eventAnzahlungReturn':
            import gefolge_web.event.model

            try:
                event = gefolge_web.event.model.Event(self.json_data['event'])
            except FileNotFoundError:
                event = jinja2.Markup('abgesagtes event <code>{}</code>'.format(jinja2.escape(self.json_data['event'])))
            return jinja2.Markup('{}Rückzahlung der erhöhten Anzahlung für {}{}'.format('Teilweise ' if self.json_data['extraRemaining'] > 0 else '', event.__html__(), ' (noch {})'.format(Euro(self.json_data['extraRemaining'])) if self.json_data['extraRemaining'] > 0 else ''))
        elif self.json_data['type'] == 'payPal':
            return jinja2.Markup('PayPal-Überweisung')
        elif self.json_data['type'] == 'sponsorWerewolfCard':
            try:
                import werewolf_web # extension for Werewolf games, closed-source to allow the admin to make relevant changes before a game without giving away information to players
            except ImportError:
                return jinja2.Markup('<i>Werwölfe</i>-Karte gesponsert: {}'.format(jinja2.escape(self.json_data['role'])))
            else:
                return jinja2.Markup('<a href="{}"><i>Werwölfe</i>-Karte</a> gesponsert: <span style="color: {};">{}</span>'.format(flask.url_for('werewolf_cards'), werewolf_web.FACTION_COLORS.get(self.json_data['faction'], 'black'), jinja2.escape(self.json_data['role'])))
        elif self.json_data['type'] == 'transfer':
            import gefolge_web.login

            mensch = gefolge_web.login.Mensch(self.json_data['mensch'])
            return jinja2.Markup('{} {} übertragen'.format('von' if self.amount > Euro() else 'an', mensch.__html__()))
        elif self.json_data['type'] == 'wurstmineberg':
            return jinja2.Markup('an <a href="https://wurstmineberg.de/">Wurstmineberg</a> übertragen')
        else:
            raise NotImplementedError('transaction type {} not implemented'.format(self.json_data['type']))

    def __repr__(self):
        return 'gefolge_web.util.Transaction({!r})'.format(self.json_data)

    @property
    def amount(self):
        return Euro(self.json_data['amount'])

    @property
    def details(self):
        import gefolge_web.login

        if self.json_data['type'] == 'eventAbrechnung':
            if 'details' in self.json_data:
                return jinja2.Markup(', Details:<br /><ul>\n{}\n</ul>'.format('\n'.join(
                    '<li>{}{}: {}</li>'.format(detail['label'], ' {}'.format(gefolge_web.login.Mensch(detail['snowflake']).__html__()) if 'snowflake' in detail else '', {
                        'flat': lambda detail: ('{} ({})'.format(Euro(detail['amount']), jinja2.escape(detail['note'])) if 'note' in detail else '{}'.format(Euro(detail['amount']))),
                        'even': lambda detail: '{} ({} / {} Menschen)'.format(Euro(detail['amount']), Euro(detail['total']), detail['people']),
                        'weighted': lambda detail: '{} ({} * {} / {} Übernachtungen)'.format(Euro(detail['amount']), Euro(detail['total']), detail['nightsAttended'], detail['nightsTotal'])
                    }[detail['type']](detail))
                    for detail in self.json_data['details']
                )))
        elif self.json_data['type'] == 'transfer':
            if self.json_data.get('comment'):
                return jinja2.Markup(', Kommentar:<br /><blockquote style="margin-bottom: 0;"><p>{}</p></blockquote>'.format(jinja2.escape(self.json_data['comment'])))
        return ''

    @property
    def time(self):
        return parse_iso_datetime(self.json_data['time'], tz=pytz.utc)

def cached_json(file):
    try:
        if not hasattr(flask.g, 'json_cache'):
            flask.g.json_cache = {}
    except RuntimeError:
        return file
    else:
        return lazyjson.CachedFile(flask.g.json_cache, file)

def date_range(start, end):
    date = start
    while date < end:
        yield date
        date += datetime.timedelta(days=1)

def jlog_append(line, log_path):
    with log_path.open('a') as log_f:
        simplejson.dump(line, log_f, sort_keys=True)
        print(file=log_f)

def log(event_type, event):
    event = copy.copy(event)
    event['by'] = flask.g.user.snowflake
    event['time'] = '{:%Y-%m-%dT%H:%M:%SZ}'.format(now(pytz.utc))
    event['type'] = event_type
    jlog_append(event, EDIT_LOG)

def notify_crash(exc=None):
    whoami = subprocess.run(['whoami'], stdout=subprocess.PIPE, check=True).stdout.decode('utf-8').strip()
    hostname = subprocess.run(['hostname', '-f'], stdout=subprocess.PIPE, check=True).stdout.decode('utf-8').strip()
    try:
        user = str(flask.g.user)
    except Exception:
        user = None
    try:
        url = str(flask.g.view_node.url)
    except Exception:
        url = None
    mail_text = CRASH_NOTICE.format(whoami=whoami, hostname=hostname, user=user)
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
    result = dateutil.parser.isoparse(datetime_str)
    if result.tzinfo is not None and result.tzinfo.utcoffset(result) is not None: # result is timezone-aware
        return result.astimezone(tz)
    else:
        return tz.localize(result, is_dst=None)

def render_template(template_name=None, **kwargs):
    if template_name is None:
        template_path = '{}.html.j2'.format(flask.request.endpoint.replace('.', '/'))
    else:
        template_path = '{}.html.j2'.format(template_name.replace('.', '/'))
    return jinja2.Markup(flask.render_template(template_path, **kwargs))

def setup(app):
    for error_code in {403, 404}:
        app.register_error_handler(error_code, lambda e: (render_template('error.{}'.format(error_code)), error_code))

    @app.errorhandler(500)
    def internal_server_error(e):
        try:
            notify_crash(e)
        except Exception:
            reported = False
        else:
            reported = True
        return render_template('error.500', reported=reported), 500

    @app.template_filter()
    def dt_format(value, format='%d.%m.%Y %H:%M:%S', event_timezone=None):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        if isinstance(value, str):
            value = parse_iso_datetime(value)
        if hasattr(value, 'astimezone'):
            return render_template('datetime-format', local_timestamp=value, utc_timestamp=value.astimezone(pytz.utc), format=format, event_timezone=event_timezone)
        else:
            return value.strftime(format)

    @app.template_filter()
    def dm(value, event_timezone=None):
        return dt_format(value, '%d.%m.', event_timezone=event_timezone)

    @app.template_filter()
    def dmy(value, event_timezone=None):
        return dt_format(value, '%d.%m.%Y', event_timezone=event_timezone)

    @app.template_filter()
    def dmy_hm(value, event_timezone=None):
        return dt_format(value, '%d.%m.%Y %H:%M', event_timezone=event_timezone)

    @app.template_filter()
    def dmy_hms(value, event_timezone=None):
        return dt_format(value, '%d.%m.%Y %H:%M:%S', event_timezone=event_timezone)

    @app.template_filter()
    def hm(value, event_timezone=None):
        return dt_format(value, '%H:%M', event_timezone=event_timezone)

    @app.template_filter()
    def length(value):
        try:
            return len(value)
        except TypeError:
            return more_itertools.ilen(value)

    @app.template_filter()
    def melt(value):
        if isinstance(value, lazyjson.Node):
            value = value.value()
        value = int(value)
        timestamp, data_center, worker, sequence = snowflake.melt(value, twepoch=DISCORD_EPOCH)
        return pytz.utc.localize(datetime.datetime.fromtimestamp(timestamp / 1000))

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
        reboot_info = cached_json(lazyjson.File('/opt/dev/reboot.json')).value()
        if 'schedule' in reboot_info:
            flask.g.reboot_timestamp = parse_iso_datetime(reboot_info['schedule'], tz=pytz.utc)
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

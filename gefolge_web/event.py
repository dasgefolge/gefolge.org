import decimal
import flask
import flask_wtf
import functools
import lazyjson
import pathlib
import pytz
import random
import re
import wtforms
import wtforms.validators

import gefolge_web.login
import gefolge_web.util

EVENTS_ROOT = pathlib.Path('/usr/local/share/fidera/event')

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

class Guest:
    def __init__(self, event, guest_id):
        self.event = event
        self.snowflake = int(guest_id) # not actually a snowflake but uses this variable name for compatibility with the Mensch class

    def __eq__(self, other):
        return hasattr(other, 'snowflake') and self.snowflake == other.snowflake

    def __hash__(self):
        return hash(self.snowflake)

    def __repr__(self):
        return 'gefolge_web.event.Guest({!r}, {!r})'.format(self.event, self.snowflake)

    def __str__(self):
        return self.event.attendee_data(self)['name'].value()

    @property
    def via(self):
        return gefolge_web.login.Mensch(self.event.attendee_data(self)['via'].value())

class EuroField(wtforms.StringField):
    """A form field that validates to the Euro class. Some code derived from wtforms.DecimalField."""
    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        elif self.data is not None:
            return str(self.data.value)
        else:
            return ''

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = Euro(valuelist[0].replace(' ', '').replace(',', '.').strip('€'))
            except (decimal.InvalidOperation, ValueError) as e:
                self.data = None
                raise ValueError('Ungültiger Eurobetrag') from e

def ConfirmSignupForm(event):
    def validate_verwendungszweck(form, field):
        match = re.fullmatch('Anzahlung {} ([0-9]+)'.format(event.event_id), field.data)
        if not match:
            raise wtforms.validators.ValidationError('Verwendungszweck ist keine Anzahlung für dieses event.')
        if len(match.group(1)) < 3:
            guest = Guest(event, match.group(1))
            if guest not in event.guests:
                raise wtforms.validators.ValidationError('Es ist kein Gast mit dieser Nummer für dieses event eingetragen.')
            if guest in event.signups:
                raise wtforms.validators.ValidationError('Dieser Gast ist bereits für dieses event angemeldet.')
        else:
            mensch = gefolge_web.login.Mensch(match.group(1))
            if not mensch.is_active:
                raise wtforms.validators.ValidationError('Dieser Mensch ist nicht im Gefolge Discord server.')
            if mensch in event.menschen:
                raise wtforms.validators.ValidationError('Dieser Mensch ist bereits für dieses event angemeldet.')

    class Form(flask_wtf.FlaskForm):
        betrag = EuroField('Betrag', [wtforms.validators.InputRequired(), wtforms.validators.NumberRange(min=event.anzahlung, max=event.anzahlung)])
        verwendungszweck = wtforms.StringField('Verwendungszweck', [validate_verwendungszweck])

    return Form()

def SignupGuestForm(event):
    def validate_guest_name(form, field):
        name = field.data.strip()
        if any(str(guest) == name for guest in event.guests):
            raise wtforms.validators.ValidationError('Ein Gast mit diesem Namen ist bereits angemeldet.')

    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Name', [wtforms.validators.DataRequired(), validate_guest_name])

class Event:
    def __init__(self, event_id):
        self.event_id = event_id

    def __repr__(self):
        return 'gefolge_web.event.Event({!r})'.format(self.event_id)

    def __str__(self):
        return self.data.get('name', self.event_id)

    @property
    def anzahlung(self):
        if 'anzahlung' in self.data:
            return Euro(self.data['anzahlung'].value())
        else:
            return Euro()

    def attendee_data(self, person):
        for iter_data in self.data['menschen']:
            if iter_data['id'].value() == person.snowflake:
                return iter_data

    @property
    def ausfall(self):
        if 'ausfall' in self.data:
            return Euro(self.data['ausfall'].value())
        else:
            return Euro()

    @property
    def data(self):
        return lazyjson.File(EVENTS_ROOT / '{}.json'.format(self.event_id))

    @property
    def end(self):
        return gefolge_web.util.parse_iso_datetime(self.data['end'].value())

    @property
    def end_str(self):
        return '{:%d.%m.%Y %H:%M}'.format(self.end)

    @property
    def guests(self):
        return [
            Guest(self, person['id'].value())
            for person in self.data['menschen']
            if 'via' in person
        ]

    @property
    def menschen(self):
        return [
            gefolge_web.login.Mensch(person['id'].value())
            for person in self.data['menschen']
            if 'via' not in person
        ]

    def orga(self, aufgabe):
        for mensch in self.data['menschen']:
            if aufgabe in mensch.get('orga', []):
                return gefolge_web.login.Mensch(mensch['id'].value())

    def signup(self, mensch):
        self.data['menschen'].append({
            'id': mensch.snowflake,
            'signup': '{:%Y-%m-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
        })

    def signup_guest(self, mensch, guest_name):
        if any(str(guest) == guest_name for guest in self.guests):
            raise ValueError('Duplicate guest name: {!r}'.format(guest_name))
        available_ids = [i for i in range(100) if not any(guest.snowflake == i for guest in self.guests)]
        guest_id = random.choice(available_ids)
        self.data['menschen'].append({
            'id': guest_id,
            'name': guest_name,
            'via': mensch.snowflake
        })
        return guest_id

    @property
    def signups(self):
        """Returns everyone who has completed signup, including guests, in order of signup."""
        result = {
            guest: self.attendee_data(guest)['signup'].value()
            for guest in self.guests
            if 'signup' in self.attendee_data(guest)
        }
        result += {
            mensch: self.attendee_data(mensch)['signup'].value()
            for mensch in self.menschen
        }
        return [person for person, signup in sorted(result.items(), key=lambda kv: kv[1])]

    @property
    def start(self):
        return gefolge_web.util.parse_iso_datetime(self.data['start'].value())

    @property
    def start_str(self):
        return '{:%d.%m.%Y %H:%M}'.format(self.start)

    @property
    def url_part(self):
        return self.event_id

def setup(app):
    @app.template_test('guest')
    def is_guest(value):
        if hasattr(value, 'snowflake'):
            value = value.snowflake
        return int(value) < 100

    @app.route('/event')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('event', 'events'))
    @gefolge_web.util.template('events-index')
    def events_index():
        return {
            'events_list': [
                Event(event_path.stem)
                for event_path in sorted(EVENTS_ROOT.iterdir(), key=lambda event: lazyjson.File(event)['start'].value())
            ]
        }

    @app.route('/event/<event_id>', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(Event, events_index)
    @gefolge_web.util.template('event')
    def event_page(event_id):
        event = Event(event_id)
        confirm_signup_form = ConfirmSignupForm(event)
        if confirm_signup_form.validate_on_submit():
            snowflake = int(re.fullmatch('Anzahlung {} ([0-9]+)'.format(event_id), confirm_signup_form.verwendungszweck.data).group(1))
            if snowflake < 100:
                guest = Guest(event, snowflake)
                event.attendee_data(guest)['signup'] = '{:%Y-%m-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
            else:
                mensch = gefolge_web.login.Mensch()
                event.signup(mensch)
            return flask.redirect(flask.url_for('event_page', event_id=event_id))
        return {
            'event': event,
            'confirm_signup_form': confirm_signup_form
        }

    @app.route('/event/<event_id>/guest', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('guest', 'Gast anmelden'), event_page)
    def event_guest_form(event_id):
        event = Event(event_id)
        signup_guest_form = SignupGuestForm(event)
        if signup_guest_form.validate_on_submit():
            guest_name = signup_guest_form.name.data.strip()
            guest_id = event.signup_guest(flask.g.user, guest_name)
            return flask.render_template('event-guest-confirm.html', event=event, guest_id=guest_id, guest_name=guest_name)
        else:
            return flask.render_template('event-guest-form.html', event=event, signup_guest_form=signup_guest_form)

    @app.route('/event/<event_id>/mensch')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('mensch', 'Menschen'), event_page)
    @gefolge_web.util.template('event-menschen')
    def event_menschen(event_id):
        return {'event': Event(event_id)}

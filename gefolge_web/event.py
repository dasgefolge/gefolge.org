import decimal
import flask_wtf
import lazyjson
import pathlib
import pytz
import re
import wtforms
import wtforms.validators

import gefolge_web.login
import gefolge_web.util

EVENTS_ROOT = pathlib.Path('/usr/local/share/fidera/event')

class Euro:
    def __init__(self, value=0):
        self.value = decimal.Decimal(value)
        if self.value.quantize(decimal.Decimal('1.00')) != self.value:
            raise ValueError('Euro value contains fractional cents')

    def __str__(self):
        return '{:.2f}€'.format(self.value).replace('.', ',')

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

class ConfirmSignupForm(flask_wtf.FlaskForm):
    betrag = EuroField('Betrag', [wtforms.validators.Required()])
    verwendungszweck = wtforms.StringField('Verwendungszweck')

class Event:
    def __init__(self, event_id):
        self.event_id = event_id

    def __str__(self):
        return self.data.get('name', self.event_id)

    @property
    def anzahlung(self):
        if 'anzahlung' in self.data:
            return Euro(self.data['anzahlung'].value())
        else:
            return Euro()

    def attendee_data(self, mensch):
        for iter_data in self.data['menschen'].value():
            if iter_data['id'] == mensch.snowflake:
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
    def menschen(self):
        return [
            gefolge_web.login.Mensch(mensch['id'].value())
            for mensch in self.data['menschen']
        ]

    def orga(self, aufgabe):
        for mensch in self.data['menschen']:
            if aufgabe in mensch.get('orga', []):
                return gefolge_web.login.Mensch(mensch['id'].value())

    def signup(self, mensch):
        self.data['menschen'].append({
            'id': mensch.snowflake,
            'signup': '{:%Y-%M-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
        })

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
        confirm_signup_form = ConfirmSignupForm()
        if confirm_signup_form.validate_on_submit():
            match = re.fullmatch('Anzahlung {} ([0-9]+)'.format(event_id), form.verwendungszweck.data)
            if not match:
                raise ValueError('Verwendungszweck ist keine Anzahlung für dieses event')
            mensch = gefolge_web.login.Mensch(match.group(1))
            if not mensch.is_active:
                raise ValueError('Mensch mit dieser snowflake ist nicht im Gefolge Discord server')
            if mensch in event.menschen:
                raise ValueError('Dieser Mensch ist bereits für dieses event angemeldet')
            if form.betrag.data < event.anzahlung:
                raise ValueError('Betrag der Anzahlung zu niedrig')
            if form.betrag.data > event.anzahlung:
                raise ValueError('Betrag der Anzahlung zu hoch')
            event.signup(mensch)
            return flask.redirect(flask.url_for('event_page', event_id=event_id))
        return {
            'event': event,
            'confirm_signup_form': confirm_signup_form
        }

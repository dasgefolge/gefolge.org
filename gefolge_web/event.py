import decimal
import lazyjson
import pathlib

import gefolge_web.login
import gefolge_web.util

EVENTS_ROOT = pathlib.Path('/usr/local/share/fidera/event')

class Euro:
    def __init__(self, value):
        self.value = decimal.Decimal(value)
        assert self.value.quantize(decimal.Decimal('1.00')) == self.value

    def __str__(self):
        return '{:.2f}€'.format(self.value).replace('.', ',')

class Event:
    def __init__(self, event_id):
        self.event_id = event_id

    @property
    def anzahlung(self):
        if 'anzahlung' in self.data:
            return Euro(self.data['anzahlung'].value())

    @property
    def ausfall(self):
        if 'ausfall' in self.data:
            return Euro(self.data['ausfall'].value())

    @property
    def data(self):
        return lazyjson.File(EVENTS_ROOT / '{}.json'.format(self.event_id))

    @property
    def end(self):
        return gefolge_web.util.parse_iso_datetime(self.data['end'].value(), tz=pytz.timezone('Europe/Berlin'))

    @property
    def end_str(self):
        return '{:%d.%m.%Y %H:%M}'.format(self.end)

    @property
    def name(self):
        return self.data['name'].value()

    @property
    def start(self):
        return gefolge_web.util.parse_iso_datetime(self.data['start'].value(), tz=pytz.timezone('Europe/Berlin'))

    @property
    def start_str(self):
        return '{:%d.%m.%Y %H:%M}'.format(self.start)

def setup(app):
    @app.route('/event')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('events-index')
    def events_index():
        return {
            'events_list': [
                (event.stem, lazyjson.File(event)['name'])
                for event in sorted(EVENTS_ROOT.iterdir(), key=lambda event: lazyjson.File(event)['start'].value())
            ]
        }

    @app.route('/event/<event_id>')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('event')
    def event_page(event_id):
        return {'event': Event(event_id)}

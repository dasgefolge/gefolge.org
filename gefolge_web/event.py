import lazyjson
import pathlib

import gefolge_web.login
import gefolge_web.util

EVENTS_ROOT = pathlib.Path('/usr/local/share/fidera/event')

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

    @app.route('/event/<event_name>')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('event')
    def event_page(event_id):
        return {
            'event_data': get_event_data(event_id),
            'event_id': event_id
        }

def get_event_data(event_id):
    event_data_path = EVENTS_ROOT / '{}.json'.format(event_id)
    if event_data_path.exists():
        return lazyjson.File(event_data)

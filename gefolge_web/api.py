import functools

import flask # PyPI: Flask
import flask_login # PyPI: Flask-Login
import icalendar # PyPI: icalendar

import gefolge_web.event.model
import gefolge_web.event.programm
import gefolge_web.login
import gefolge_web.util

DISCORD_VOICE_STATE_PATH = gefolge_web.util.BASE_PATH / 'discord' / 'voice-state.json'

def key_or_member_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if flask_login.current_user.is_active:
            flask.g.user = flask_login.current_user
        elif gefolge_web.login.Mensch.by_api_key() is not None:
            flask.g.user = gefolge_web.login.Mensch.by_api_key()
        else:
            flask.g.user = gefolge_web.login.AnonymousUser()
        if flask.g.user is not None and flask.g.user.is_active:
            return f(*args, **kwargs)
        return flask.Response(
            'Sie haben keinen Zugriff auf diesen Inhalt, weil Sie nicht im Gefolge Discord server sind oder den API key noch nicht eingegeben haben.',
            401,
            {'WWW-Authenticate': 'Basic realm="gefolge.org API key required"'}
        ) #TODO template

    return wrapper

def setup(index):
    @index.child('api', 'API', decorators=[key_or_member_required])
    @gefolge_web.util.template('api-docs')
    def api_index():
        return {}

    @api_index.child('calendar')
    @gefolge_web.util.template('api-dir')
    def api_calendars_index():
        return {}

    @api_calendars_index.child('signups.ics')
    def calendar_signups():
        """Ein Kalender im iCalendar-Format mit allen events und Programmpunkten, für die du angemeldet bist."""
        cal = icalendar.Calendar()
        cal.add('prodid', '-//Gefolge//gefolge.org//DE')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'gefolge.org')
        for event in gefolge_web.event.model.Event:
            if event.start is not None and flask.g.user in event.signups:
                cal.add_component(event.to_ical())
                for calendar_event in event.calendar:
                    if calendar_event.programmpunkt is None or calendar_event.programmpunkt.orga == flask.g.user or flask.g.user in calendar_event.programmpunkt.signups:
                        cal.add_component(calendar_event.to_ical())
        return flask.Response(cal.to_ical(), mimetype='text/calendar')

    @api_index.child('discord')
    @gefolge_web.util.template('api-dir')
    def api_discord_index():
        return {}

    @api_discord_index.child('voice-state.json')
    def discord_voice_state():
        """Infos, wer gerade in welchen voice channels ist."""
        with DISCORD_VOICE_STATE_PATH.open() as f:
            return flask.Response(f.read(), mimetype='application/json')

    @api_index.child('event')
    @gefolge_web.util.template('api-dir')
    def api_events_index():
        return {}

    @api_events_index.children(gefolge_web.event.model.Event)
    @gefolge_web.util.template('api-dir')
    def api_event(event):
        return {}

    @api_event.catch_init(FileNotFoundError)
    def api_event_catch_init(exc, value):
        return gefolge_web.util.render_template('event.404', event_id=value), 404

    @api_event.child('calendar')
    @gefolge_web.util.template('api-dir')
    def event_calendars(event):
        return {}

    @event_calendars.child('all.ics')
    def event_calendar_all(event):
        """Ein Kalender im iCalendar-Format mit allen Programmpunkten von diesem event."""
        cal = icalendar.Calendar()
        cal.add('prodid', '-//Gefolge//gefolge.org//DE')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', str(event))
        for calendar_event in event.calendar:
            cal.add_component(calendar_event.to_ical())
        return flask.Response(cal.to_ical(), mimetype='text/calendar')

    @api_event.child('overview.json')
    def api_event_overview(event):
        """Infos zu diesem event im auf https://gefolge.org/wiki/event-json/meta dokumentierten Format."""

        def cal_event_json(calendar_event):
            result = {
                'end': f'{calendar_event.end:%Y-%m-%dT%H:%M:%S}',
                'ibSubtitle': calendar_event.info_beamer_subtitle,
                'start': f'{calendar_event.start:%Y-%m-%dT%H:%M:%S}',
                'subtitle': calendar_event.subtitle,
                'text': str(calendar_event)
            }
            if isinstance(calendar_event.programmpunkt, gefolge_web.event.programm.Programmpunkt):
                result['programmpunkt'] = calendar_event.programmpunkt.url_part
            return result

        def person_json(person):
            attendee_data = event.attendee_data(person)
            result = {
                'bedsheets': attendee_data.get('bedsheets', 1),
                'id': person.snowflake,
                'nights': {
                    f'{night:%Y-%m-%d}': {
                        'going': event.night_going(person, night),
                        'lastUpdated': None if event.night_status_change(person, night) is None else f'{event.night_status_change(person, night):%Y-%m-%dT%H:%M:%SZ}'
                    } for night in event.nights
                },
                'orga': attendee_data.get('orga', [])
            }
            if person == flask.g.user or (person.is_guest and person.via == flask.g.user) or event.can_edit(flask.g.user, person):
                result['alkohol'] = attendee_data.get('alkohol', True)
                result['selbstversorger'] = attendee_data.get('selbstversorger', False)
            if (person == flask.g.user or person == event.orga('Abrechnung')):
                if 'konto' in attendee_data:
                    result['konto'] = attendee_data['konto'].value()
                elif (not person.is_guest) and 'konto' in person.userdata:
                    result['konto'] = person.userdata['konto'].value()
            if person.is_guest:
                result['name'] = str(person)
                result['via'] = person.via.snowflake
            if flask.g.user == person or flask.g.user == event.orga('Abrechnung'):
                for night in event.nights:
                    result['nights'][f'{night:%Y-%m-%d}']['log'] = event.night_log(person, night)
                result['paid'] = attendee_data.get('paid', {})
            return result

        def programmpunkt_json(programmpunkt):
            return {
                'name': programmpunkt.name,
                'signups': [signup.snowflake for signup in programmpunkt.signups]
            }

        result = {
            'name': str(event),
            'menschen': [person_json(person) for person in event.signups],
            'programm': {programmpunkt.url_part: programmpunkt_json(programmpunkt) for programmpunkt in event.programm},
            'calendarEvents': [cal_event_json(cal_event) for cal_event in event.calendar]
        }
        if event.anzahlung is not None:
            result['anzahlung'] = event.anzahlung.value
        if event.location is not None and event.location.is_online:
            result['capacity'] = None
        else:
            result['capacity'] = {f'{night:%Y-%m-%d}': event.capacity(night) for night in event.nights}
        if event.end is not None:
            result['end'] = f'{event.end:%Y-%m-%dT%H:%M:%S}'
        if event.location is not None:
            if event.location.is_online:
                result['location'] = 'online'
            else:
                result['location'] = event.location.data.value()
                result['location']['id'] = event.location.loc_id
        if event.start is not None:
            result['start'] = f'{event.start:%Y-%m-%dT%H:%M:%S}'
        return result

    @api_index.child('websocket')
    def api_websocket():
        """Ein websocket server für länger dauernde Verbindungen. Dokumentation siehe https://github.com/dasgefolge/gefolge-websocket"""
        raise NotImplementedError('Websocket should be directed to gefolge-websocket server by nginx')

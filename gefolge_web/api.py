import flask
import flask_login
import functools
import icalendar

import gefolge_web.event.model
import gefolge_web.login
import gefolge_web.util

def key_or_member_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if flask_login.current_user.is_active:
            flask.g.user = flask_login.current_user
        elif gefolge_web.login.Mensch.by_api_key() is not None:
            flask.g.user = gefolge_web.login.Mensch.by_api_key()
        else:
            flask.g.user is None
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
        cal = icalendar.Calendar()
        cal.add('prodid', '-//Gefolge//gefolge.org//DE')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'gefolge.org')
        for event in gefolge_web.event.model.Event:
            if flask.g.user in event.signups:
                cal.add_component(event.to_ical())
                for programmpunkt in event.programm:
                    if flask.g.user in programmpunkt.signups and programmpunkt.start is not None and programmpunkt.end is not None:
                        cal.add_component(programmpunkt.to_ical())
        return flask.Response(cal.to_ical(), mimetype='text/calendar')

    @api_index.child('event')
    @gefolge_web.util.template('api-dir')
    def api_events_index():
        return {}

    @api_events_index.children(gefolge_web.event.model.Event)
    @gefolge_web.util.template('api-dir')
    def api_event(event):
        return {}

    @api_event.child('calendar')
    @gefolge_web.util.template('api-dir')
    def event_calendars(event):
        return {}

    @event_calendars.child('all.ics')
    def event_calendar_all(event):
        cal = icalendar.Calendar()
        cal.add('prodid', '-//Gefolge//gefolge.org//DE')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', str(event))
        for programmpunkt in event.programm:
            if programmpunkt.start is not None and programmpunkt.end is not None:
                cal.add_component(programmpunkt.to_ical())
        return flask.Response(cal.to_ical(), mimetype='text/calendar')

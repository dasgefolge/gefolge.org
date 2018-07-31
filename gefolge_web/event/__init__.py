import datetime
import flask
import icalendar
import itertools
import jinja2
import math
import more_itertools
import pytz
import re

import gefolge_web.event.forms
import gefolge_web.event.model
import gefolge_web.login
import gefolge_web.util

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
            'events_list': sorted(
                gefolge_web.event.model.Event(event_path.stem)
                for event_path in gefolge_web.event.model.EVENTS_ROOT.iterdir()
            )
        }

    @app.route('/event/<event_id>', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(gefolge_web.event.model.Event, events_index)
    @gefolge_web.util.template('event')
    def event_page(event_id):
        event = gefolge_web.event.model.Event(event_id)
        confirm_signup_form = gefolge_web.event.forms.ConfirmSignupForm(event)
        if confirm_signup_form.validate_on_submit():
            snowflake = int(re.fullmatch('Anzahlung {} ([0-9]+)'.format(event_id), confirm_signup_form.verwendungszweck.data).group(1))
            if snowflake < 100:
                guest = gefolge_web.event.model.Guest(event, snowflake)
                gefolge_web.util.log('eventConfirmSignup', {
                    'event': event_id,
                    'person': snowflake
                })
                event.attendee_data(guest)['signup'] = '{:%Y-%m-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
            else:
                mensch = gefolge_web.login.Mensch(snowflake)
                event.signup(mensch)
            return flask.redirect(flask.url_for('event_page', event_id=event_id))
        programm_add_form = gefolge_web.event.forms.ProgrammAddForm(event)
        if programm_add_form.validate_on_submit():
            gefolge_web.util.log('eventProgrammAdd', {
                'event': event_id,
                'orga': programm_add_form.orga.data.snowflake,
                'programmpunkt': programm_add_form.name.data,
                'description': programm_add_form.description.data
            })
            event.data['programm'][programm_add_form.name.data] = {
                'description': programm_add_form.description.data,
                'orga': programm_add_form.orga.data.snowflake,
                'signups': []
            }
            #TODO ping Programm orga on Discord
            #TODO redirect to Programm view/edit page
        return {
            'event': event,
            'article_source': gefolge_web.wiki.get_article_source('event', event_id),
            'confirm_signup_form': confirm_signup_form,
            'programm_add_form': programm_add_form
        }

    @app.route('/event/<event_id>/calendar/all')
    @gefolge_web.login.member_required
    def event_calendar_all(event_id):
        event = gefolge_web.event.model.Event(event_id)
        cal = icalendar.Calendar()
        cal.add('prodid', '-//Gefolge//gefolge.org//DE')
        cal.add('version', '1.0')
        cal.add('x-wr-calname', str(event))
        for programmpunkt in event.programm:
            if programmpunkt.start is not None and programmpunkt.end is not None:
                cal.add_component(programmpunkt.to_ical())
        return cal.to_ical()

    @app.route('/event/<event_id>/guest', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('guest', 'Gast anmelden'), event_page)
    def event_guest_form(event_id):
        event = gefolge_web.event.model.Event(event_id)
        signup_guest_form = gefolge_web.event.forms.SignupGuestForm(event)
        if signup_guest_form.validate_on_submit():
            guest_name = signup_guest_form.name.data.strip()
            guest = event.signup_guest(flask.g.user, guest_name)
            return flask.render_template('event-guest-confirm.html', event=event, guest=guest)
        else:
            return flask.render_template('event-guest-form.html', event=event, signup_guest_form=signup_guest_form)

    @app.route('/event/<event_id>/me')
    @gefolge_web.login.member_required
    def event_me(event_id):
        return flask.redirect(flask.url_for('event_profile', event_id=event_id, snowflake=str(flask.g.user.snowflake)))

    @app.route('/event/<event_id>/me/edit')
    @gefolge_web.login.member_required
    def event_me_edit(event_id):
        return flask.redirect(flask.url_for('event_profile_edit', event_id=event_id, snowflake=str(flask.g.user.snowflake)))

    @app.route('/event/<event_id>/mensch')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('mensch', 'Menschen'), event_page)
    @gefolge_web.util.template('event-menschen')
    def event_menschen(event_id):
        return {'event': gefolge_web.event.model.Event(event_id)}

    @app.route('/event/<event_id>/mensch/<snowflake>')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(lambda event_id, snowflake: gefolge_web.event.model.Event(event_id).person(snowflake), event_menschen)
    @gefolge_web.util.template('event-profile')
    def event_profile(event_id, snowflake):
        event = gefolge_web.event.model.Event(event_id)
        return {
            'event': event,
            'person': event.person(snowflake)
        }

    @app.route('/event/<event_id>/mensch/<snowflake>/edit', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('edit', 'bearbeiten'), event_profile)
    @gefolge_web.util.template('event-profile-edit')
    def event_profile_edit(event_id, snowflake):
        event = gefolge_web.event.model.Event(event_id)
        person = event.person(snowflake)
        if not event.can_edit(flask.g.user, person):
            flask.flash('Du bist nicht berechtigt, dieses Profil zu bearbeiten.')
            return flask.redirect(flask.url_for('event_profile', event_id=event_id, snowflake=snowflake))
        profile_form = gefolge_web.event.forms.ProfileForm(event, person)
        if profile_form.validate_on_submit():
            person_data = event.attendee_data(person)
            gefolge_web.util.log('eventProfileEdit', {
                'event': event_id,
                'person': person.snowflake,
                'nights': {
                    '{:%Y-%m-%d}'.format(night): getattr(profile_form, 'night{}'.format(i)).data
                    for i, night in enumerate(event.nights)
                },
                'food': {
                    'animalProducts': profile_form.animal_products.data,
                    'allergies': profile_form.allergies.data
                }
            })
            if 'nights' not in person_data:
                person_data['nights'] = {}
            for i, night in enumerate(event.nights):
                person_data['nights']['{:%Y-%m-%d}'.format(night)] = getattr(profile_form, 'night{}'.format(i)).data
            if 'food' not in person_data:
                person_data['food'] = {}
            person_data['food']['animalProducts'] = profile_form.animal_products.data
            person_data['food']['allergies'] = profile_form.allergies.data
            return flask.redirect(flask.url_for('event_profile', event_id=event_id, snowflake=snowflake))
        else:
            return {
                'event': event,
                'person': person,
                'event_attendee_edit_form': profile_form
            }

    @app.route('/event/<event_id>/programm')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('programm', 'Programm'), event_page)
    @gefolge_web.util.template('event-programm')
    def event_programm(event_id):
        event = gefolge_web.event.model.Event(event_id)
        programm = event.programm
        filled_until = None

        def programm_cell(date, hour):
            nonlocal filled_until

            timestamp = pytz.timezone('Europe/Berlin').localize(datetime.datetime.combine(date, datetime.time(hour)), is_dst=None)
            if filled_until is not None and filled_until > timestamp:
                return '' # this cell is already filled
            if timestamp < event.start or timestamp >= event.end:
                return jinja2.Markup('<td style="background-color: #666666;"></td>')
            if any(programmpunkt.start is not None and programmpunkt.start >= timestamp and programmpunkt.start < timestamp + datetime.timedelta(hours=1) for programmpunkt in programm):
                programmpunkt = more_itertools.one(programmpunkt for programmpunkt in programm if programmpunkt.start is not None and programmpunkt.start >= timestamp and programmpunkt.start < timestamp + datetime.timedelta(hours=1))
                hours = math.ceil((programmpunkt.end - timestamp) / datetime.timedelta(hours=1))
                filled_until = timestamp + datetime.timedelta(hours=hours) #TODO support for events that go past midnight
                return jinja2.Markup('<td rowspan="{}"><a href="{}">{}</a></td>'.format(hours, flask.url_for('event_programmpunkt', event_id=event_id, name=programmpunkt.name), programmpunkt))
            return jinja2.Markup('<td></td>') # nothing planned yet

        return {
            'event': event,
            'table': {
                date: {
                    hour: programm_cell(date, hour)
                    for hour in range(24)
                }
                for date in itertools.chain(event.nights, [event.end.date()])
            }
        }

    @app.route('/event/<event_id>/programm/<name>')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(gefolge_web.event.model.Programmpunkt, event_programm)
    @gefolge_web.util.template('event-programmpunkt')
    def event_programmpunkt(event_id, name):
        event = gefolge_web.event.model.Event(event_id)
        return {
            'event': event,
            'programmpunkt': gefolge_web.event.model.Programmpunkt(event, name)
        }

    @app.route('/event/<event_id>/programm/<name>/edit', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('edit', 'bearbeiten'), event_programmpunkt)
    @gefolge_web.util.template('event-programmpunkt-edit')
    def event_programmpunkt_edit(event_id, name):
        event = gefolge_web.event.model.Event(event_id)
        programmpunkt = gefolge_web.event.model.Programmpunkt(event, name)
        if not programmpunkt.can_edit(flask.g.user):
            flask.flash('Du bist nicht berechtigt, diesen Programmpunkt zu bearbeiten.')
            return flask.redirect(flask.url_for('event_programmpunkt', event_id=event_id, name=name))
        programm_edit_form = gefolge_web.event.forms.ProgrammEditForm(programmpunkt)
        if programm_edit_form.validate_on_submit():
            gefolge_web.util.log('eventProgrammEdit', {
                'event': event_id,
                'programmpunkt': name,
                'orga': programm_edit_form.orga.data.snowflake,
                'start': (None if programm_edit_form.start.data is None else '{:%Y-%m-%d %H:%M:%S}'.format(programm_edit_form.start.data)),
                'end': (None if programm_edit_form.end.data is None else '{:%Y-%m-%d %H:%M:%S}'.format(programm_edit_form.end.data)),
                'description': programm_edit_form.description.data
            })
            programmpunkt.orga = programm_edit_form.orga.data
            programmpunkt.start = programm_edit_form.start.data
            programmpunkt.end = programm_edit_form.end.data
            programmpunkt.description = programm_edit_form.description.data
            return flask.redirect(flask.url_for('event_programmpunkt', event_id=event_id, name=name))
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programm_edit_form': programm_edit_form
            }

    @app.route('/event/<event_id>/programm/<name>/delete', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('delete', 'löschen'), event_programmpunkt)
    @gefolge_web.util.template('event-programmpunkt-delete')
    def event_programmpunkt_delete(event_id, name):
        event = gefolge_web.event.model.Event(event_id)
        programmpunkt = gefolge_web.event.model.Programmpunkt(event, name)
        if g.user != event.orga('Programm'):
            flask.flash('Du bist nicht berechtigt, diesen Programmpunkt zu löschen.')
            return flask.redirect(flask.url_for('event_programmpunkt', event_id=event_id, name=name))
        programm_delete_form = gefolge_web.event.forms.ProgrammDeleteForm(programmpunkt)
        if programm_delete_form.validate_on_submit():
            gefolge_web.util.log('eventProgrammDelete', {
                'event': event_id,
                'programmpunkt': name
            })
            del event.data['programm'][programmpunkt.name]
            return flask.redirect(flask.url_for('event_programm', event_id=event_id))
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programm_delete_form': programm_delete_form
            }

    @app.route('/event/<event_id>/programm/<name>/signup/<snowflake>')
    @gefolge_web.login.member_required
    def event_programm_signup(event_id, name, snowflake):
        event = gefolge_web.event.model.Event(event_id)
        programmpunkt = gefolge_web.event.model.Programmpunkt(event, name)
        person = event.person(snowflake)
        if not programmpunkt.can_signup(flask.g.user, person):
            flask.flash('Du bist nicht berechtigt, diese Person für diesen Programmpunkt anzumelden.')
            return flask.redirect(flask.url_for('event_programmpunkt', event_id=event_id, name=name))
        programmpunkt.signup(person)
        return flask.redirect(flask.url_for('event_programmpunkt', event_id=event_id, name=name))

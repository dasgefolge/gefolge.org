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
import gefolge_web.event.programm
import gefolge_web.login
import gefolge_web.util

def handle_profile_edit(event, person, profile_form):
    person_data = event.attendee_data(person)
    gefolge_web.util.log('eventProfileEdit', {
        'event': event.event_id,
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

def setup(index, app):
    @app.template_test('guest')
    def is_guest(value):
        if hasattr(value, 'snowflake'):
            value = value.snowflake
        return int(value) < 100

    @index.child('event', 'events', decorators=[gefolge_web.login.member_required])
    @gefolge_web.util.template('event.index')
    def events_index():
        now = gefolge_web.util.now()
        future_events, past_events = more_itertools.partition(lambda event: event.end is not None and event.end < now, gefolge_web.event.model.Event)
        return {
            'future_events': sorted(future_events),
            'past_events': sorted(past_events, reverse=True)
        }

    @events_index.children(gefolge_web.event.model.Event, methods=['GET', 'POST'])
    @gefolge_web.util.template('event.overview')
    def event_page(event):
        profile_form = gefolge_web.event.forms.ProfileForm(event, flask.g.user)
        if profile_form.submit_profile_form.data and profile_form.validate():
            if flask.g.user in event.signups:
                flask.flash('Du bist schon angemeldet.')
                return flask.redirect(flask.g.view_node.url)
            if event.anzahlung > gefolge_web.util.Euro():
                if flask.g.user.balance < event.anzahlung:
                    flask.flash('Dein Guthaben reicht nicht aus, um die Anzahlung zu bezahlen.')
                    return flask.redirect(flask.g.view_node.url)
                flask.g.user.add_transaction(gefolge_web.util.Transaction.anzahlung(event))
            event.signup(flask.g.user)
            handle_profile_edit(event, flask.g.user, profile_form)
            return flask.redirect((flask.g.view_node / 'mensch' / flask.g.user).url)
        confirm_signup_form = gefolge_web.event.forms.ConfirmSignupForm(event)
        if confirm_signup_form.submit_confirm_signup_form.data and confirm_signup_form.validate():
            snowflake = int(re.fullmatch('anzahlung {} ([0-9]+)'.format(event.event_id), confirm_signup_form.verwendungszweck.data.lower()).group(1))
            if snowflake < 100:
                guest = gefolge_web.event.model.Guest(event, snowflake)
                event.confirm_guest_signup(guest)
            else:
                mensch = gefolge_web.login.Mensch(snowflake)
                event.signup(mensch)
            return flask.redirect(flask.g.view_node.url)
        programm_add_form = gefolge_web.event.forms.ProgrammAddForm(event)
        if programm_add_form.submit_programm_add_form.data and programm_add_form.validate():
            gefolge_web.util.log('eventProgrammAdd', {
                'event': event.event_id,
                'orga': programm_add_form.orga.data.snowflake,
                'programmpunkt': programm_add_form.name.data,
                'description': programm_add_form.description.data
            })
            if 'programm' not in event.data:
                event.data['programm'] = {}
            event.data['programm'][programm_add_form.name.data] = {
                'description': programm_add_form.description.data,
                'orga': programm_add_form.orga.data.snowflake,
                'signups': []
            }
            #TODO ping Programm orga on Discord
            return flask.redirect((flask.g.view_node / 'programm' / programm_add_form.name.data).url)
        return {
            'event': event,
            'article_source': gefolge_web.wiki.get_article_source('event', event.event_id),
            'confirm_signup_form': confirm_signup_form,
            'profile_form': profile_form,
            'programm_add_form': programm_add_form
        }

    @event_page.catch_init(FileNotFoundError)
    def event_page_catch_init(exc, value):
        #TODO allow users to create new events?
        return flask.render_template('event/404.html', event_id=value), 404

    @app.route('/event/<event_id>/calendar/all.ics') #TODO move to api.gefolge.org
    @gefolge_web.login.member_required
    def event_calendar_all(event_id):
        event = gefolge_web.event.model.Event(event_id)
        cal = icalendar.Calendar()
        cal.add('prodid', '-//Gefolge//gefolge.org//DE')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', str(event))
        for programmpunkt in event.programm:
            if programmpunkt.start is not None and programmpunkt.end is not None:
                cal.add_component(programmpunkt.to_ical())
        return flask.Response(cal.to_ical(), mimetype='text/calendar')

    @event_page.child('guest', 'Gast anmelden', methods=['GET', 'POST'])
    def event_guest_form(event):
        signup_guest_form = gefolge_web.event.forms.SignupGuestForm(event)
        if signup_guest_form.submit_signup_guest_form.data and signup_guest_form.validate():
            guest_name = signup_guest_form.name.data.strip()
            guest = event.signup_guest(flask.g.user, guest_name)
            if event.anzahlung == gefolge_web.util.Euro() or event.orga('Abrechnung') == gefolge_web.login.Mensch.admin():
                if event.anzahlung > gefolge_web.util.Euro():
                    if flask.g.user.balance < event.anzahlung:
                        flask.flash('Dein Guthaben reicht nicht aus, um die Anzahlung zu bezahlen.')
                        return flask.redirect(flask.g.view_node.url)
                    flask.g.user.add_transaction(gefolge_web.util.Transaction.anzahlung(event, guest=guest))
                return flask.redirect((flask.g.view_node.parent / 'mensch' / guest / 'edit').url)
            else:
                return flask.render_template('event/guest-confirm.html', event=event, guest=guest)
        else:
            return flask.render_template('event/guest-form.html', event=event, signup_guest_form=signup_guest_form)

    @event_page.child('mensch', 'Menschen')
    @gefolge_web.util.template('event.menschen')
    def event_menschen(event):
        return {'event': event}

    @event_menschen.children(lambda event, person: event.person(person))
    @gefolge_web.util.template('event.profile')
    def event_profile(event, person):
        return {
            'event': event,
            'person': person
        }

    @event_profile.child('edit', 'bearbeiten', methods=['GET', 'POST'])
    @gefolge_web.util.template('event.profile-edit')
    def event_profile_edit(event, person):
        if not event.can_edit(flask.g.user, person):
            flask.flash('Du bist nicht berechtigt, dieses Profil zu bearbeiten.')
            return flask.redirect(flask.g.view_node.parent.url)
        profile_form = gefolge_web.event.forms.ProfileForm(event, person)
        if profile_form.submit_profile_form.data and profile_form.validate():
            handle_profile_edit(event, person, profile_form)
            return flask.redirect(flask.g.view_node.parent.url)
        else:
            return {
                'event': event,
                'person': person,
                'event_attendee_edit_form': profile_form
            }

    @event_page.redirect('me')
    def event_me(event):
        return event_menschen, flask.g.user

    @event_page.child('programm', 'Programm')
    @gefolge_web.util.template('event.programm')
    def event_programm(event):
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
                return jinja2.Markup('<td rowspan="{}"><a href="{}">{}</a></td>'.format(hours, (flask.g.view_node / programmpunkt).url, programmpunkt))
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

    @event_programm.children(gefolge_web.event.programm.Programmpunkt, methods=['GET', 'POST'])
    @gefolge_web.util.template('event.programmpunkt')
    def event_programmpunkt(event, programmpunkt):
        programmpunkt_form = programmpunkt.form(flask.g.user)
        if hasattr(programmpunkt_form, 'submit_programmpunkt_form') and programmpunkt_form.submit_programmpunkt_form.data and programmpunkt_form.validate():
            programmpunkt.process_form_submission(programmpunkt_form, flask.g.user)
            return flask.redirect(flask.g.view_node.url)
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programmpunkt_form': programmpunkt_form if hasattr(programmpunkt_form, 'submit_programmpunkt_form') else None
            }

    @event_programmpunkt.child('edit', 'bearbeiten', methods=['GET', 'POST'])
    @gefolge_web.util.template('event.programmpunkt-edit')
    def event_programmpunkt_edit(event, programmpunkt):
        if not programmpunkt.can_edit(flask.g.user):
            flask.flash('Du bist nicht berechtigt, diesen Programmpunkt zu bearbeiten.')
            return flask.redirect(flask.g.view_node.parent.url)
        programm_edit_form = gefolge_web.event.forms.ProgrammEditForm(programmpunkt)
        if programm_edit_form.submit_programm_edit_form.data and programm_edit_form.validate():
            gefolge_web.util.log('eventProgrammEdit', {
                'event': event.event_id,
                'programmpunkt': programmpunkt.name,
                'orga': programm_edit_form.orga.data.snowflake,
                'start': (None if programm_edit_form.start.data is None else '{:%Y-%m-%d %H:%M:%S}'.format(programm_edit_form.start.data)),
                'end': (None if programm_edit_form.end.data is None else '{:%Y-%m-%d %H:%M:%S}'.format(programm_edit_form.end.data)),
                'description': programm_edit_form.description.data
            })
            programmpunkt.orga = programm_edit_form.orga.data
            programmpunkt.start = programm_edit_form.start.data
            programmpunkt.end = programm_edit_form.end.data
            programmpunkt.description = programm_edit_form.description.data
            return flask.redirect(flask.g.view_node.parent.url)
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programm_edit_form': programm_edit_form
            }

    @event_programmpunkt.child('delete', 'löschen', methods=['GET', 'POST'])
    @gefolge_web.util.template('event.programmpunkt-delete')
    def event_programmpunkt_delete(event, programmpunkt):
        if g.user != event.orga('Programm'):
            flask.flash('Du bist nicht berechtigt, diesen Programmpunkt zu löschen.')
            return flask.redirect(flask.g.view_node.parent.url)
        programm_delete_form = gefolge_web.event.forms.ProgrammDeleteForm(programmpunkt)
        if programm_delete_form.submit_programm_delete_form.data and programm_delete_form.validate():
            gefolge_web.util.log('eventProgrammDelete', {
                'event': event.event_id,
                'programmpunkt': programmpunkt.name
            })
            del event.data['programm'][programmpunkt.name]
            return flask.redirect(flask.g.view_node.parent.parent.url)
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programm_delete_form': programm_delete_form
            }

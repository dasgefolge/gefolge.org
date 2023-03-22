import datetime
import functools
import itertools
import math
import random
import re
import urllib.parse

import flask # PyPI: Flask
import jinja2 # PyPI: Jinja2
import more_itertools # PyPI: more-itertools
import pytz # PyPI: pytz

import peter # https://github.com/dasgefolge/peter-discord

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
            f'{night:%Y-%m-%d}': getattr(profile_form, f'night{i}').data
            for i, night in enumerate(event.nights)
        },
        'food': {
            'animalProducts': profile_form.animal_products.data,
            'allergies': profile_form.allergies.data,
        },
        'alkohol': profile_form.alkohol.data,
    })
    # Zeitraum
    if 'nights' not in person_data:
        person_data['nights'] = {}
    for i, night in enumerate(event.nights):
        # don't change lastUpdated if the status for this night stays the same
        if f'{night:%Y-%m-%d}' not in person_data.get('nights', {}) or getattr(profile_form, f'night{i}').data != event.night_going(person_data, night):
            person_data['nights'][f'{night:%Y-%m-%d}'] = {
                'going': getattr(profile_form, f'night{i}').data,
                'lastUpdated': f'{gefolge_web.util.now(pytz.utc):%Y-%m-%dT%H:%M:%SZ}',
            }
        if 'log' not in person_data['nights'][f'{night:%Y-%m-%d}']:
            person_data['nights'][f'{night:%Y-%m-%d}']['log'] = []
        person_data['nights'][f'{night:%Y-%m-%d}']['log'] = sorted([*person_data['nights'][f'{night:%Y-%m-%d}']['log'].value(), {
            'time': f'{gefolge_web.util.now(pytz.utc):%Y-%m-%dT%H:%M:%SZ}',
            'going': getattr(profile_form, f'night{i}').data,
        }], key=lambda entry: entry['time'])
    # Zimmer
    if hasattr(profile_form, 'room'):
        if profile_form.room.data:
            person_data['room'] = profile_form.room.data
        elif 'room' in person_data:
            del person_data['room']
    # Essen
    if hasattr(profile_form, 'allergies'):
        if 'food' not in person_data:
            person_data['food'] = {}
        person_data['food']['animalProducts'] = profile_form.animal_products.data
        person_data['food']['allergies'] = profile_form.allergies.data
    if hasattr(profile_form, 'alkohol'):
        person_data['alkohol'] = profile_form.alkohol.data
    # Programm
    # COVID-19
    if hasattr(profile_form, 'covid_immune'):
        person_data['covidStatus'] = 'geimpftGenesen' # checkbox is required
    elif hasattr(profile_form, 'covid_status'):
        person_data['covidStatus'] = profile_form.covid_status.data
    # Anmeldung
    if hasattr(profile_form, 'hausordnung') and profile_form.hausordnung.data:
        person_data['hausordnung'] = True

def handle_programm_edit(programmpunkt, programm_form, is_new):
    gefolge_web.util.log('eventProgrammEdit', {
        'event': programmpunkt.event.event_id,
        'programmpunkt': programmpunkt.url_part,
        'subtitle': programm_form.subtitle.data,
        'orga': programm_form.orga.data.snowflake if hasattr(programm_form, 'orga') and programm_form.orga.data is not None else '(unchanged)',
        'start': (None if programm_form.start.data is None else '{:%Y-%m-%dT%H:%M:%S}'.format(programm_form.start.data)),
        'end': (None if programm_form.end.data is None else '{:%Y-%m-%dT%H:%M:%S}'.format(programm_form.end.data)),
        'description': programm_form.description.data if hasattr(programm_form, 'description') else None
    })
    if programmpunkt.name_editable and hasattr(programm_form, 'display_name'):
        programmpunkt.name = programm_form.display_name.data
    programmpunkt.subtitle = programm_form.subtitle.data
    if hasattr(programm_form, 'orga'):
        old_orga = programmpunkt.orga
        programmpunkt.orga = programm_form.orga.data
        if programmpunkt.orga != old_orga and not is_new:
            if programmpunkt.orga is None:
                peter.channel_msg(programmpunkt.event.channel, f'{programmpunkt} auf {programmpunkt.event} sucht jetzt eine Orga')
            else:
                peter.channel_msg(programmpunkt.event.channel, '{} auf {} wird jetzt von {} organisiert'.format(
                    programmpunkt,
                    programmpunkt.event,
                    programmpunkt.orga if programmpunkt.orga.is_guest else f'<@{programmpunkt.orga.snowflake}>'
                ))
    programmpunkt.start = programm_form.start.data
    programmpunkt.end = programm_form.end.data
    if programmpunkt.description_editable and hasattr(programm_form, 'description'):
        programmpunkt.description = programm_form.description.data
    if hasattr(programm_form, 'css_class'):
        programmpunkt.css_class = programm_form.css_class.data

def mensch_or_signup_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not flask.g.user.is_authenticated:
            return flask.redirect('/login/discord') #TODO redirect_to parameter
        if not flask.g.user.is_mensch and flask.g.user not in gefolge_web.event.model.Event(kwargs['event']).signups:
            return flask.make_response(('Sie haben keinen Zugriff auf diesen Inhalt, weil Sie nicht für dieses event angemeldet sind und nicht im Gefolge Discord server sind oder nicht als Gefolgemensch verifiziert sind.', 403, [])) #TODO template
        return f(*args, **kwargs)

    return wrapper

def setup(index, app):
    @index.child('event', 'events')
    @gefolge_web.login.mensch_required # children use mensch_or_signup_required
    @gefolge_web.util.template('event.index')
    def events_index():
        now = gefolge_web.util.now()
        future_events, past_events = more_itertools.partition(lambda event: event.end is not None and event.end < now, gefolge_web.event.model.Event)
        future_events, current_events = more_itertools.partition(lambda event: event.start is not None and event.start < now, future_events)
        return {
            'current_events': sorted(current_events),
            'future_events': sorted(future_events),
            'past_events': sorted(past_events, reverse=True)
        }

    @events_index.children(gefolge_web.event.model.Event, methods=['GET', 'POST'], decorators=[mensch_or_signup_required])
    @gefolge_web.util.template('event.overview')
    def event_page(event):
        profile_form = gefolge_web.event.forms.ProfileForm(event, flask.g.user)
        if profile_form.submit_profile_form.data and profile_form.validate():
            if event.location is not None and event.location.is_online:
                flask.flash('Für online events gibt es keine Anmeldung.', 'error')
                return flask.redirect(flask.g.view_node.url)
            if flask.g.user in event.signups:
                flask.flash('Du bist schon angemeldet.', 'error')
                return flask.redirect(flask.g.view_node.url)
            if event.signup_block_reason is not None:
                flask.flash(event.signup_block_reason, 'error')
                return flask.redirect(flask.g.view_node.url)
            if event.anzahlung is not None and event.anzahlung > gefolge_web.util.Euro():
                if hasattr(profile_form, 'anzahlung'):
                    anzahlung = profile_form.anzahlung.data
                else:
                    anzahlung = event.anzahlung
                if flask.g.user.balance < anzahlung and not (flask.g.user.is_admin or flask.g.user.is_treasurer):
                    flask.flash('Dein Guthaben reicht nicht aus, um die Anzahlung zu bezahlen.', 'error')
                    return flask.redirect(flask.g.view_node.url)
                flask.g.user.add_transaction(gefolge_web.util.Transaction.anzahlung(event, -anzahlung))
                while True:
                    anzahlung_extra = event.anzahlung_total - event.ausfall
                    if anzahlung_extra <= gefolge_web.util.Euro():
                        break
                    extra_anzahlungen = sorted(filter(lambda kv: kv[1] > event.anzahlung, (
                        (mensch, gefolge_web.util.Euro(event.attendee_data(mensch).get('anzahlung', event.anzahlung.value)))
                        for mensch in event.menschen
                    )), key=lambda kv: (kv[1] % event.anzahlung == gefolge_web.util.Euro(), (kv[1] - anzahlung_extra) % event.anzahlung != gefolge_web.util.Euro(), -kv[1]))
                    if len(extra_anzahlungen) == 0:
                        break
                    iter_mensch, iter_anzahlung = extra_anzahlungen[0]
                    if iter_anzahlung % event.anzahlung == gefolge_web.util.Euro() or (iter_anzahlung - anzahlung_extra) % event.anzahlung == gefolge_web.util.Euro():
                        amount = min(anzahlung_extra, iter_anzahlung - event.anzahlung)
                    else:
                        amount = min(anzahlung_extra, iter_anzahlung % event.anzahlung)
                    event.attendee_data(iter_mensch)['anzahlung'] = event.attendee_data(iter_mensch)['anzahlung'].value() - amount.value
                    iter_mensch.add_transaction(gefolge_web.util.Transaction.anzahlung_return(event, iter_anzahlung - amount - event.anzahlung, amount))
            event.signup(flask.g.user, anzahlung)
            handle_profile_edit(event, flask.g.user, profile_form)
            return flask.redirect((flask.g.view_node / 'mensch' / flask.g.user).url)
        confirm_signup_form = gefolge_web.event.forms.ConfirmSignupForm(event)
        if confirm_signup_form.submit_confirm_signup_form.data and confirm_signup_form.validate():
            snowflake = int(re.fullmatch('anzahlung {} ([0-9]+)'.format(event.event_id), confirm_signup_form.verwendungszweck.data.lower()).group(1))
            if snowflake < 100:
                person = gefolge_web.event.model.EventGuest(event, snowflake)
            else:
                person = gefolge_web.login.DiscordPerson(snowflake)
            if person.is_guest:
                event.confirm_guest_signup(person, message=True)
            else:
                event.signup(person)
            return flask.redirect(flask.g.view_node.url)
        programm_form = gefolge_web.event.forms.ProgrammForm(event, None)
        if programm_form.submit_programm_form.data and programm_form.validate():
            gefolge_web.util.log('eventProgrammAdd', {
                'event': event.event_id,
                'programmpunkt': programm_form.url_part.data
            })
            if 'programm' not in event.data:
                event.data['programm'] = {}
            event.data['programm'][programm_form.url_part.data] = {}
            programmpunkt = gefolge_web.event.programm.Programmpunkt(event, programm_form.url_part.data)
            handle_programm_edit(programmpunkt, programm_form, True)
            peter.channel_msg(event.channel, 'Neuer Programmpunkt auf {}: {} ({}, <https://gefolge.org/event/{}/programm/{}>)'.format(
                '<@&{}>'.format(event.data['role']) if 'role' in event.data else event,
                programmpunkt,
                'Orga gesucht' if programmpunkt.orga is None else f'Orga: <@{programmpunkt.orga.snowflake}>',
                event.event_id,
                urllib.parse.quote(programmpunkt.url_part)
            ))
            return flask.redirect((flask.g.view_node / 'programm' / programmpunkt.url_part).url)
        return {
            'event': event,
            'confirm_signup_form': confirm_signup_form,
            'profile_form': profile_form,
            'programm_form': programm_form
        }

    @event_page.catch_init(FileNotFoundError)
    def event_page_catch_init(exc, value):
        #TODO allow users to create new events?
        return gefolge_web.util.render_template('event.404', event_id=value), 404

    @event_page.child('guest', 'Gast anmelden', methods=['GET', 'POST'])
    def event_guest_form(event):
        signup_guest_form = gefolge_web.event.forms.SignupGuestForm(event)
        if signup_guest_form.submit_signup_guest_form.data and signup_guest_form.validate():
            if event.guest_signup_block_reason is not None:
                flask.flash(event.guest_signup_block_reason, 'error')
                return flask.redirect(flask.g.view_node.url)
            guest_name = signup_guest_form.name.data.strip()
            if len(guest_name) > 0:
                # EventGuest
                if any(str(guest) == guest_name for guest in event.guests):
                    raise ValueError('Duplicate guest name: {!r}'.format(guest_name))
                available_ids = [i for i in range(1, 100) if not any(guest.snowflake == i for guest in event.guests)]
                guest_id = random.choice(available_ids)
            else:
                # DiscordGuest
                guest = signup_guest_form.person.data
                guest_id = guest.snowflake
            signup_data = {
                'id': guest_id,
                'via': flask.g.user.snowflake
            }
            if len(guest_name) > 0:
                signup_data['name'] = guest_name
            gefolge_web.util.log('eventSignupGuest', {'event': event.event_id, **signup_data})
            event.data['menschen'].append(signup_data)
            if event.anzahlung == gefolge_web.util.Euro() or event.orga('Abrechnung').is_treasurer:
                peter.channel_msg(event.channel, f'<@{flask.g.user.snowflake}> hat {guest_name or f"<@{guest.snowflake}>"} für {event} angemeldet')
            if len(guest_name) > 0:
                guest = gefolge_web.event.model.EventGuest(event, guest_id)
            if event.anzahlung == gefolge_web.util.Euro() or event.orga('Abrechnung').is_treasurer:
                if event.anzahlung > gefolge_web.util.Euro():
                    if flask.g.user.balance < event.anzahlung and not (flask.g.user.is_admin or flask.g.user.is_treasurer):
                        flask.flash('Dein Guthaben reicht nicht aus, um die Anzahlung zu bezahlen.', 'error')
                        return flask.redirect(flask.g.view_node.url)
                    flask.g.user.add_transaction(gefolge_web.util.Transaction.anzahlung(event, guest=guest))
                event.confirm_guest_signup(guest, message=False)
                return flask.redirect((flask.g.view_node.parent / 'mensch' / guest / 'edit').url)
            else:
                return gefolge_web.util.render_template('event.guest-confirm', event=event, guest=guest)
        else:
            return gefolge_web.util.render_template('event.guest-form', event=event, signup_guest_form=signup_guest_form)

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

    @event_profile.catch_init(ValueError)
    def event_profile_catch_init(exc, value):
        return gefolge_web.util.render_template('event.profile-404', exc=exc), 404

    @event_profile.child('edit', 'bearbeiten', methods=['GET', 'POST'])
    @gefolge_web.util.template('event.profile-edit')
    def event_profile_edit(event, person):
        if not event.can_edit(flask.g.user, person):
            flask.flash('Du bist nicht berechtigt, dieses Profil zu bearbeiten.', 'error')
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
        calendar = event.calendar
        filled_until = None
        # rows from hour snip_start to hour snip_end are omitted
        snip_start = 0
        snip_end = 24

        def calendar_cell(date, hour):
            nonlocal filled_until
            nonlocal snip_start
            nonlocal snip_end

            timestamp = event.timezone.localize(datetime.datetime.combine(date, datetime.time(hour)), is_dst=None)
            if filled_until is not None and filled_until > timestamp:
                return '' # this cell is already filled
            if timestamp < event.start or timestamp >= event.end:
                return jinja2.Markup('<td style="background-color: #666666;"></td>')
            events_starting_now = [
                calendar_event
                for calendar_event in calendar
                if calendar_event.start >= timestamp
                and calendar_event.start < timestamp + datetime.timedelta(hours=1)
                and calendar_event.end < calendar_event.start + datetime.timedelta(hours=24)
            ]
            if len(events_starting_now) == 0:
                return jinja2.Markup('<td></td>') # nothing planned yet
            elif len(events_starting_now) == 1:
                calendar_event = more_itertools.one(events_starting_now)
                hours = math.ceil((min(calendar_event.end, event.timezone.localize(datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time()), is_dst=None)) - timestamp) / datetime.timedelta(hours=1))
                filled_until = timestamp + datetime.timedelta(hours=hours) #TODO support for events that go past midnight
                if hour < 6 and hour + hours >= 6:
                    # goes over 06:00, remove snip entirely
                    snip_start = 6
                    snip_end = 6
                if snip_start < hour + hours < 6:
                    # before 06:00, can only start snip at end hour
                    snip_start = hour + hours
                if snip_end > hour >= 6:
                    # at or after 06:00, must stop snip at start hour
                    snip_end = hour
                return jinja2.Markup('<td rowspan="{}" class="{}">{}{}</td>'.format(hours, calendar_event.css_class, calendar_event.__html__(), '<br />{}'.format(jinja2.escape(calendar_event.subtitle)) if calendar_event.subtitle else ''))
            else:
                #TODO support for events that go past midnight
                return jinja2.Markup('<td class="danger">{} Programmpunkte</td>'.format(len(events_starting_now)))

        table = {
            date: {
                hour: calendar_cell(date, hour)
                for hour in range(24)
            }
            for date in itertools.chain(event.nights, [event.end.date()])
        }
        return {
            'event': event,
            'snip_start': snip_start,
            'snip_end': snip_end,
            'table': table
        }

    @event_programm.children(gefolge_web.event.programm.Programmpunkt.from_url_part_or_name, methods=['GET', 'POST'])
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

    @event_programmpunkt.catch_init(ValueError)
    def event_programmpunkt_catch_init(exc, value):
        return gefolge_web.util.render_template('event.programmpunkt-404', exc=exc), 404

    @event_programmpunkt.child('edit', 'bearbeiten', methods=['GET', 'POST'])
    @gefolge_web.util.template('event.programmpunkt-edit')
    def event_programmpunkt_edit(event, programmpunkt):
        if not programmpunkt.can_edit(flask.g.user):
            flask.flash('Du bist nicht berechtigt, diesen Programmpunkt zu bearbeiten.', 'error')
            return flask.redirect(flask.g.view_node.parent.url)
        programm_form = gefolge_web.event.forms.ProgrammForm(event, programmpunkt)
        if programm_form.submit_programm_form.data and programm_form.validate():
            handle_programm_edit(programmpunkt, programm_form, False)
            return flask.redirect(flask.g.view_node.parent.url)
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programm_form': programm_form
            }

    @event_programmpunkt.child('delete', 'löschen', methods=['GET', 'POST'])
    @gefolge_web.util.template('event.programmpunkt-delete')
    def event_programmpunkt_delete(event, programmpunkt):
        if flask.g.user != event.orga('Programm') and not flask.g.user.is_admin:
            flask.flash('Du bist nicht berechtigt, diesen Programmpunkt zu löschen.', 'error')
            return flask.redirect(flask.g.view_node.parent.url)
        programm_delete_form = gefolge_web.event.forms.ProgrammDeleteForm()
        if programm_delete_form.submit_programm_delete_form.data and programm_delete_form.validate():
            gefolge_web.util.log('eventProgrammDelete', {
                'event': event.event_id,
                'programmpunkt': programmpunkt.url_part
            })
            del event.data['programm'][programmpunkt.url_part]
            return flask.redirect(flask.g.view_node.parent.parent.url)
        else:
            return {
                'event': event,
                'programmpunkt': programmpunkt,
                'programm_delete_form': programm_delete_form
            }

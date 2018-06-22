import datetime
import decimal
import flask
import flask_wtf
import functools
import jinja2
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
LOCATIONS_ROOT = pathlib.Path('/usr/local/share/fidera/loc')

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
        if not any('via' in person and person['id'].value() == self.snowflake for person in event.data['menschen']):
            raise ValueError('Es gibt keinen Gast mit dieser ID.')

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

class Location:
    def __init__(self, loc_id):
        self.loc_id = loc_id

    def __html__(self):
        website = self.data.get('website')
        if website is None:
            return jinja2.escape(str(self))
        else:
            return jinja2.Markup('<a href="{}">{}</a>'.format(jinja2.escape(website), self))

    def __repr__(self):
        return 'gefolge_web.event.Location({!r})'.format(self.loc_id)

    def __str__(self):
        return self.data.get('name', self.loc_id)

    @property
    def data(self):
        return lazyjson.File(LOCATIONS_ROOT / '{}.json'.format(self.loc_id))

    @property
    def prefix(self):
        return self.data.get('prefix', 'in')

@functools.total_ordering
class Programmpunkt:
    def __init__(self, event=None, name=None, *, event_id=None):
        # event can be specified by event or event_id argument
        if name is None:
            raise TypeError('Missing name argument for Programmpunkt constructor')
        else:
            self.name = name
        if event is not None:
            self.event = event
        elif event_id is not None:
            self.event = Event(event_id)

    def __eq__(self, other):
        return isinstance(other, Programmpunkt) and self.event == other.event and self.name == other.name

    def __lt__(self, other):
        if not isinstance(other, Programmpunkt):
            return NotImplemented
        return (self.event, self.name) < (other.event, other.name) #TODO sort by time

    def __repr__(self):
        return 'gefolge_web.event.Programmpunkt({!r}, {!r})'.format(self.event, self.name)

    def __str__(self):
        return self.name

    def can_edit(self, editor):
        return self.orga == editor or self.event.orga('Programm') == editor

    @property
    def data(self):
        return self.event.data['programm'][self.name]

    @property
    def orga(self):
        orga_id = self.data['orga'].value()
        if orga_id is not None:
            return gefolge_web.login.Mensch(orga_id)

@functools.total_ordering
class Event:
    def __init__(self, event_id):
        self.event_id = event_id

    def __eq__(self, other):
        return isinstance(other, Event) and self.event_id == other.event_id

    def __lt__(self, other):
        if not isinstance(other, Event):
            return NotImplemented
        return (self.start, self.end, self.event_id) < (other.start, other.end, other.event_id)

    def __repr__(self):
        return 'gefolge_web.event.Event({!r})'.format(self.event_id)

    def __str__(self):
        return self.data.get('name', self.event_id)

    @property
    def anzahlung(self):
        if 'anzahlung' in self.data:
            if self.data['anzahlung'].value() is None:
                return None
            return Euro(self.data['anzahlung'].value())
        else:
            return None

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

    def can_edit(self, editor, profile):
        editor_data = self.attendee_data(editor)
        if editor_data is None:
            # wer nicht angemeldet ist, darf nichts bearbeiten
            return False
        if len(editor_data.get('orga', [])) > 0:
            # Orga darf alle bearbeiten
            return True
        if gefolge_web.util.now() > self.end:
            # nach Ende des event darf nur noch die Orga bearbeiten
            return False
        if editor == profile:
            # Menschen dürfen ihr eigenes Profil bearbeiten
            return True
        if profile.snowflake < 100 and profile.via == editor:
            # Gastprofile dürfen von ihren proxies bearbeitet werden
            return True
        return False

    @property
    def data(self):
        return lazyjson.File(EVENTS_ROOT / '{}.json'.format(self.event_id))

    @property
    def end(self):
        return gefolge_web.util.parse_iso_datetime(self.data['end'].value())

    @property
    def guests(self):
        return [
            Guest(self, person['id'].value())
            for person in self.data['menschen']
            if 'via' in person
        ]

    @property
    def location(self):
        loc_id = self.data.get('location')
        if loc_id is not None:
            return Location(loc_id)

    @property
    def menschen(self):
        return [
            gefolge_web.login.Mensch(person['id'].value())
            for person in self.data['menschen']
            if 'via' not in person
        ]

    def night_maybes(self, night):
        return [
            person
            for person in self.signups
            if self.attendee_data(person).get('nights', {}).get('{:%Y-%m-%d}'.format(night), 'maybe') == 'maybe'
        ]

    def night_signups(self, night):
        return [
            person
            for person in self.signups
            if self.attendee_data(person).get('nights', {}).get('{:%Y-%m-%d}'.format(night), 'maybe') == 'yes'
        ]

    @property
    def nights(self):
        return gefolge_web.util.date_range(self.start.date(), self.end.date())

    def orga(self, aufgabe):
        for mensch in self.data['menschen']:
            if aufgabe in mensch.get('orga', []):
                return gefolge_web.login.Mensch(mensch['id'].value())

    def person(self, snowflake):
        if int(snowflake) < 100:
            result = Guest(self, snowflake)
        else:
            result = gefolge_web.login.Mensch(snowflake)
            if not result.is_active:
                raise ValueError('Dieser Discord account existiert nicht oder ist nicht im Gefolge.')
        return result

    @property
    def programm(self):
        return sorted(
            Programmpunkt(self, name)
            for name in self.data['programm'].value()
        )

    def signup(self, mensch):
        gefolge_web.util.log('eventConfirmSignup', {
            'id': mensch.snowflake
        })
        self.data['menschen'].append({
            'id': mensch.snowflake,
            'signup': '{:%Y-%m-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
        })

    def signup_guest(self, mensch, guest_name):
        if any(str(guest) == guest_name for guest in self.guests):
            raise ValueError('Duplicate guest name: {!r}'.format(guest_name))
        available_ids = [i for i in range(100) if not any(guest.snowflake == i for guest in self.guests)]
        guest_id = random.choice(available_ids)
        gefolge_web.util.log('eventSignupGuest', {
            'id': guest_id,
            'name': guest_name,
            'via': mensch.snowflake
        })
        self.data['menschen'].append({
            'id': guest_id,
            'name': guest_name
        })
        return Guest(self, guest_id)

    @property
    def signups(self):
        """Returns everyone who has completed signup, including guests, in order of signup."""
        result = {
            guest: self.attendee_data(guest)['signup'].value()
            for guest in self.guests
            if 'signup' in self.attendee_data(guest)
        }
        result.update({
            mensch: self.attendee_data(mensch)['signup'].value()
            for mensch in self.menschen
        })
        return [person for person, signup in sorted(result.items(), key=lambda kv: kv[1])]

    @property
    def start(self):
        return gefolge_web.util.parse_iso_datetime(self.data['start'].value())

    @property
    def url_part(self):
        return self.event_id

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

class PersonField(wtforms.SelectField):
    """A form field that validates to a Mensch or Guest. Displayed as a combobox."""

    #TODO actually display as a combobox (text field with dropdown menu)

    def __init__(self, event, label, allow_guests=True, **kwargs):
        self.event = event
        self.allow_guests = allow_guests
        super().__init__(label, choices=[(person.snowflake, str(person)) for person in self.people], **kwargs)

    @property
    def people(self):
        if self.allow_guests:
            return self.event.signups
        else:
            return self.event.menschen

    def iter_choices(self):
        for person in self.people:
            yield person.snowflake, str(person), person == self.data

    def process_data(self, value):
        try:
            self.data = None if value is None else self.event.person(value)
        except (TypeErro, ValueError):
            self.data = None

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = self.event.person(valuelist[0])
            except (ValueError, TypeError):
                raise ValueError('Invalid choice: could not coerce')

    def pre_validate(self, form):
        for person in self.people:
            if self.data == person:
                break
        else:
            raise ValueError('Not a valid choice')

class YesMaybeNoField(wtforms.RadioField):
    """A form field that validates to yes, maybe, or no. Displayed as a horizontal button group."""

    def __init__(self, label, default='maybe', **kwargs):
        super().__init__(label, choices=[('yes', 'Ja'), ('maybe', 'Vielleicht'), ('no', 'Nein')], default=default, **kwargs)

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

def ProfileForm(event, person):
    class Form(flask_wtf.FlaskForm):
        pass

    person_data = event.attendee_data(person).value()
    for i, night in enumerate(event.nights):
        setattr(Form, 'night{}'.format(i), YesMaybeNoField(
            '{:%d.%m.}–{:%d.%m.}'.format(night, night + datetime.timedelta(days=1)),
            default=person_data.get('nights', {}).get('{:%Y-%m-%d}'.format(night), 'maybe'),
            validators=[wtforms.validators.InputRequired()]
        ))
    return Form()

def ProgrammAddForm(event):
    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Titel', [wtforms.validators.InputRequired(), wtforms.validators.NoneOf([programmpunkt.name for programmpunkt in event.programm], message='Es gibt bereits einen Programmpunkt mit diesem Titel.')])
        orga = PersonField(event, 'Orga', allow_guests=False)
        description = wtforms.StringField('Beschreibung')

    return Form()

def SignupGuestForm(event):
    def validate_guest_name(form, field):
        name = field.data.strip()
        if any(str(guest) == name for guest in event.guests):
            raise wtforms.validators.ValidationError('Ein Gast mit diesem Namen ist bereits angemeldet.')

    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Name', [wtforms.validators.DataRequired(), validate_guest_name])

    return Form()

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
                Event(event_path.stem)
                for event_path in EVENTS_ROOT.iterdir()
            )
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
                gefolge_web.util.log('eventConfirmSignup', {
                    'id': snowflake
                })
                event.attendee_data(guest)['signup'] = '{:%Y-%m-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
            else:
                mensch = gefolge_web.login.Mensch(snowflake)
                event.signup(mensch)
            return flask.redirect(flask.url_for('event_page', event_id=event_id))
        programm_add_form = ProgrammAddForm(event)
        if programm_add_form.validate_on_submit():
            gefolge_web.util.log('eventProgrammAdd', {
                'orga': programm_add_form.orga.data.snowflake,
                'title': programm_add_form.name.data,
                'description': programm_add_form.description.data
            })
            event.data['programm'][programm_add_form.name.data] = {
                'description': programm_add_form.description.data,
                'interesse': [],
                'orga': programm_add_form.orga.data.snowflake
            }
            #TODO ping Programm orga on Discord
            #TODO redirect to Programm view/edit page
        return {
            'event': event,
            'article_source': gefolge_web.wiki.get_article_source('event', event_id),
            'confirm_signup_form': confirm_signup_form,
            'programm_add_form': programm_add_form
        }

    @app.route('/event/<event_id>/guest', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('guest', 'Gast anmelden'), event_page)
    def event_guest_form(event_id):
        event = Event(event_id)
        signup_guest_form = SignupGuestForm(event)
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
        return {'event': Event(event_id)}

    @app.route('/event/<event_id>/mensch/<snowflake>')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(lambda event_id, name: Event(event_id).person(snowflake), event_menschen)
    @gefolge_web.util.template('event-profile')
    def event_profile(event_id, snowflake):
        event = Event(event_id)
        return {
            'event': event,
            'person': event.person(snowflake)
        }

    @app.route('/event/<event_id>/mensch/<snowflake>/edit', methods=['GET', 'POST'])
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('edit', 'bearbeiten'), event_profile)
    @gefolge_web.util.template('event-profile-edit')
    def event_profile_edit(event_id, snowflake):
        event = Event(event_id)
        person = event.person(snowflake)
        if not event.can_edit(flask.g.user, person):
            flask.flash('Du bist nicht berechtigt, dieses Profil zu bearbeiten.')
            return flask.redirect(flask.url_for('event_profile', event_id=event_id, snowflake=snowflake))
        profile_form = ProfileForm(event, person)
        if profile_form.validate_on_submit():
            person_data = event.attendee_data(person)
            gefolge_web.util.log('eventProfileEdit', {
                'id': person.snowflake,
                'nights': {
                    '{:%Y-%m-%d}'.format(night): getattr(profile_form, 'night{}'.format(i)).data
                    for i, night in enumerate(event.nights)
                }
            })
            if 'nights' not in person_data:
                person_data['nights'] = {}
            for i, night in enumerate(event.nights):
                person_data['nights']['{:%Y-%m-%d}'.format(night)] = getattr(profile_form, 'night{}'.format(i)).data
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
        return {'event': Event(event_id)}

    @app.route('/event/<event_id>/programm/<name>')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(Programmpunkt, event_programm)
    @gefolge_web.util.template('event-programmpunkt')
    def event_programmpunkt(event_id, name):
        event = Event(event_id)
        return {
            'event': event,
            'programmpunkt': Programmpunkt(event, name)
        }

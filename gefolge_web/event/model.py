import datetime
import itertools
import pathlib
import random

import flask # PyPI: Flask
import icalendar # PyPI: icalendar
import jinja2 # PyPI: Jinja2
import pytz # PyPI: pytz

import class_key # https://github.com/fenhl/python-class-key
import lazyjson # https://github.com/fenhl/lazyjson

import gefolge_web.login
import gefolge_web.peter
import gefolge_web.util

EVENTS_ROOT = gefolge_web.util.BASE_PATH / 'event'
LOCATIONS_ROOT = gefolge_web.util.BASE_PATH / 'loc'
ORGA_ROLES = ['Abrechnung', 'Buchung', 'Essen', 'Programm', 'Schlüssel']
SILVESTER_CHANNEL = 387264349678338049

class Guest:
    def __init__(self, event, guest_id):
        self.event = event
        self.snowflake = int(guest_id) # not actually a snowflake but uses this variable name for compatibility with the Mensch class
        if not any('via' in person and person['id'] == self.snowflake for person in event.data.get('menschen', [])):
            raise ValueError('Es gibt keinen Gast mit dieser ID.')

    def __eq__(self, other):
        return hasattr(other, 'snowflake') and self.snowflake == other.snowflake

    def __hash__(self):
        return hash(self.snowflake)

    def __html__(self):
        return jinja2.escape(str(self))

    def __repr__(self):
        return 'gefolge_web.event.model.Guest({!r}, {!r})'.format(self.event, self.snowflake)

    def __str__(self):
        return self.event.attendee_data(self)['name'].value()

    @property
    def is_guest(self):
        return True

    @property
    def long_name(self):
        return str(self)

    @property
    def url_part(self):
        return str(self.snowflake)

    @property
    def via(self):
        return gefolge_web.login.Mensch(self.event.attendee_data(self)['via'].value())

class Location:
    def __init__(self, loc_id):
        self.loc_id = loc_id

    def __html__(self):
        result = jinja2.Markup()
        if 'host' in self.data:
            result += jinja2.Markup('bei ')
            result += gefolge_web.login.Mensch(self.data['host'].value()).__html__()
            result += jinja2.Markup(' ')
        result += jinja2.escape(self.prefix)
        website = self.data.get('website')
        if website is None:
            result += jinja2.escape(str(self))
        else:
            result += jinja2.Markup('<a href="{}">{}</a>'.format(jinja2.escape(website), jinja2.escape(str(self))))
        return result

    def __repr__(self):
        return 'gefolge_web.event.model.Location({!r})'.format(self.loc_id)

    def __str__(self):
        return self.data.get('name', self.loc_id)

    @property
    def address(self):
        return self.data['address'].value()

    @property
    def data(self):
        return gefolge_web.util.cached_json(lazyjson.File(LOCATIONS_ROOT / '{}.json'.format(self.loc_id)))

    @property
    def hausordnung(self):
        return self.data.get('hausordnung')

    @property
    def prefix(self):
        return self.data.get('prefix', 'in ')

    @property
    def timezone(self):
        return pytz.timezone(self.data['timezone'].value())

class EventMeta(type):
    def __iter__(self):
        # iterating over the Event class yields all events
        return iter(sorted(
            Event(event_path.stem)
            for event_path in EVENTS_ROOT.iterdir()
        ))

@class_key.class_key()
class Event(metaclass=EventMeta):
    def __init__(self, event_id):
        self.event_id = event_id
        self.data.value() # make sure event exists

    def __html__(self):
        return jinja2.Markup('<a href="{}">{}</a>'.format(flask.url_for('event_page', event=self.event_id), self))

    @property
    def __key__(self):
        return self.start is None, self.start, self.end is None, self.end, self.event_id

    def __repr__(self):
        return 'gefolge_web.event.model.Event({!r})'.format(self.event_id)

    def __str__(self):
        return self.data.get('name', self.event_id)

    @property
    def anzahlung(self):
        if 'anzahlung' in self.data:
            if self.data['anzahlung'].value() is None:
                return None
            return gefolge_web.util.Euro(self.data['anzahlung'].value())
        else:
            return None

    @property
    def anzahlung_total(self):
        """Die Summe der bisher gezahlten Anzahlungen."""
        if self.anzahlung is None:
            return None
        return sum((
            gefolge_web.util.Euro(self.attendee_data(person).get('anzahlung', self.anzahlung.value))
            for person in self.signups
        ), gefolge_web.util.Euro())

    def attendee_data(self, person):
        if 'menschen' in self.data:
            for iter_data in self.data['menschen']:
                if iter_data['id'].value() == person.snowflake:
                    return iter_data

    @property
    def ausfall(self):
        if 'ausfall' in self.data:
            return gefolge_web.util.Euro(self.data['ausfall'].value())
        else:
            return gefolge_web.util.Euro()

    @property
    def ausfall_date(self):
        if 'ausfallDate' in self.data:
            return gefolge_web.util.parse_iso_date(self.data['ausfallDate'].value())

    @property
    def calendar(self):
        import gefolge_web.event.programm

        return sorted(itertools.chain((
            [gefolge_web.event.programm.CalendarEvent(
                self, 'neujahr',
                text='Neujahr',
                html='Neujahr',
                start=self.timezone.localize(datetime.datetime(self.end.year, 1, 1), is_dst=None),
                end=self.timezone.localize(datetime.datetime(self.end.year, 1, 1, 1), is_dst=None)
            )] if self.end.year > self.start.year else []
        ), (
            [gefolge_web.event.programm.CalendarEvent(
                self, 'endreinigung',
                text='Endreinigung',
                html='Endreinigung',
                start=self.end - datetime.timedelta(hours=2),
                end=self.end
            )] if self.location is not None and 'host' not in self.location.data else []
        ), itertools.chain.from_iterable(
            programmpunkt.calendar_events
            for programmpunkt in self.programm
        )))

    def can_edit(self, editor, profile):
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
        editor_data = self.attendee_data(editor)
        if editor_data is None:
            # wer nicht angemeldet ist, darf nichts bearbeiten
            return False
        if len(editor_data.get('orga', [])) > 0:
            # Orga darf alle bearbeiten
            return True
        if gefolge_web.util.now(self.timezone) > self.end:
            # nach Ende des event darf nur noch die Orga bearbeiten
            return False
        if editor == profile:
            # Menschen dürfen ihr eigenes Profil bearbeiten
            return True
        if profile.is_guest and profile.via == editor:
            # Gastprofile dürfen von ihren proxies bearbeitet werden
            return True
        return False

    def capacity(self, night):
        if 'capacity' in self.data:
            return self.data['capacity']['{:%Y-%m-%d}'.format(night)].value()
        else:
            return self.location.data['capacity'].value()

    @property
    def channel(self):
        return self.data.get('channel', SILVESTER_CHANNEL)

    def confirm_guest_signup(self, guest, *, message=None):
        if message is None:
            message = not self.orga('Abrechnung').is_admin
        gefolge_web.util.log('eventConfirmSignup', {
            'event': self.event_id,
            'person': guest.snowflake
        })
        self.attendee_data(guest)['signup'] = '{:%Y-%m-%dT%H:%M:%S}'.format(gefolge_web.util.now(self.timezone)) #TODO Datum der Überweisung verwenden
        if message:
            gefolge_web.peter.channel_msg(self.channel, '<@{}>: {} ist jetzt für {} angemeldet. Fülle bitte bei Gelegenheit noch das Profil auf <https://gefolge.org/event/{}/mensch/{}/edit> aus. Außerdem kannst du {} auf <https://gefolge.org/event/{}/programm> für Programmpunkte als interessiert eintragen'.format(guest.via.snowflake, guest, self, self.event_id, guest.snowflake, guest, self.event_id))

    @property
    def data(self):
        return gefolge_web.util.cached_json(lazyjson.File(EVENTS_ROOT / '{}.json'.format(self.event_id)))

    @property
    def end(self):
        if 'end' in self.data:
            return gefolge_web.util.parse_iso_datetime(self.data['end'].value(), tz=self.timezone)

    def essen(self, date):
        import gefolge_web.event.programm.essen

        if date in self.nights:
            return gefolge_web.event.programm.essen.Abendessen(self, date)
        else:
            raise ValueError('Datum liegt außerhalb des event')

    def free(self, start=None, end=None):
        if end is None:
            if start is None:
                end = self.end.date()
            else:
                end = start + datetime.timedelta(days=1)
        if start is None:
            start = self.start.date()
        return min(
            self.capacity(night) - len(self.night_signups(night))
            for night in gefolge_web.util.date_range(start, end)
        )

    @property
    def guests(self):
        return [
            Guest(self, person['id'])
            for person in self.data.get('menschen', [])
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
            gefolge_web.login.Mensch(person['id'])
            for person in self.data.get('menschen', [])
            if 'via' not in person
        ]

    def night_going(self, attendee_data, night):
        if hasattr(attendee_data, 'snowflake'):
            attendee_data = self.attendee_data(attendee_data)
        result = attendee_data.get('nights', {}).get('{:%Y-%m-%d}'.format(night), {'going': 'maybe', 'lastUpdated': None})
        if isinstance(result, dict):
            result = result['going']
        return result

    def night_maybes(self, night):
        return [
            person
            for person in self.signups
            if self.night_going(person, night) == 'maybe'
        ]

    def night_signups(self, night):
        return [
            person
            for person in self.signups
            if self.night_going(person, night) == 'yes'
        ]

    @property
    def nights(self):
        return gefolge_web.util.date_range(self.start.date(), self.end.date())

    def orga(self, aufgabe):
        for mensch in self.data.get('menschen', []):
            if aufgabe in mensch.get('orga', []):
                return gefolge_web.login.Mensch(mensch['id'])

    @property
    def orga_unassigned(self):
        return [role for role in ORGA_ROLES if self.orga(role) is None]

    def person(self, snowflake):
        if hasattr(snowflake, 'snowflake'):
            snowflake = snowflake.snowflake
        if snowflake is None:
            return None
        if int(snowflake) < 100:
            result = Guest(self, snowflake)
        else:
            result = gefolge_web.login.Mensch(snowflake)
            if not result.is_active:
                raise ValueError('Dieser Discord account existiert nicht oder ist nicht im Gefolge.')
        return result

    @property
    def programm(self):
        import gefolge_web.event.programm
        import gefolge_web.event.programm.essen
        import gefolge_web.event.programm.magic
        try:
            import werewolf_web # extension for Werewolf games, closed-source to allow the admin to make relevant changes before a game without giving away information to players
        except ImportError:
            werewolf_web = None

        return sorted(itertools.chain((
            gefolge_web.event.programm.Programmpunkt(self, name)
            for name in self.data.get('programm', {})
            if name not in {'custom-magic-draft', 'rtww'} # special, already listed below
        ), ([] if self.start is None else (
            gefolge_web.event.programm.essen.Abendessen(self, date)
            for date in self.nights
        )), (
            [] if self.event_id in gefolge_web.event.programm.magic.config().get('skippedEvents', []) else [gefolge_web.event.programm.magic.CustomMagicDraft(self)]
        ), (
            [] if werewolf_web is None or not werewolf_web.Setup(self).data_path.parent.exists() else [werewolf_web.RealtimeWerewolf(self)]
        )))

    def signup(self, mensch, anzahlung=None):
        gefolge_web.util.log('eventConfirmSignup', {
            'event': self.event_id,
            'person': mensch.snowflake,
            'anzahlung': None if anzahlung is None else anzahlung.value
        })
        if 'menschen' not in self.data:
            self.data['menschen'] = []
        person_data = {
            'id': mensch.snowflake,
            'signup': '{:%Y-%m-%dT%H:%M:%S}'.format(gefolge_web.util.now(self.timezone))
        }
        if anzahlung is not None:
            person_data['anzahlung'] = anzahlung.value
        self.data['menschen'].append(person_data)
        if 'role' in self.data:
            gefolge_web.peter.add_role(mensch, self.data['role'], check=False)
        if self.orga('Abrechnung') == gefolge_web.login.Mensch.admin():
            gefolge_web.peter.channel_msg(self.channel, '<@{}>: du bist jetzt für {} angemeldet. Du kannst dich auf <https://gefolge.org/event/{}/programm> für Programmpunkte als interessiert eintragen'.format(mensch.snowflake, self, self.event_id), check=False)
        else:
            gefolge_web.peter.channel_msg(self.channel, '<@{}>: du bist jetzt für {} angemeldet. Fülle bitte bei Gelegenheit noch dein Profil auf <https://gefolge.org/event/{}/me/edit> aus. Außerdem kannst du dich auf <https://gefolge.org/event/{}/programm> für Programmpunkte als interessiert eintragen'.format(mensch.snowflake, self, self.event_id, self.event_id), check=False)

    def signup_guest(self, mensch, guest_name):
        if any(str(guest) == guest_name for guest in self.guests):
            raise ValueError('Duplicate guest name: {!r}'.format(guest_name))
        available_ids = [i for i in range(1, 100) if not any(guest.snowflake == i for guest in self.guests)]
        guest_id = random.choice(available_ids)
        gefolge_web.util.log('eventSignupGuest', {
            'event': self.event_id,
            'person': guest_id,
            'name': guest_name,
            'via': mensch.snowflake
        })
        self.data['menschen'].append({
            'id': guest_id,
            'name': guest_name,
            'via': mensch.snowflake
        })
        if self.anzahlung == gefolge_web.util.Euro() or self.orga('Abrechnung') == gefolge_web.login.Mensch.admin():
            gefolge_web.peter.channel_msg(self.channel, '<@{}> hat {} für {} angemeldet'.format(mensch.snowflake, guest_name, self))
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
        if 'start' in self.data:
            return gefolge_web.util.parse_iso_datetime(self.data['start'].value(), tz=self.timezone)

    @property
    def timezone(self):
        if 'timezone' in self.data:
            return pytz.timezone(self.data['timezone'].value())
        elif self.location is not None:
            return self.location.timezone
        else:
            return pytz.timezone('Europe/Berlin')

    def to_ical(self):
        result = icalendar.Event()
        result.add('summary', str(self))
        result.add('dtstart', self.start) #TODO add support for personal start time based on profile
        result.add('dtend', self.end) #TODO add support for personal end time based on profile
        #TODO date created
        #TODO date last modified
        result.add('uid', 'gefolge-event-{}@gefolge.org'.format(self.event_id))
        result.add('location', self.location.address)
        result.add('url', flask.url_for('event_page', event=self.event_id, _external=True))
        return result

    @property
    def url_part(self):
        return self.event_id

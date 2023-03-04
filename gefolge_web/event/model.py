import datetime
import itertools

import flask # PyPI: Flask
import icalendar # PyPI: icalendar
import jinja2 # PyPI: Jinja2
import pytz # PyPI: pytz

import class_key # https://github.com/fenhl/python-class-key
import peter # https://github.com/dasgefolge/peter-discord

import gefolge_web.db
import gefolge_web.login
import gefolge_web.person
import gefolge_web.util

EVENTS_ROOT = gefolge_web.util.BASE_PATH / 'event'
ORGA_ROLES = ['Abrechnung', 'Buchung', 'Essen', 'Programm', 'Schlüssel']
SILVESTER_CHANNEL = 387264349678338049

class EventGuest(gefolge_web.person.Guest):
    def __init__(self, event, guest_id):
        self.event = event
        self.snowflake = int(guest_id) # not actually a snowflake but uses this variable name for compatibility with the DiscordPerson class
        if not any('via' in person and person['id'] == self.snowflake for person in event.data.get('menschen', [])):
            raise ValueError('Es gibt keinen Gast mit dieser ID.')

    def __eq__(self, other):
        return isinstance(other, EventGuest) and self.event == other.event and self.snowflake == other.snowflake

    def __hash__(self):
        return hash((self.event, self.snowflake))

    def __html__(self):
        return jinja2.escape(str(self))

    def __repr__(self):
        return f'gefolge_web.event.model.EventGuest({self.event!r}, {self.snowflake!r})'

    def __str__(self):
        return self.event.attendee_data(self)['name'].value()

    @property
    def url_part(self):
        return str(self.snowflake)

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
            )] if self.location is not None and not self.location.is_online and 'host' not in self.location.data else []
        ), itertools.chain.from_iterable(
            programmpunkt.calendar_events
            for programmpunkt in self.programm
        )))

    def can_edit(self, editor, profile):
        if editor.is_admin:
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
        if self.proxy(profile) == editor:
            # Gastprofile dürfen von ihren proxies bearbeitet werden
            return True
        return False

    def capacity(self, night):
        if 'capacity' in self.data:
            if isinstance(self.data['capacity'].value(), dict):
                return self.data['capacity']['{:%Y-%m-%d}'.format(night)].value()
            else:
                return self.data['capacity'].value()
        else:
            return self.location.capacity

    @property
    def channel(self):
        return self.data.get('channel', SILVESTER_CHANNEL)

    def confirm_guest_signup(self, guest, *, message):
        gefolge_web.util.log('eventConfirmSignup', {
            'event': self.event_id,
            'person': guest.snowflake
        })
        self.attendee_data(guest)['signup'] = f'{gefolge_web.util.now(self.timezone):%Y-%m-%dT%H:%M:%S}' #TODO Datum der Überweisung verwenden
        if guest.is_active and 'role' in self.data:
            peter.add_role(guest, self.data['role'].value())
        if message:
            peter.channel_msg(self.channel, '<@{proxy_snowflake}>: {guest} ist jetzt für {event} angemeldet. Fülle bitte bei Gelegenheit noch das Profil auf <https://gefolge.org/event/{event_id}/mensch/{guest_snowflake}/edit> aus. Außerdem kannst du {guest} auf <https://gefolge.org/event/{event_id}/programm> für Programmpunkte als interessiert eintragen'.format(
                proxy_snowflake=self.proxy(guest).snowflake,
                guest=f'<@{guest.snowflake}>' if guest.is_active else guest,
                event=self,
                event_id=self.event_id,
                guest_snowflake=guest.snowflake
            ))

    @property
    def data(self):
        return gefolge_web.util.cached_json(gefolge_web.db.PgFile('events', self.event_id))

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
    def guest_signup_block_reason(self):
        return self.data.get('guestSignupBlockReason', self.data.get('signupBlockReason'))

    @property
    def guests(self):
        return [
            EventGuest(self, person['id']) if person['id'] < 100 else gefolge_web.login.DiscordGuest(person['id'])
            for person in self.data.get('menschen', [])
            if 'via' in person
        ]

    @property
    def location(self):
        import gefolge_web.event.location

        loc_id = self.data.get('location')
        if loc_id is not None:
            return gefolge_web.event.location.Location(loc_id)

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

    def night_log(self, attendee_data, night):
        if hasattr(attendee_data, 'snowflake'):
            attendee_data = self.attendee_data(attendee_data)
        result = attendee_data.get('nights', {}).get('{:%Y-%m-%d}'.format(night), {'going': 'maybe', 'lastUpdated': None})
        if isinstance(result, str):
            return []
        else:
            return result.get('log', [])

    def night_status_change(self, attendee_data, night):
        if hasattr(attendee_data, 'snowflake'):
            attendee_data = self.attendee_data(attendee_data)
        result = attendee_data.get('nights', {}).get('{:%Y-%m-%d}'.format(night), {'going': 'maybe', 'lastUpdated': None})
        if isinstance(result, str):
            result = None
        else:
            result = result['lastUpdated']
        if result is not None:
            return gefolge_web.util.parse_iso_datetime(result, tz=pytz.utc)

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
        elif int(snowflake) < 100:
            return EventGuest(self, snowflake)
        else:
            return gefolge_web.login.DiscordPerson(snowflake)

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
        ), ([] if self.start is None or (self.location is not None and self.location.is_online) else (
            gefolge_web.event.programm.essen.Abendessen(self, date)
            for date in self.nights
        )), (
            # Before Lore Seeker was discontinued, Custom Magic Drafts were a regular part of every event.
            # Now the repo is no longer cloned on the server where gefolge.org runs, so showing them for future events would cause errors.
            [] if self.start is None or self.start >= pytz.utc.localize(datetime.datetime(2021, 1, 1)) or self.event_id in gefolge_web.event.programm.magic.config().get('skippedEvents', []) else [gefolge_web.event.programm.magic.CustomMagicDraft(self)]
        ), (
            [] if werewolf_web is None or not werewolf_web.Setup(self).data_path.parent.exists() else [werewolf_web.RealtimeWerewolf(self)]
        )))

    def proxy(self, guest):
        """The person who invited this guest to this event. Also called “via”. `None` if `guest` is not a guest."""
        if guest.is_guest:
            return gefolge_web.login.Mensch(self.attendee_data(guest)['via'].value())

    @property
    def rooms(self):
        if self.location is None:
            return None
        return self.location.rooms_for(self)

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
            peter.add_role(mensch, self.data['role'].value())
        if self.orga('Abrechnung').is_treasurer:
            peter.channel_msg(self.channel, '<@{}>: du bist jetzt für {} angemeldet. Du kannst dich auf <https://gefolge.org/event/{}/programm> für Programmpunkte als interessiert eintragen'.format(mensch.snowflake, self, self.event_id))
        else:
            peter.channel_msg(self.channel, '<@{}>: du bist jetzt für {} angemeldet. Fülle bitte bei Gelegenheit noch dein Profil auf <https://gefolge.org/event/{}/me/edit> aus. Außerdem kannst du dich auf <https://gefolge.org/event/{}/programm> für Programmpunkte als interessiert eintragen'.format(mensch.snowflake, self, self.event_id, self.event_id))

    @property
    def signup_block_reason(self):
        return self.data.get('signupBlockReason')

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

    def transaction(self, mensch):
        return self.transactions()[mensch] #TODO include guests

    def transactions(self):
        details = {person: [] for person in self.signups}
        # Anzahlung
        for person in self.signups:
            if 'anzahlung' in self.attendee_data(person):
                anzahlung = self.attendee_data(person)['anzahlung'].value()
            else:
                anzahlung = self.anzahlung.value
            if anzahlung != 0:
                details[person].append({
                    'amount': anzahlung,
                    'label': 'Anzahlung',
                    'type': 'flat'
                })
        raise NotImplementedError() #TODO populate details
        return {
            person: {
                'amount': sum(detail['amount'] for detail in details),
                'details': details,
                'event': self.event_id,
                'time': '{:%Y-%m-%dT%H:%M:%SZ}'.format(gefolge_web.util.now(pytz.utc)),
                'type': 'eventAbrechnung'
            }
            for person, details in details.items()
        }

    def travel_with(self, person, travel):
        """Helper method since Jinja doesn't have while loops"""
        seen = set()
        while self.attendee_data(person)[travel].get('type') == 'with':
            person = self.person(self.attendee_data(person)[travel]['with'].value())
            if person in seen:
                return person
            else:
                seen.add(person)
        return person

    @property
    def url_part(self):
        return self.event_id

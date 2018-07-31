import functools
import jinja2
import lazyjson
import random
import re

import gefolge_web.login
import gefolge_web.util

EVENTS_ROOT = pathlib.Path('/usr/local/share/fidera/event')
LOCATIONS_ROOT = pathlib.Path('/usr/local/share/fidera/loc')
ORGA_ROLES = ['Abrechnung', 'Buchung', 'Essen', 'Programm', 'Schlüssel']

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
        return 'gefolge_web.event.model.Guest({!r}, {!r})'.format(self.event, self.snowflake)

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
        return 'gefolge_web.event.model.Location({!r})'.format(self.loc_id)

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
    def __new__(self, event=None, name=None, *, event_id=None):
        if re.fullmatch('abendessen[0-9]+-[0-9]+-[0-9]+', name):
            return Abendessen(event=event, name=name, event_id=event_id)
        else:
            return super().__new__(self, event=event, name=name, event_id=event_id)

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
        else:
            raise TypeError('Missing event or event_id argument for Programmpunkt constructor')

    def __eq__(self, other):
        return isinstance(other, Programmpunkt) and self.event == other.event and self.name == other.name

    def __lt__(self, other):
        if not isinstance(other, Programmpunkt):
            return NotImplemented
        return (self.start is None, self.start, self.event, self.name) < (other.start is None, other.start, other.event, other.name)

    def __repr__(self):
        return 'gefolge_web.event.model.Programmpunkt({!r}, {!r})'.format(self.event, self.name)

    def __str__(self):
        return self.name

    def can_edit(self, editor):
        return self.orga == editor or self.event.orga('Programm') == editor

    def can_signup(self, editor, person):
        return (
            (editor == person or editor == self.event.orga('Programm'))
            and person in self.event.signups
            and person not in self.signups
            and len(self.signups) < self.data.get('limit', float('inf'))
            and not self.data.get('closed', False)
        )

    @property
    def data(self):
        return self.event.data['programm'][self.name]

    @property
    def description(self):
        return self.data.get('description')

    @description.setter
    def description(self, value):
        self.data['description'] = value

    @property
    def end(self):
        end_str = self.data.get('end')
        if end_str is not None:
            return gefolge_web.util.parse_iso_datetime(end_str)

    @end.setter
    def end(self, value):
        if value is None:
            del self.end
        else:
            self.data['end'] = '{:%Y-%m-%d %H:%M:%S}'.format(value)

    @end.deleter
    def end(self):
        if 'end' in self.data:
            del self.data['end']

    @property
    def listed(self):
        """Whether this shows up in the list. Calendar and timetable are unaffected."""
        return True

    @property
    def orga(self):
        orga_id = self.data['orga'].value()
        if orga_id is not None:
            return gefolge_web.login.Mensch(orga_id)

    @orga.setter
    def orga(self, value):
        self.data['orga'] = value.snowflake

    def signup(self, person):
        gefolge_web.util.log('eventProgrammSignup', {
            'event': self.event.event_id,
            'programmpunkt': self.name,
            'person': person.snowflake
        })
        self.data['signups'].append(person.snowflake)

    @property
    def signups(self):
        return [
            self.event.person(snowflake)
            for snowflake in self.data['signups'].value()
        ]

    @property
    def start(self):
        start_str = self.data.get('start')
        if start_str is not None:
            return gefolge_web.util.parse_iso_datetime(start_str)

    @start.setter
    def start(self, value):
        if value is None:
            del self.start
        else:
            self.data['start'] = '{:%Y-%m-%d %H:%M:%S}'.format(value)

    @start.deleter
    def start(self):
        if 'start' in self.data:
            del self.data['start']

class Abendessen(Programmpunkt):
    def __new__(cls, event=None, name=None, *, event_id=None):
        return object.__new__(cls, event=event, name=name, event_id=event_id)

    def __init__(self, event=None, name=None, *, event_id=None):
        if isinstance(name, datetime.date):
            name = 'abendessen{:%Y-%m-%d}'.format(name)
        super().__init__(self, event=event, name=name, event_id=event_id)
        self.date = datetime.date(*map(int, re.fullmatch('abendessen([0-9]+)-([0-9]+)-([0-9]+)', self.name).groups()))
        self.name = 'abendessen{:%Y-%m-%d}'.format(self.date) # normalize name

    def __repr__(self):
        return 'gefolge_web.event.model.Abendessen({!r}, {!r})'.format(self.event, self.name)

    def __str__(self):
        return 'Abendessen'

    def can_edit(self, editor):
        return self.orga == editor or self.event.orga('Essen') == editor

    def can_signup(self, editor, person):
        return False

    @property
    def data(self):
        return self.event.data.get('essen', {}).get('{:%Y-%m-%d}'.format(self.date), {})

    @property
    def description(self):
        return self.data.get('dinner')

    @description.setter
    def description(self, value):
        if 'essen' not in self.event.data:
            self.event.data['essen'] = {}
        if '{:%Y-%m-%d}'.format(self.date) not in self.event.data['essen']:
            self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)] = {}
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['dinner'] = value

    @property
    def end(self):
        return datetime.datetime.combine(self.date, pytz.timezone('Europe/Berlin').localize(datetime.time(20))) #TODO make configurable

    @end.setter
    def end(self, value):
        if value == self.end:
            return
        raise NotImplementedError('Abendessenzeiten können noch nicht geändert werden') #TODO

    @end.deleter
    def end(self):
        raise TypeError('Abendessenzeiten können nicht gelöscht werden')

    @property
    def listed(self):
        return False

    @property
    def orga(self):
        return self.event.person(self.data.get('orga', self.event.orga('Essen')))

    @orga.setter
    def orga(self, value):
        if 'essen' not in self.event.data:
            self.event.data['essen'] = {}
        if '{:%Y-%m-%d}'.format(self.date) not in self.event.data['essen']:
            self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)] = {}
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['orga'] = value.snowflake

    @property
    def signups(self):
        return []

    @property
    def start(self):
        return datetime.datetime.combine(self.date, pytz.timezone('Europe/Berlin').localize(datetime.time(19))) #TODO make configurable

    @start.setter
    def start(self, value):
        if value == self.start:
            return
        raise NotImplementedError('Abendessenzeiten können noch nicht geändert werden') #TODO

    @start.deleter
    def start(self):
        raise TypeError('Abendessenzeiten können nicht gelöscht werden')

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

    def attendee_data(self, person):
        for iter_data in self.data['menschen']:
            if iter_data['id'].value() == person.snowflake:
                return iter_data

    @property
    def ausfall(self):
        if 'ausfall' in self.data:
            return gefolge_web.util.Euro(self.data['ausfall'].value())
        else:
            return gefolge_web.util.Euro()

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

    def essen(self, date):
        if date in self.nights:
            return Abendessen(self, date)
        else:
            raise ValueError('Datum liegt außerhalb des event')

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

    @property
    def orga_unassigned(self):
        return [role for role in ORGA_ROLES if self.orga(role) is None]

    def person(self, snowflake):
        if hasattr(snowflake, 'snowflake'):
            snowflake = snowflake.snowflake
        if int(snowflake) < 100:
            result = Guest(self, snowflake)
        else:
            result = gefolge_web.login.Mensch(snowflake)
            if not result.is_active:
                raise ValueError('Dieser Discord account existiert nicht oder ist nicht im Gefolge.')
        return result

    @property
    def programm(self):
        return sorted(itertools.chain(
            Programmpunkt(self, name)
            for name in self.data['programm'].value()
        ), (
            Abendessen(self, date)
            for date in self.nights
        ))

    def signup(self, mensch):
        gefolge_web.util.log('eventConfirmSignup', {
            'event': self.event_id,
            'person': mensch.snowflake
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
            'event': self.event_id,
            'person': guest_id,
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

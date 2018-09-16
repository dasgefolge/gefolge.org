import class_key
import itertools
import jinja2
import lazyjson
import pathlib
import peter
import random

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

    @property
    def __key__(self):
        return self.start, self.end, self.event_id

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
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
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
        if profile.is_guest and profile.via == editor:
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
        import gefolge_web.event.programm.essen

        if date in self.nights:
            return gefolge_web.event.programm.essen.Abendessen(self, date)
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

        return sorted(itertools.chain((
            gefolge_web.event.programm.Programmpunkt(self, name)
            for name in self.data['programm'].value()
            if name != 'custom-magic-draft' # draft is already listed below
        ), (
            gefolge_web.event.programm.essen.Abendessen(self, date)
            for date in self.nights
        ), [
            gefolge_web.event.programm.magic.CustomMagicDraft(self)
        ]))
        #TODO rtww-Abstimmungen

    def signup(self, mensch):
        gefolge_web.util.log('eventConfirmSignup', {
            'event': self.event_id,
            'person': mensch.snowflake
        })
        self.data['menschen'].append({
            'id': mensch.snowflake,
            'signup': '{:%Y-%m-%d %H:%M:%S}'.format(gefolge_web.util.now()) #TODO Datum der Überweisung verwenden
        })
        if 'role' in self.data:
            peter.bot_cmd('add-role', str(mensch.snowflake), str(self.data['role']))

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
            'name': guest_name,
            'via': mensch.snowflake
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

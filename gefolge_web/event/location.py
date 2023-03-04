import dataclasses

import jinja2 # PyPI: Jinja2
import more_itertools # PyPI: more-itertools
import pytz # PyPI: pytz

import gefolge_web.db
import gefolge_web.event.model
import gefolge_web.login
import gefolge_web.util

LOCATIONS_ROOT = gefolge_web.util.BASE_PATH / 'loc'

class Location:
    def __new__(cls, loc_id):
        if loc_id == 'online':
            return Online()
        else:
            return super().__new__(cls)

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
    def capacity(self):
        return self.data['capacity'].value()

    @property
    def data(self):
        return gefolge_web.util.cached_json(gefolge_web.db.PgFile('locations', self.loc_id))

    @property
    def hausordnung(self):
        return self.data.get('hausordnung')

    @property
    def is_online(self):
        return False

    @property
    def prefix(self):
        return self.data.get('prefix', 'in ')

    def rooms_for(self, event):
        return EventRooms(self, event)

    @property
    def timezone(self):
        return pytz.timezone(self.data['timezone'].value())

class Online(Location):
    def __new__(cls, loc_id='online'):
        return object.__new__(cls)

    def __init__(self, loc_id='online'):
        super().__init__('online')

    @property
    def capacity(self):
        return float('inf')

    @property
    def is_online(self):
        return True

    def rooms_for(self, event):
        return None

    @property
    def timezone(self):
        return pytz.timezone('Europe/Berlin')

@dataclasses.dataclass(frozen=True)
class EventRooms:
    location: Location
    event: gefolge_web.event.model.Event

    def __bool__(self):
        return 'rooms' in self.location.data

    def __iter__(self):
        for section in self.location.data.get('rooms', {}).values():
            for room_name in section:
                yield self.room(room_name)

    def get(self, person):
        data = self.event.attendee_data(person)
        if data is None or data.get('room') is None:
            return None
        return self.room(data['room'].value())

    def room(self, room_name):
        return Room(self.location, self.event, room_name)

@dataclasses.dataclass(frozen=True)
class Room:
    location: Location
    event: gefolge_web.event.model.Event
    name: str

    def __str__(self):
        return self.name

    @property
    def beds(self):
        return self.data['beds'].value()

    @property
    def data(self):
        return more_itertools.one(
            section
            for section in self.location.data['rooms']
            if self.name in section
        )[self.name]

    @property
    def description(self):
        return f'Zimmer {self} ({self.section}, {self.free} von {self.beds} Betten frei)'

    @property
    def free(self): #TODO night-based
        return self.beds - len(self.people)

    @property
    def people(self): #TODO night-based
        return [
            person
            for person in self.event.signups
            if self.event.attendee_data(person).get('room') == self.name
        ]

    @property
    def reserved(self):
        return self.data.get('reserved', False)

    @property
    def section(self):
        return more_itertools.one(
            section
            for section in self.location.data['rooms']
            if self.name in section
        ).key

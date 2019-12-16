import dataclasses

import jinja2 # PyPI: Jinja2
import pytz # PyPI: pytz

import gefolge_web.event.model
import gefolge_web.login
import gefolge_web.util

LOCATIONS_ROOT = gefolge_web.util.BASE_PATH / 'loc'

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

    def rooms_for(self, event):
        return EventRooms(self, event)

    @property
    def timezone(self):
        return pytz.timezone(self.data['timezone'].value())

@dataclasses.dataclass(frozen=True)
class EventRooms:
    location: Location
    event: gefolge_web.event.model.Event

    def __bool__(self):
        return 'rooms' in self.location.data

    def get(self, person):
        data = self.event.attendee_data(person)
        if data is None:
            return None
        return data.get('room')

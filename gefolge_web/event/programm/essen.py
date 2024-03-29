import datetime
import re

import jinja2 # PyPI: Jinja2

import gefolge_web.event.programm
import gefolge_web.login
import gefolge_web.util

class Abendessen(gefolge_web.event.programm.Programmpunkt):
    def __new__(cls, event, programmpunkt):
        return object.__new__(cls)

    def __init__(self, event, programmpunkt):
        if isinstance(programmpunkt, datetime.date):
            programmpunkt = 'abendessen{:%Y-%m-%d}'.format(programmpunkt)
        self.date = datetime.date(*map(int, re.fullmatch('abendessen([0-9]+)-([0-9]+)-([0-9]+)', programmpunkt).groups()))
        super().__init__(event, programmpunkt)

    def __repr__(self):
        return 'gefolge_web.event.programm.essen.Abendessen({!r}, {!r})'.format(self.event, self.url_part)

    def assert_exists(self):
        if self.date < self.event.start.date():
            raise ValueError('Am {:%d.%m.%Y} hat {} noch nicht angefangen.'.format(self.date, self.event))
        elif self.date < self.event.end.date():
            pass # date is correct
        elif self.date == self.event.end.date():
            raise ValueError('Der {:%d.%m.%Y} ist der Abreisetag von {}.'.format(self.date, self.event))
        else:
            raise ValueError('Am {:%d.%m.%Y} ist {} schon vorbei.'.format(self.date, self.event))

    @property
    def calendar_events(self):
        return super().calendar_events + ([gefolge_web.event.programm.CalendarEvent(
            self, 'vorbereitung',
            text='Silvesterbuffet: Vorbereitung',
            html=jinja2.Markup('{}: Vorbereitung'.format(self.__html__())),
            start=self.start - datetime.timedelta(hours=4),
            end=self.start,
        )] if self.date.month == 12 and self.date.day == 31 else [])

    def can_edit(self, editor):
        if editor.is_admin:
            return True # always allow the admin to edit since they have write access to the database anyway
        if self.event.orga('Programm') == editor:
            return True # allow the Programm orga to edit past events for archival purposes
        if self.event.end < gefolge_web.util.now(self.event.timezone):
            return False # event frozen
        return self.orga == editor or self.event.orga('Essen') == editor

    def can_signup(self, editor, person):
        if editor.is_admin:
            return True # always allow the admin to edit since they have write access to the database anyway
        return False

    @property
    def css_class(self):
        return self.data.get('cssClass', 'programm-essen')

    @css_class.setter
    def css_class(self, value):
        self.data['cssClass'] = value

    @property
    def data(self):
        return self.event.data.get('essen', {}).get('{:%Y-%m-%d}'.format(self.date), {})

    @property
    def description(self):
        return self.data.get('dinner', '')

    @description.setter
    def description(self, value):
        if 'essen' not in self.event.data:
            self.event.data['essen'] = {}
        if '{:%Y-%m-%d}'.format(self.date) not in self.event.data['essen']:
            self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)] = {}
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['dinner'] = value

    @property
    def end(self):
        if 'dinnerEnd' in self.data:
            return gefolge_web.util.parse_iso_datetime(self.data['dinnerEnd'], tz=self.timezone)
        elif self.date.month == 12 and self.date.day == 31:
            return self.timezone.localize(datetime.datetime.combine(self.date, datetime.time(23, 55)), is_dst=None)
        else:
            return self.start + datetime.timedelta(hours=1)

    @end.setter
    def end(self, value):
        if value is None:
            del self.end
        if 'essen' not in self.event.data:
            self.event.data['essen'] = {}
        if '{:%Y-%m-%d}'.format(self.date) not in self.event.data['essen']:
            self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)] = {}
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['dinnerEnd'] = '{:%Y-%m-%dT%H:%M:%S}'.format(value)

    @end.deleter
    def end(self):
        raise TypeError('Abendessenzeiten können nicht gelöscht werden')

    @property
    def listed(self):
        return False

    @property
    def name(self):
        if self.date.month == 12 and self.date.day == 31:
            return 'Silvesterbuffet'
        else:
            return 'Abendessen'

    @property
    def name_editable(self):
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
    def orga_notes(self):
        return gefolge_web.util.render_template('event.orga-notes-essen', event=self.event, programmpunkt=self)

    @property
    def orga_role(self):
        return 'Essen'

    @property
    def signups(self):
        night_maybes = self.event.night_signups(self.date) + self.event.night_maybes(self.date)
        return [
            person
            for person in self.event.signups
            if person in night_maybes
            #TODO Selbstversorger
        ]

    @property
    def start(self):
        if 'dinnerStart' in self.data:
            return gefolge_web.util.parse_iso_datetime(self.data['dinnerStart'], tz=self.timezone)
        elif self.date.month == 12 and self.date.day == 31:
            return self.timezone.localize(datetime.datetime.combine(self.date, datetime.time(22)), is_dst=None)
        else:
            return self.timezone.localize(datetime.datetime.combine(self.date, datetime.time(19)), is_dst=None)

    @start.setter
    def start(self, value):
        if value is None:
            del self.start
        if 'essen' not in self.event.data:
            self.event.data['essen'] = {}
        if '{:%Y-%m-%d}'.format(self.date) not in self.event.data['essen']:
            self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)] = {}
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['dinnerStart'] = '{:%Y-%m-%dT%H:%M:%S}'.format(value)

    @start.deleter
    def start(self):
        raise TypeError('Abendessenzeiten können nicht gelöscht werden')

import datetime
import pytz
import re

import gefolge_web.event.programm
import gefolge_web.login
import gefolge_web.util

class Abendessen(gefolge_web.event.programm.Programmpunkt):
    def __new__(cls, event, programmpunkt):
        return object.__new__(cls)

    def __init__(self, event, programmpunkt):
        if isinstance(programmpunkt, datetime.date):
            programmpunkt = 'abendessen{:%Y-%m-%d}'.format(programmpunkt)
        super().__init__(event, programmpunkt)
        self.date = datetime.date(*map(int, re.fullmatch('abendessen([0-9]+)-([0-9]+)-([0-9]+)', self.name).groups()))
        self.name = 'abendessen{:%Y-%m-%d}'.format(self.date) # normalize name

    def __repr__(self):
        return 'gefolge_web.event.programm.essen.Abendessen({!r}, {!r})'.format(self.event, self.name)

    def __str__(self):
        if self.date.month == 12 and self.date.day == 31:
            return 'Silvesterbuffet'
        else:
            return 'Abendessen'

    def assert_exists(self):
        if self.date < self.event.start.date():
            raise ValueError('Am {:%d.%m.%Y} hat {} noch nicht angefangen.'.format(self.date, self.event))
        elif self.date < self.event.end.date():
            pass # date is correct
        elif self.date == self.event.end.date():
            raise ValueError('Der {:%d.%m.%Y} ist der Abreisetag von {}.'.format(self.date, self.event))
        else:
            raise ValueError('Am {:%d.%m.%Y} ist {} schon vorbei.'.format(self.date, self.event))

    def can_edit(self, editor):
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
        if self.event.end < gefolge_web.util.now():
            return False # event frozen
        return self.orga == editor or self.event.orga('Essen') == editor

    def can_signup(self, editor, person):
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
        return False

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
            return gefolge_web.util.parse_iso_datetime(self.data['dinnerEnd'])
        elif self.date.month == 12 and self.date.day == 31:
            return pytz.timezone('Europe/Berlin').localize(datetime.datetime.combine(self.date, datetime.time(23, 55)))
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
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['dinnerEnd'] = '{:%Y-%m-%d %H:%M:%S}'.format(value)

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
        if 'dinnerStart' in self.data:
            return gefolge_web.util.parse_iso_datetime(self.data['dinnerStart'])
        elif self.date.month == 12 and self.date.day == 31:
            return pytz.timezone('Europe/Berlin').localize(datetime.datetime.combine(self.date, datetime.time(22)))
        else:
            return pytz.timezone('Europe/Berlin').localize(datetime.datetime.combine(self.date, datetime.time(19)))

    @start.setter
    def start(self, value):
        if value is None:
            del self.start
        if 'essen' not in self.event.data:
            self.event.data['essen'] = {}
        if '{:%Y-%m-%d}'.format(self.date) not in self.event.data['essen']:
            self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)] = {}
        self.event.data['essen']['{:%Y-%m-%d}'.format(self.date)]['dinnerStart'] = '{:%Y-%m-%d %H:%M:%S}'.format(value)

    @start.deleter
    def start(self):
        raise TypeError('Abendessenzeiten können nicht gelöscht werden')

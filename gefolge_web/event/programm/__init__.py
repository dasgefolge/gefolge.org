import flask
import flask_wtf
import functools
import icalendar
import more_itertools
import re
import wtforms

import gefolge_web.login
import gefolge_web.util

@functools.total_ordering
class Programmpunkt:
    def __new__(cls, event=None, name=None, *, event_id=None):
        if name == 'custom-magic-draft':
            import gefolge_web.event.programm.magic

            return gefolge_web.event.programm.magic.CustomMagicDraft(event=event, name=name, event_id=event_id)
        elif re.fullmatch('abendessen[0-9]+-[0-9]+-[0-9]+', name):
            import gefolge_web.event.programm.essen

            return gefolge_web.event.programm.essen.Abendessen(event=event, name=name, event_id=event_id)
        else:
            return super().__new__(cls)

    def __init__(self, event=None, name=None, *, event_id=None):
        # event can be specified by event or event_id argument
        if name is None:
            raise TypeError('Missing name argument for Programmpunkt constructor')
        else:
            self.name = name
        if event is not None:
            self.event = event
        elif event_id is not None:
            import gefolge_web.event.model

            self.event = gefolge_web.event.model.Event(event_id)
        else:
            raise TypeError('Missing event or event_id argument for Programmpunkt constructor')

    def __eq__(self, other):
        return isinstance(other, Programmpunkt) and self.event == other.event and self.name == other.name

    def __lt__(self, other):
        if not isinstance(other, Programmpunkt):
            return NotImplemented
        return (self.start is None, self.start, self.event, self.name) < (other.start is None, other.start, other.event, other.name)

    def __repr__(self):
        return 'gefolge_web.event.programm.Programmpunkt({!r}, {!r})'.format(self.event, self.name)

    def __str__(self):
        return self.name

    def add_form_details(self, Form, editor):
        pass # subclasses may override

    def can_edit(self, editor):
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
        if self.event.end < gefolge_web.util.now():
            return False # event frozen
        return self.orga == editor or self.event.orga('Programm') == editor

    def can_signup(self, editor, person):
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
        if self.event.end < gefolge_web.util.now():
            return False # event frozen
        return (
            (editor == person or (person.is_guest and person.via == editor) or editor == self.event.orga('Programm'))
            and person in self.event.signups
            and person not in self.signups
            and len(self.signups) < self.signup_limit
            and not self.data.get('closed', False)
        )

    @property
    def data(self):
        return self.event.data['programm'].get(self.name, {})

    @property
    def description(self):
        return self.data.get('description', '')

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

    def form(self, editor):
        class Form(flask_wtf.FlaskForm):
            pass

        people_allowed_to_sign_up = list(filter(lambda person: self.can_signup(editor, person), self.event.signups))
        if len(people_allowed_to_sign_up) == 0:
            submit_text = None # don't show submit field unless overridden by a subclass in add_form_details
        elif len(people_allowed_to_sign_up) == 1:
            if more_itertools.one(people_allowed_to_sign_up) == editor:
                submit_text = self.data.get('signupButton', 'Als interessiert markieren')
            else:
                submit_text = self.data.get('signupOtherButton', '{} als interessiert markieren').format(more_itertools.one(people_allowed_to_sign_up))
            Form.submit_programmpunkt_form = wtforms.SubmitField(submit_text)
        else:
            Form.person_to_signup = gefolge_web.forms.EventPersonField(self.event, 'Mensch', person_filter=lambda person: person in people_allowed_to_sign_up)
            submit_text = self.data.get('signupOtherButton', '{} als interessiert markieren').format('Gewählte Person')

        self.add_form_details(Form, editor)

        if submit_text is not None:
            Form.submit_programmpunkt_form = wtforms.SubmitField(submit_text)
        return Form()

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

    def process_form_details(self, form, editor):
        pass # subclasses may override

    def process_form_submission(self, form, editor):
        if hasattr(form, 'person_to_signup'):
            person_to_signup = form.person_to_signup.data
        else:
            person_to_signup = more_itertools.one(filter(lambda person: self.can_signup(editor, person), self.event.signups))
        if not self.can_signup(editor, person_to_signup):
            flask.flash('Du bist nicht berechtigt, {} für diesen Programmpunkt anzumelden.'.format(person_to_signup))
            return flask.redirect(flask.url_for('event_programmpunkt', event_id=self.event.event_id, name=self.name))
        self.signup(person_to_signup)
        self.process_form_details(form, editor)

    def signup(self, person):
        gefolge_web.util.log('eventProgrammSignup', {
            'event': self.event.event_id,
            'programmpunkt': self.name,
            'person': person.snowflake
        })
        if 'signups' not in self.data:
            self.data['signups'] = [person.snowflake for person in self.signups]
        self.data['signups'].append(person.snowflake)

    @property
    def signup_limit(self):
        return self.data.get('limit', float('inf'))

    @property
    def signups(self):
        return [
            self.event.person(snowflake)
            for snowflake in self.data.get('signups', [])
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

    def to_ical(self):
        result = icalendar.Event()
        result.add('summary', str(self))
        result.add('dtstart', self.start)
        result.add('dtend', self.end)
        #TODO date created
        #TODO date last modified
        result.add('uid', 'gefolge-event-{}-{}@gefolge.org'.format(self.event.event_id, self.name))
        result.add('location', str(self.event.location)) #TODO add support for Programm at different locations
        #TODO URL to Programmpunkt web page
        return result

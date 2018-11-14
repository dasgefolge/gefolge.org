import class_key
import flask
import flask_wtf
import icalendar
import jinja2
import more_itertools
import re
import wtforms

import gefolge_web.login
import gefolge_web.util

@class_key.class_key()
class CalendarEvent:
    def __init__(self, programmpunkt, uid, text, html, start, end):
        self.programmpunkt = programmpunkt
        self.uid = uid
        self.text = text
        self.html = html
        self.start = start
        self.end = end

    def __html__(self):
        return self.html

    @property
    def __key__(self):
        return self.start, self.end, self.text

    def __str__(self):
        return self.text

    def to_ical(self):
        result = icalendar.Event()
        result.add('summary', self.text)
        result.add('dtstart', self.start)
        result.add('dtend', self.end)
        #TODO date created
        #TODO date last modified
        if isinstance(self.programmpunkt, Programmpunkt):
            result.add('uid', 'gefolge-event-{}-{}-{}@gefolge.org'.format(self.programmpunkt.event.event_id, self.programmpunkt.name, self.uid))
        else:
            result.add('uid', 'gefolge-event-{}-{}@gefolge.org'.format(self.programmpunkt.event_id, self.uid))
        result.add('location', str(self.programmpunkt.location))
        if isinstance(self.programmpunkt, Programmpunkt):
            result.add('url', flask.url_for('event_programmpunkt', event=self.programmpunkt.event.event_id, programmpunkt=self.programmpunkt.name, _external=True))
        else:
            result.add('url', flask.url_for('event_page', event=self.programmpunkt.event_id, _external=True))
        return result

@class_key.class_key()
class Programmpunkt:
    def __new__(cls, event, programmpunkt):
        try:
            import werewolf_web
        except ImportError:
            werewolf_web = None

        if programmpunkt == 'custom-magic-draft':
            import gefolge_web.event.programm.magic

            return gefolge_web.event.programm.magic.CustomMagicDraft(event)
        elif programmpunkt == 'rtww' and werewolf_web is not None:
            return werewolf_web.RealtimeWerewolf(event)
        elif re.fullmatch('abendessen[0-9]+-[0-9]+-[0-9]+', programmpunkt):
            import gefolge_web.event.programm.essen

            return gefolge_web.event.programm.essen.Abendessen(event, programmpunkt)
        else:
            return super().__new__(cls)

    def __init__(self, event, programmpunkt):
        # event can be specified by event or event_id argument
        if isinstance(event, str):
            import gefolge_web.event.model

            self.event = gefolge_web.event.model.Event(event)
        else:
            self.event = event
        self.name = programmpunkt
        self.assert_exists()

    def __html__(self):
        return jinja2.Markup('<a href="{}">{}</a>'.format(jinja2.escape(flask.url_for('event_programmpunkt', event=self.event.event_id, programmpunkt=self.name)), jinja2.escape(str(self))))

    @property
    def __key__(self):
        return self.start is None, self.start, self.event, self.name

    def __repr__(self):
        return 'gefolge_web.event.programm.Programmpunkt({!r}, {!r})'.format(self.event, self.name)

    def __str__(self):
        return self.name

    def add_form_details(self, Form, editor):
        return False # subclasses may override

    def assert_exists(self):
        if self.name not in self.event.data.get('programm', {}):
            raise ValueError('Es gibt auf {} keinen Programmpunkt namens {}.'.format(self.event, self.name))

    @property
    def calendar_events(self):
        if self.start is not None and self.end is not None:
            return [CalendarEvent(
                self, 'main',
                text=str(self),
                html=self.__html__(),
                start=self.start,
                end=self.end
            )]
        else:
            return []

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
        if 'programm' not in self.event.data:
            self.event.data['programm'] = {}
        if self.name not in self.event.data['programm']:
            self.event.data['programm'][self.name] = {}
        return self.event.data['programm'][self.name]

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
        import gefolge_web.event.forms

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
            Form.person_to_signup = gefolge_web.event.forms.PersonField(self.event, 'Mensch', person_filter=lambda person: person in people_allowed_to_sign_up, default=editor if editor in people_allowed_to_sign_up else people_allowed_to_sign_up[0])
            submit_text = self.data.get('signupOtherButton', '{} als interessiert markieren').format('Gewählte Person')

        if self.add_form_details(Form, editor) and submit_text is None:
            submit_text = self.data.get('editSignupButton', 'Änderungen speichern')

        if submit_text is not None:
            Form.submit_programmpunkt_form = wtforms.SubmitField(submit_text)
        return Form()

    @property
    def listed(self):
        """Whether this shows up in the list. Calendar and timetable are unaffected."""
        return True

    @property
    def location(self):
        return self.event.location #TODO add support for Programm at different locations

    @property
    def orga(self):
        orga_id = self.data.get('orga')
        if orga_id is not None:
            return gefolge_web.login.Mensch(orga_id)

    @orga.setter
    def orga(self, value):
        self.data['orga'] = value.snowflake

    @property
    def orga_notes(self):
        pass # subclasses may override

    @property
    def orga_role(self):
        return 'Programm' # subclasses may override

    def process_form_details(self, form, editor):
        pass # subclasses may override

    def process_form_submission(self, form, editor):
        people_allowed_to_sign_up = list(filter(lambda person: self.can_signup(editor, person), self.event.signups))
        if len(people_allowed_to_sign_up) > 0:
            if len(people_allowed_to_sign_up) == 1:
                person_to_signup = more_itertools.one(people_allowed_to_sign_up)
            else:
                person_to_signup = form.person_to_signup.data
            if not self.can_signup(editor, person_to_signup):
                flask.flash('Du bist nicht berechtigt, {} für diesen Programmpunkt anzumelden.'.format(person_to_signup), 'error')
                return flask.redirect(flask.url_for('event_programmpunkt', event=self.event.event_id, programmpunkt=self.name))
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
        if person.snowflake not in self.data['signups']:
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

    @property
    def url_part(self):
        return self.name

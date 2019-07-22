import challonge # package: pychal
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
        result.add('location', self.programmpunkt.location.address)
        if isinstance(self.programmpunkt, Programmpunkt):
            result.add('url', flask.url_for('event_programmpunkt', event=self.programmpunkt.event.event_id, programmpunkt=self.programmpunkt.name, _external=True))
        else:
            result.add('url', flask.url_for('event_page', event=self.programmpunkt.event_id, _external=True))
        return result

class Strings:
    def __init__(self, *, signup_header, signup_button, signup_other_button, edit_signup_button):
        self.signup_header = signup_header
        self.signup_button = signup_button
        self.signup_other_button = signup_other_button
        self.edit_signup_button = edit_signup_button

    @classmethod
    def defaults(cls):
        return cls(
            signup_header='Interessiert',
            signup_button='Als interessiert markieren',
            signup_other_button='{} als interessiert markieren',
            edit_signup_button='Änderungen speichern'
        )

    @classmethod
    def from_json(cls, json_data, defaults=None):
        if defaults is None:
            defaults = cls.defaults()
        return cls(
            signup_header=json_data.get('signupHeader', defaults.signup_header),
            signup_button=json_data.get('signupButton', defaults.signup_button),
            signup_other_button=json_data.get('signupOtherButton', defaults.signup_other_button),
            edit_signup_button=json_data.get('editSignupButton', defaults.edit_signup_button)
        )

    def to_json(self, defaults=None):
        if defaults is None:
            defaults = self.__class__.defaults()
        result = {}
        if self.signup_header != defaults.signup_header:
            result['signupHeader'] = self.signup_header
        if self.signup_button != defaults.signup_button:
            result['signupButton'] = self.signup_button
        if self.signup_other_button != defaults.signup_other_button:
            result['signupOtherButton'] = self.signup_other_button
        if self.edit_signup_button != defaults.edit_signup_button:
            result['editSignupButton'] = self.edit_signup_button
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
        if self.event.orga('Programm') == editor:
            return True # allow the Programm orga to edit past events for archival purposes
        if self.event.end < gefolge_web.util.now(self.event.timezone):
            return False # event frozen
        return self.orga == editor

    def can_signup(self, editor, person):
        if editor == gefolge_web.login.Mensch.admin():
            return True # always allow the admin to edit since they have write access to the database anyway
        if self.event.end < gefolge_web.util.now(self.event.timezone):
            return False # event frozen
        return (
            (editor == person or (person.is_guest and person.via == editor) or editor == self.event.orga('Programm'))
            and person in self.event.signups
            and person not in self.signups
            and len(self.signups) < self.signup_limit
            and not self.closed
        )

    @property
    def closed(self):
        return self.data.get('closed', False)

    @property
    def data(self):
        if 'programm' not in self.event.data:
            self.event.data['programm'] = {}
        if self.name not in self.event.data['programm']:
            self.event.data['programm'][self.name] = {}
        return self.event.data['programm'][self.name]

    @property
    def default_strings(self):
        return Strings.defaults()

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
            return gefolge_web.util.parse_iso_datetime(end_str, tz=self.timezone)

    @end.setter
    def end(self, value):
        if value is None:
            del self.end
        else:
            self.data['end'] = '{:%Y-%m-%dT%H:%M:%S}'.format(value)

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
                submit_text = self.strings.signup_button
            else:
                submit_text = self.strings.signup_other_button.format(more_itertools.one(people_allowed_to_sign_up))
            Form.submit_programmpunkt_form = wtforms.SubmitField(submit_text)
        else:
            Form.person_to_signup = gefolge_web.event.forms.PersonField(self.event, 'Mensch', person_filter=lambda person: person in people_allowed_to_sign_up, default=editor if editor in people_allowed_to_sign_up else people_allowed_to_sign_up[0])
            submit_text = self.strings.signup_other_button.format('Gewählte Person' if self.strings.signup_other_button.startswith('{') else 'gewählte Person')

        if 'challonge' in self.data:
            Form.challonge_username = wtforms.TextField(jinja2.Markup('<a href="">Challonge</a> username'), [wtforms.validators.Regexp('^[0-9A-Za-z_]*$')], description='optional')

        if self.add_form_details(Form, editor) and submit_text is None:
            submit_text = self.strings.edit_signup_button

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
        if value is None:
            del self.orga
        else:
            self.data['orga'] = value.snowflake

    @orga.deleter
    def orga(self):
        del self.data['orga']

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
        if 'challonge' in self.data:
            if form.challonge.data:
                challonge.participants.create(self.data['challonge'], challonge_username=form.challonge.data, misc='id{}'.format(person_to_signup.snowflake))
            else:
                challonge.participants.create(self.data['challonge'], name=person_to_signup.name, misc='id{}'.format(person_to_signup.snowflake))

        self.process_form_details(form, editor)

    def signup(self, person):
        gefolge_web.util.log('eventProgrammSignup', {
            'event': self.event.event_id,
            'programmpunkt': self.name,
            'person': person.snowflake
        })
        if 'signups' not in self.data:
            self.data['signups'] = []
        if person not in self.signups:
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
            return gefolge_web.util.parse_iso_datetime(start_str, tz=self.timezone)

    @start.setter
    def start(self, value):
        if value is None:
            del self.start
        else:
            self.data['start'] = '{:%Y-%m-%dT%H:%M:%S}'.format(value)

    @start.deleter
    def start(self):
        if 'start' in self.data:
            del self.data['start']

    @property
    def strings(self):
        return Strings.from_json(self.data.get('strings', {}), defaults=self.default_strings)

    @property
    def timezone(self):
        if 'timezone' in self.data:
            return pytz.timezone(self.data['timezone'].value())
        elif self.location is not None:
            return self.location.timezone
        else:
            return pytz.timezone('Europe/Berlin')

    @property
    def url_part(self):
        return self.name

    def user_notes(self, user):
        """These notes are only shown to the given user. Should be wrapped in spoiler tags if sensitive."""
        participants = [
            person
            for person in self.event.signups
            if str(person.snowflake) in self.data.get('targets', {}) and (person == user or (person.is_guest and person.via == user))
        ]
        if len(participants) > 0:
            return jinja2.Markup('\n'.join(
                '<p>{} ist <span class="spoiler">{}</span>.</p>'.format(
                    'Dein Ziel' if participant == user else 'Das Ziel für {}'.format(participant.__html__()),
                    self.event.person(self.data['targets'][str(participant.snowflake)].value()).__html__()
                )
                for participant in participants
            ))

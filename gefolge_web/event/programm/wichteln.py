import pathlib

import jinja2 # PyPI: Jinja2
import wtforms # PyPI: WTForms
import wtforms.validators # PyPI: WTForms

import gefolge_web.event.programm

class Wichteln(gefolge_web.event.programm.Programmpunkt):
    def __new__(cls, event, programmpunkt='wichteln'):
        return object.__new__(cls)

    def __init__(self, event, programmpunkt='wichteln'):
        super().__init__(event, 'wichteln')

    def __repr__(self):
        return 'gefolge_web.event.programm.wichteln.Wichteln({!r})'.format(self.event)

    def add_form_details(self, Form, editor):
        if self.event.location is not None and self.event.location.is_online:
            Form.address = wtforms.TextAreaField('Anschrift', [wtforms.validators.InputRequired()])
            return True
        else:
            return False

    @property
    def default_strings(self):
        return gefolge_web.event.programm.Strings(
            signups_header='Angemeldet',
            signup_form_header='Anmeldung',
            signup_button='Anmelden',
            signup_other_button='{} anmelden',
            edit_signup_button='Änderungen speichern'
        )

    @property
    def name(self):
        return 'Wichteln'

    @property
    def name_editable(self):
        return False

    def process_form_details(self, form, editor):
        if self.event.location is not None and self.event.location.is_online:
            if 'addresses' not in self.data:
                self.data['addresses'] = {}
            self.data['addresses'][editor.snowflake] = form.address.data

    def user_notes(self, user):
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

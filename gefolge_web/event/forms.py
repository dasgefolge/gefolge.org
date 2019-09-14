import datetime
import math
import re

import flask # PyPI: Flask
import flask_wtf # PyPI: Flask-WTF
import jinja2 # PyPI: jinja2
import wtforms # PyPI: WTForms
import wtforms.validators # PyPI: WTForms

import gefolge_web.event.model
import gefolge_web.event.programm
import gefolge_web.forms
import gefolge_web.login
import gefolge_web.util

class PersonField(gefolge_web.forms.MenschField):
    """A form field that validates to a Mensch or Guest. Displayed as a combobox."""

    def __init__(self, event, label, validators=[], *, allow_guests=True, person_filter=lambda person: True, **kwargs):
        self.event = event
        self.allow_guests = allow_guests
        super().__init__(label, validators, person_filter=person_filter, **kwargs)

    @property
    def people(self):
        if self.allow_guests:
            result = self.event.signups
        else:
            result = self.event.menschen
        return list(filter(self.person_filter, result))

    def value_constructor(self, snowflake):
        return self.event.person(snowflake)

def ConfirmSignupForm(event):
    def validate_verwendungszweck(form, field):
        match = re.fullmatch('anzahlung {} ([0-9]+)'.format(event.event_id), field.data.lower())
        if not match:
            raise wtforms.validators.ValidationError('Verwendungszweck ist keine Anzahlung für dieses event.')
        if len(match.group(1)) < 3:
            guest = gefolge_web.event.model.Guest(event, match.group(1))
            if guest not in event.guests:
                raise wtforms.validators.ValidationError('Es ist kein Gast mit dieser Nummer für dieses event eingetragen.')
            if guest in event.signups:
                raise wtforms.validators.ValidationError('Dieser Gast ist bereits für dieses event angemeldet.')
        else:
            mensch = gefolge_web.login.Mensch(match.group(1))
            if not mensch.is_active:
                raise wtforms.validators.ValidationError('Dieser Mensch ist nicht im Gefolge Discord server.')
            if mensch in event.menschen:
                raise wtforms.validators.ValidationError('Dieser Mensch ist bereits für dieses event angemeldet.')

    class Form(flask_wtf.FlaskForm):
        betrag = gefolge_web.forms.EuroField('Betrag', [wtforms.validators.InputRequired(), wtforms.validators.NumberRange(min=event.anzahlung, max=event.anzahlung)])
        verwendungszweck = wtforms.StringField('Verwendungszweck', [validate_verwendungszweck])
        submit_confirm_signup_form = wtforms.SubmitField('Anzahlung bestätigen')

    return Form()

def ProfileForm(event, person):
    class Form(flask_wtf.FlaskForm):
        pass

    person_data = event.attendee_data(person)
    if person_data is None:
        person_data = {'id': person.snowflake}
    else:
        person_data = person_data.value()

    Form.section_nights = gefolge_web.forms.FormSection('Zeitraum')
    if event.start is None:
        Form.section_nights_intro = gefolge_web.forms.FormText('Coming soon™')
    else:
        for i, night in enumerate(event.nights):
            setattr(Form, 'night{}'.format(i), gefolge_web.forms.YesMaybeNoField(
                '{:%d.%m.}–{:%d.%m.}'.format(night, night + datetime.timedelta(days=1)),
                [wtforms.validators.InputRequired()],
                default=person_data.get('nights', {}).get('{:%Y-%m-%d}'.format(night), 'maybe')
            ))

    Form.section_food = gefolge_web.forms.FormSection('Essen')
    if person_data.get('selbstversorger', False):
        Form.section_food_intro = gefolge_web.forms.FormText(jinja2.Markup('Du bist als Selbstversorger eingetragen. Um das zu ändern, wende dich bitte an {}.'.format(gefolge_web.login.Mensch.admin().__html__())))
    else:
        Form.section_food_intro = gefolge_web.forms.FormText('Bitte trage hier Informationen zu deiner Ernährung ein. Diese Daten werden nur der Orga angezeigt.')
        Form.animal_products = gefolge_web.forms.HorizontalButtonGroupField(
            'tierische Produkte',
            [wtforms.validators.InputRequired()],
            choices=[('yes', 'uneingeschränkt', '#808080'), ('vegetarian', 'vegetarisch', '#aac912'), ('vegan', 'vegan', '#55a524')],
            default=person_data.get('food', {}).get('animalProducts', 'yes')
        )
        Form.allergies = wtforms.TextAreaField('Allergien, Unverträglichkeiten', default=person_data.get('food', {}).get('allergies', ''))

    Form.section_programm = gefolge_web.forms.FormSection('Programm')
    if person in event.signups:
        Form.section_programm_intro = gefolge_web.forms.FormText(jinja2.Markup('Auf der <a href="{}">Programmseite</a> kannst du {} für Programmpunkte als interessiert eintragen.'.format(flask.url_for('event_programm', event=event.event_id), 'dich' if person == flask.g.user else person.__html__()))) #TODO add support for deleting programm signups, then adjust this text
    else:
        Form.section_programm_intro = gefolge_web.forms.FormText(jinja2.Markup('Nachdem du dich angemeldet hast, kannst du dich auf der <a href="{}">Programmseite</a> für Programmpunkte als interessiert eintragen.'.format(flask.url_for('event_programm', event=event.event_id))))

    header_generated = False
    if person not in event.signups and person == flask.g.user and event.anzahlung is not None and event.ausfall > event.anzahlung_total + event.anzahlung:
        if not header_generated:
            Form.section_signup = gefolge_web.forms.FormSection('Anmeldung')
            header_generated = True
        if event.ausfall_date is None:
            Form.section_money_intro = gefolge_web.forms.FormText('Wir können erst buchen, wenn die Ausfallgebühr von {} gesichert ist. Dazu fehlen noch {}, also {} Anmeldungen. Damit wir früher buchen können, kannst du freiwillig eine höhere Anzahlung bezahlen. Du bekommst den zusätzlichen Betrag wieder gutgeschrieben, wenn sich genug weitere Menschen angemeldet haben, dass ihre Anzahlungen ihn decken. Er wird nur behalten, um die Ausfallgebühr zu bezahlen, falls das event komplett ausfällt.'.format(event.ausfall, event.ausfall - event.anzahlung_total, math.ceil((event.ausfall - event.anzahlung_total).value / event.anzahlung.value)))
        else:
            Form.section_money_intro = gefolge_web.forms.FormText('Bis zum {:%d.%m.%Y} müssen wir die Ausfallgebühr von {} abdecken. Dazu fehlen noch {}, also {} Anmeldungen. Um sicher zu stellen, dass wir nicht stornieren müssen, kannst du freiwillig eine höhere Anzahlung bezahlen. Du bekommst den zusätzlichen Betrag wieder gutgeschrieben, wenn sich genug weitere Menschen angemeldet haben, dass ihre Anzahlungen ihn decken.'.format(event.ausfall_date, event.ausfall, event.ausfall - event.anzahlung_total, math.ceil((event.ausfall - event.anzahlung_total).value / event.anzahlung.value)))
        Form.anzahlung = gefolge_web.forms.EuroField('Anzahlung', [
            wtforms.validators.InputRequired(),
            wtforms.validators.NumberRange(min=event.anzahlung, message='Die reguläre Anzahlung beträgt %(min)s. Mindestens soviel musst du bezahlen, um dich anzumelden.'),
            wtforms.validators.NumberRange(max=event.ausfall - event.anzahlung_total, message='Wir benötigen nur noch %(max)s, um die Ausfallgebühr abzudecken.'),
            wtforms.validators.NumberRange(max=person.balance, message=jinja2.Markup('Dein aktuelles Guthaben ist {}. Auf <a href="{}">deiner Profilseite</a> steht, wie du Guthaben aufladen kannst.'.format(flask.g.user.balance, flask.url_for('profile', mensch=flask.g.user.snowflake))))
        ], default=event.anzahlung)
    if gefolge_web.util.now(event.timezone) < event.end and person == flask.g.user and event.location is not None and event.location.hausordnung is not None and not person_data.get('hausordnung', False): #TODO track last-changed event and hide if current version has already been accepted
        if not header_generated:
            Form.section_signup = gefolge_web.forms.FormSection('Anmeldung')
            header_generated = True
        Form.hausordnung = wtforms.BooleanField(jinja2.Markup('Ich habe die <a href="{}">Hausordnung</a> zur Kenntnis genommen.'.format(event.location.hausordnung)), [wtforms.validators.DataRequired()])

    Form.submit_profile_form = wtforms.SubmitField('Anmelden' if header_generated or person not in event.signups else 'Speichern')
    return Form()

def ProgrammAddForm(event):
    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Titel', [
            wtforms.validators.InputRequired(),
            wtforms.validators.NoneOf([programmpunkt.name for programmpunkt in event.programm], message='Es gibt bereits einen Programmpunkt mit diesem Titel.'),
            wtforms.validators.Regexp('^[^/]+$', message='Schrägstriche können hier nicht verwendet werden, weil der Titel in der URL der Programmpunktseite steht.')
        ])
        orga = PersonField(event, 'Orga', optional_label='Orga gesucht', allow_guests=False, default=None)
        description = gefolge_web.forms.MarkdownField('Beschreibung')
        submit_programm_add_form = wtforms.SubmitField('Programmpunkt erstellen')

    return Form()

def ProgrammEditForm(programmpunkt):
    def validate_orga(form, field):
        if field.data == programmpunkt.orga:
            return
        if flask.g.user == programmpunkt.event.orga(programmpunkt.orga_role):
            return
        raise wtforms.validators.ValidationError('Bitte wende dich an {}, wenn du die Orga für diesen Programmpunkt abgeben möchtest.'.format(programmpunkt.event.orga(programmpunkt.orga_role)))

    class Form(flask_wtf.FlaskForm):
        orga = PersonField(programmpunkt.event, 'Orga', [validate_orga], optional_label='Orga gesucht', allow_guests=False, default=programmpunkt.orga) #TODO disable (https://getbootstrap.com/docs/3.3/css/#forms-control-disabled) if not allowed to edit
        start = gefolge_web.forms.DateTimeField('Beginn', [wtforms.validators.Optional()], tz=programmpunkt.timezone, default=programmpunkt.start)
        end = gefolge_web.forms.DateTimeField('Ende', [wtforms.validators.Optional()], tz=programmpunkt.timezone, default=programmpunkt.end)
        description = gefolge_web.forms.MarkdownField('Beschreibung', default=programmpunkt.description)
        submit_programm_edit_form = wtforms.SubmitField('Speichern')

    return Form()

class ProgrammDeleteForm(flask_wtf.FlaskForm):
    submit_programm_delete_form = wtforms.SubmitField('Löschen')

def SignupGuestForm(event):
    def validate_guest_name(form, field):
        name = field.data.strip()
        if any(str(guest) == name for guest in event.guests):
            raise wtforms.validators.ValidationError('Ein Gast mit diesem Namen ist bereits angemeldet.')

    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Name', [wtforms.validators.DataRequired(), validate_guest_name])
        submit_signup_guest_form = wtforms.SubmitField('Anmelden' if event.anzahlung == gefolge_web.util.Euro() or event.orga('Abrechnung') == gefolge_web.login.Mensch.admin() else 'Weiter')

    return Form()

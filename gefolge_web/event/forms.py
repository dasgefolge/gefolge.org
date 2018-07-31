import datetime
import flask
import flask_wtf
import re
import wtforms
import wtforms.validators

import gefolge_web.forms
import gefolge_web.login

def ConfirmSignupForm(event):
    def validate_verwendungszweck(form, field):
        match = re.fullmatch('Anzahlung {} ([0-9]+)'.format(event.event_id), field.data)
        if not match:
            raise wtforms.validators.ValidationError('Verwendungszweck ist keine Anzahlung für dieses event.')
        if len(match.group(1)) < 3:
            guest = Guest(event, match.group(1))
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

    return Form()

def ProfileForm(event, person):
    class Form(flask_wtf.FlaskForm):
        pass

    Form.section_nights = gefolge_web.forms.FormSection('Zeitraum')
    person_data = event.attendee_data(person).value()
    for i, night in enumerate(event.nights):
        setattr(Form, 'night{}'.format(i), gefolge_web.forms.YesMaybeNoField(
            '{:%d.%m.}–{:%d.%m.}'.format(night, night + datetime.timedelta(days=1)),
            [wtforms.validators.InputRequired()],
            default=person_data.get('nights', {}).get('{:%Y-%m-%d}'.format(night), 'maybe')
        ))

    Form.section_food = gefolge_web.forms.FormSection('Essen')
    Form.section_food_intro = gefolge_web.forms.FormText('Bitte trage hier Informationen zu deiner Ernährung ein. Diese Daten werden nur der Orga angezeigt.')
    Form.animal_products = gefolge_web.forms.HorizontalButtonGroupField(
        'tierische Produkte',
        [wtforms.validators.InputRequired()],
        choices=[('yes', 'uneingeschränkt', '#808080'), ('vegetarian', 'vegetarisch', '#aac912'), ('vegan', 'vegan', '#55a524')],
        default=person_data.get('food', {}).get('animalProducts', 'yes')
    )
    Form.allergies = wtforms.TextAreaField('Allergien, Unverträglichkeiten', default=person_data.get('food', {}).get('allergies', ''))
    return Form()

def ProgrammAddForm(event):
    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Titel', [
            wtforms.validators.InputRequired(),
            wtforms.validators.NoneOf([programmpunkt.name for programmpunkt in event.programm], message='Es gibt bereits einen Programmpunkt mit diesem Titel.'),
            wtforms.validators.Regexp('^[^/]+$', message='Schrägstriche können hier nicht verwendet werden, weil der Titel in der URL der Programmpunktseite steht.')
        ])
        orga = gefolge_web.forms.EventPersonField(event, 'Orga', allow_guests=False, default=flask.g.user)
        description = wtforms.TextAreaField('Beschreibung')

    return Form()

def ProgrammEditForm(programmpunkt):
    def validate_orga(form, field):
        if field.data == programmpunkt.orga:
            return
        if flask.g.user == programmpunkt.event.orga('Essen' if isinstance(programmpunkt, gefolge_web.event.model.Abendessen) else 'Programm'):
            return
        raise wtforms.validators.ValidationError('Bitte wende dich an {}, wenn du die Orga für diesen Programmpunkt abgeben möchtest.'.format(programmpunkt.event.orga('Essen' if isinstance(programmpunkt, gefolge_web.event.model.Abendessen) else 'Programm')))

    class Form(flask_wtf.FlaskForm):
        orga = gefolge_web.forms.EventPersonField(programmpunkt.event, 'Orga', [validate_orga], allow_guests=False, default=programmpunkt.orga) #TODO disable (https://getbootstrap.com/docs/3.3/css/#forms-control-disabled) if not allowed to edit
        start = wtforms.DateTimeField('Beginn', [wtforms.validators.Optional()], format='%d.%m.%Y %H:%M', default=programmpunkt.start)
        end = wtforms.DateTimeField('Ende', [wtforms.validators.Optional()], format='%d.%m.%Y %H:%M', default=programmpunkt.end)
        description = wtforms.TextAreaField('Beschreibung', default=programmpunkt.description)

    return Form()

class ProgrammDeleteForm(flask_wtf.FlaskForm):
    pass

def SignupGuestForm(event):
    def validate_guest_name(form, field):
        name = field.data.strip()
        if any(str(guest) == name for guest in event.guests):
            raise wtforms.validators.ValidationError('Ein Gast mit diesem Namen ist bereits angemeldet.')

    class Form(flask_wtf.FlaskForm):
        name = wtforms.StringField('Name', [wtforms.validators.DataRequired(), validate_guest_name])

    return Form()

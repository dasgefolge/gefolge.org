import datetime
import math
import re

import flask # PyPI: Flask
import flask_wtf # PyPI: Flask-WTF
import jinja2 # PyPI: Jinja2
import wtforms # PyPI: WTForms
import wtforms.validators # PyPI: WTForms

import gefolge_web.event.model
import gefolge_web.event.programm
import gefolge_web.forms
import gefolge_web.login
import gefolge_web.util

def ConfirmSignupForm(event):
    def validate_verwendungszweck(form, field):
        match = re.fullmatch('anzahlung {} ([0-9]+)'.format(event.event_id), field.data.lower())
        if not match:
            raise wtforms.validators.ValidationError('Verwendungszweck ist keine Anzahlung für dieses event.')
        if len(match.group(1)) < 3:
            guest = gefolge_web.event.model.EventGuest(event, match.group(1))
            if guest not in event.guests:
                raise wtforms.validators.ValidationError('Es ist kein Gast mit dieser Nummer für dieses event eingetragen.')
            if guest in event.signups:
                raise wtforms.validators.ValidationError('Dieser Gast ist bereits für dieses event angemeldet.')
        else:
            person = gefolge_web.login.DiscordPerson(match.group(1))
            if not person.is_active: # Mensch or DiscordGuest
                raise wtforms.validators.ValidationError('Diese Person ist nicht im Gefolge Discord server oder noch nicht als Mensch oder Gast verifiziert.')
            if person in event.signups:
                raise wtforms.validators.ValidationError('Diese Person ist bereits für dieses event angemeldet.')

    class Form(flask_wtf.FlaskForm):
        betrag = gefolge_web.forms.EuroField('Betrag', [
            wtforms.validators.InputRequired(),
            gefolge_web.forms.EuroRange(min=event.anzahlung, max=event.anzahlung, message='Dieser Betrag entspricht nicht der von dir vorgegebenen Anzahlung.'),
        ])
        verwendungszweck = wtforms.StringField('Verwendungszweck', [validate_verwendungszweck])
        submit_confirm_signup_form = wtforms.SubmitField('Anzahlung bestätigen')

    return Form()

def ProfileForm(event, person):
    class Form(flask_wtf.FlaskForm):
        pass

    editor_data = event.attendee_data(flask.g.user)
    person_data = event.attendee_data(person)
    if person_data is None:
        person_data = {'id': person.snowflake}
        new_signup = True
    else:
        person_data = person_data.value()
        new_signup = False

    Form.section_nights = gefolge_web.forms.FormSection('Zeitraum')
    if event.start is None:
        Form.section_nights_intro = gefolge_web.forms.FormText('Coming soon™')
    else:
        for i, night in enumerate(event.nights):
            default = event.night_going(person_data, night)
            if new_signup:
                night_data = None
            else:
                night_data = default
            free_when_maybe = event.free(night) + (1 if night_data == 'yes' else 0) # die Anzahl Plätze, die frei wären, wenn person auf vielleicht gehen würde
            maybes_when_maybe = len(event.night_maybes(night)) + (0 if night_data == 'maybe' else 1) # die Anzahl Personen auf vielleicht wenn person auf vielleicht gehen würde
            maybe_is_waiting = free_when_maybe < 1 or free_when_maybe == 1 and maybes_when_maybe > 1 # es gibt keine freien Plätze mehr, oder genau einen und es ist sonst schon wer auf vielleicht
            yes_available = night_data == 'yes' or not maybe_is_waiting # person ist schon auf ja oder es gibt aktuell keine Warteliste
            setattr(Form, 'night{}'.format(i), gefolge_web.forms.HorizontalButtonGroupField(
                '{:%d.%m.}–{:%d.%m.}'.format(night, night + datetime.timedelta(days=1)),
                [wtforms.validators.InputRequired()],
                ([('yes', 'Ja', '#449d44')] if yes_available else []) + [
                    (('maybe', 'Warteliste', '#269abc') if maybe_is_waiting else ('maybe', 'Vielleicht', '#d58512')),
                    ('no', 'Nein', '#ac2925')
                ],
                default=default
            ))

    if event.rooms:
        Form.section_room = gefolge_web.forms.FormSection('Zimmer')
        if any(room.reserved for room in event.rooms):
            Form.section_room_intro = gefolge_web.forms.FormText(gefolge_web.util.render_template('event.form-notes-zimmer', event=event, person=person))
        Form.room = wtforms.SelectField('Zimmer', choices=[('', 'noch nicht ausgewählt')] + [
            (str(room), room.description)
            for room in event.rooms
            if person in room.people
            or flask.g.user.is_admin
            or editor_data is not None and len(editor_data.get('orga', [])) > 0
            or room.free > 0 and not room.reserved
        ], default='' if event.rooms.get(person) is None else str(event.rooms.get(person)))

    Form.section_travel = gefolge_web.forms.FormSection('An-/Abreise')
    Form.section_travel_intro = gefolge_web.forms.FormText(jinja2.Markup('Um die Infos zu deiner An-/Abreise zu ändern, wende dich bitte an {}.'.format(gefolge_web.login.Mensch.admin().__html__()))) #TODO form

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
    if event.end is None or gefolge_web.util.now(event.timezone) < event.end:
        Form.alkohol = wtforms.BooleanField('Ich beteilige mich am kommunistischen™ Alkohol.', default=person_data.get('alkohol', True))
        Form.alkohol_notice = gefolge_web.forms.FormText('Kann nachträglich korrigiert werden. Die Bowle beim Silvesterbuffet zählt hier nicht.')

    Form.section_programm = gefolge_web.forms.FormSection('Programm')
    if new_signup:
        Form.section_programm_intro = gefolge_web.forms.FormText(jinja2.Markup('Nachdem du dich angemeldet hast, kannst du dich auf der <a href="{}">Programmseite</a> für Programmpunkte als interessiert eintragen.'.format(flask.url_for('event_programm', event=event.event_id))))
    else:
        Form.section_programm_intro = gefolge_web.forms.FormText(jinja2.Markup('Auf der <a href="{}">Programmseite</a> kannst du {} für Programmpunkte als interessiert eintragen.'.format(flask.url_for('event_programm', event=event.event_id), 'dich' if person == flask.g.user else person.__html__()))) #TODO add support for deleting programm signups, then adjust this text

    if (event.end is None or gefolge_web.util.now(event.timezone) < event.end) and event.data.get('covidTestRequired'):
        if event.data['covidTestRequired'].value() == 'geimpftGenesen':
            if person_data.get('covidStatus') != 'geimpftGenesen':
                Form.section_covid = gefolge_web.forms.FormSection('COVID-19')
                Form.covid_immune = wtforms.BooleanField('Ich gelte zum Zeitpunkt meiner Anreise als gegen COVID-19 immunisiert (geimpft und/oder genesen) und bringe einen entsprechenden Nachweis (Digitales COVID-Zertifikat der EU) mit.', [wtforms.validators.DataRequired()])
        else:
            Form.section_covid = gefolge_web.forms.FormSection('COVID-19')
            Form.covid_status = wtforms.RadioField(
                'Status',
                [wtforms.validators.InputRequired()],
                choices=[
                    ('geimpftGenesen', 'Ich gelte zum Zeitpunkt meiner Anreise als gegen COVID-19 immunisiert (geimpft und/oder genesen) und bringe einen entsprechenden Nachweis (Digitales COVID-Zertifikat der EU) mit.'),
                    ('test', 'Ich bin nicht gegen COVID-19 immunisiert. Mir ist bekannt, dass ich bei meiner Ankunft ein tagesaktuelles negatives Testergebnis vorzeigen muss.')
                ],
                default=person_data.get('covidStatus')
            )
            if new_signup:
                Form.covid_status_notice = gefolge_web.forms.FormText('Falls sich dein Status später ändert (z.B. weil du an COVID-19 erkrankst oder einen Impftermin absagen musst), kannst du diese Angabe in deinem Eventprofil jederzeit anpassen.')

    def header_anmeldung():
        if not hasattr(Form, 'section_signup'):
            Form.section_signup = gefolge_web.forms.FormSection('Anmeldung')
    if new_signup and person == flask.g.user and event.anzahlung is not None and event.ausfall > event.anzahlung_total + event.anzahlung:
        header_anmeldung()
        if event.ausfall_date is None:
            Form.anzahlung_notice = gefolge_web.forms.FormText('Wir können erst buchen, wenn die Ausfallgebühr von {} gesichert ist. Dazu fehlen noch {}, also {} Anmeldungen. Damit wir früher buchen können, kannst du freiwillig eine höhere Anzahlung bezahlen. Du bekommst den zusätzlichen Betrag wieder gutgeschrieben, wenn sich genug weitere Menschen angemeldet haben, dass ihre Anzahlungen ihn decken. Er wird nur behalten, um die Ausfallgebühr zu bezahlen, falls das event komplett ausfällt.'.format(event.ausfall, event.ausfall - event.anzahlung_total, math.ceil((event.ausfall - event.anzahlung_total).value / event.anzahlung.value)))
        else:
            Form.anzahlung_notice = gefolge_web.forms.FormText('Bis zum {:%d.%m.%Y} müssen wir die Ausfallgebühr von {} abdecken. Dazu fehlen noch {}, also {} Anmeldungen. Um sicher zu stellen, dass wir nicht stornieren müssen, kannst du freiwillig eine höhere Anzahlung bezahlen. Du bekommst den zusätzlichen Betrag wieder gutgeschrieben, wenn sich genug weitere Menschen angemeldet haben, dass ihre Anzahlungen ihn decken.'.format(event.ausfall_date, event.ausfall, event.ausfall - event.anzahlung_total, math.ceil((event.ausfall - event.anzahlung_total).value / event.anzahlung.value)))
        Form.anzahlung = gefolge_web.forms.EuroField('Anzahlung', [
            wtforms.validators.InputRequired(),
            gefolge_web.forms.EuroRange(min=event.anzahlung, message='Die reguläre Anzahlung beträgt {min}. Mindestens soviel musst du bezahlen, um dich anzumelden.'),
            gefolge_web.forms.EuroRange(max=event.ausfall - event.anzahlung_total, message='Wir benötigen nur noch {max}, um die Ausfallgebühr abzudecken.'),
            gefolge_web.forms.EuroRange(max=person.balance, message=jinja2.Markup(f'Dein aktuelles Guthaben ist {flask.g.user.balance}. Auf <a href="{flask.g.user.profile_url}">deiner Profilseite</a> steht, wie du Guthaben aufladen kannst.'))
        ], default=event.anzahlung)
    if (event.end is None or gefolge_web.util.now(event.timezone) < event.end) and person == flask.g.user and event.location is not None and event.location.hausordnung is not None and not person_data.get('hausordnung', False): #TODO track last-changed event and hide if current version has already been accepted. Also show last-changed date
        header_anmeldung()
        Form.hausordnung = wtforms.BooleanField(jinja2.Markup('Ich habe die <a href="{}">Hausordnung</a> zur Kenntnis genommen.'.format(event.location.hausordnung)), [wtforms.validators.DataRequired()])

    Form.submit_profile_form = wtforms.SubmitField('Anmelden' if hasattr(Form, 'section_signup') or new_signup else 'Speichern')
    return Form()

def ProgrammForm(event, programmpunkt):
    class Form(flask_wtf.FlaskForm):
        pass

    if programmpunkt is None:
        Form.url_part = gefolge_web.forms.AnnotatedStringField('URL', [
            wtforms.validators.InputRequired(),
            wtforms.validators.Regexp('^[0-9a-z-]+$', message='Darf nur aus Kleinbuchstaben, Zahlen und „-“ bestehen.'),
            wtforms.validators.NoneOf([programmpunkt.url_part for programmpunkt in event.programm], message='Es gibt bereits einen Programmpunkt mit diesem Titel.'),
        ], prefix=f'https://gefolge.org/event/{event.event_id}/programm/')
    if programmpunkt is None or programmpunkt.name_editable:
        Form.display_name = wtforms.StringField('Titel', [
            wtforms.validators.InputRequired(),
            wtforms.validators.NoneOf([
                other.name
                for other in event.programm
                if programmpunkt is None or other != programmpunkt
            ], message='Es gibt bereits einen Programmpunkt mit diesem Titel.')
        ], default='' if programmpunkt is None else programmpunkt.name)
    Form.subtitle = wtforms.StringField('Untertitel', [wtforms.validators.Length(max=40)], default='' if programmpunkt is None else programmpunkt.subtitle)
    Form.subtitle_notice = gefolge_web.forms.FormText('Wird auf dem info-beamer und im Zeitplan angezeigt.')
    if programmpunkt is None or flask.g.user.is_admin or flask.g.user == event.orga(programmpunkt.orga_role):
        Form.orga = gefolge_web.forms.PersonField('Orga', gefolge_web.login.Mensch if event.location is not None and event.location.is_online else filter(lambda person: person.is_mensch, event.signups), optional_label='Orga gesucht', default=None if programmpunkt is None else programmpunkt.orga)
    elif flask.g.user == programmpunkt.orga:
        if event.location is not None and event.location.is_online:
            programm_orga = gefolge_web.login.Mensch.admin()
        else:
            programm_orga = event.orga(programmpunkt.orga_role)
        Form.orga_notice = gefolge_web.forms.FormText(
            jinja2.Markup('Bitte wende dich an {}, wenn du die Orga für diesen Programmpunkt abgeben möchtest.'.format(programm_orga.__html__())),
            display_label='Orga'
        )
    Form.start = gefolge_web.forms.DateTimeField('Beginn', [wtforms.validators.Optional()], tz=event.timezone if programmpunkt is None else programmpunkt.timezone, default=None if programmpunkt is None else programmpunkt.start)
    Form.end = gefolge_web.forms.DateTimeField('Ende', [wtforms.validators.Optional(), gefolge_web.forms.OtherInputRequired('start', 'Bitte entweder auch den Beginn eintragen oder den Endzeitpunkt erstmal weglassen.')], tz=event.timezone if programmpunkt is None else programmpunkt.timezone, default=None if programmpunkt is None else programmpunkt.end)
    if programmpunkt is None or programmpunkt.description_editable:
        Form.description = flask.g.wiki.MarkdownField('Beschreibung', default='' if programmpunkt is None else programmpunkt.description)
    if flask.g.user.is_admin or flask.g.user == event.orga('Programm'):
        Form.css_class = gefolge_web.forms.HorizontalButtonGroupField(
            'Farbe',
            [wtforms.validators.InputRequired()],
            choices=[
                ('programm-meta', 'Kernprogramm, meta', '#a61c00', '#cc4125'),
                ('programm-essen', 'Essen', '#45818e', '#76a5af'),
                ('programm-trip', 'Ausflug', '#3c78d8', '#6d9eeb'),
                ('programm-reqsignup', 'Voranmeldung nötig', '#e69138', '#f6b26b'),
                ('programm-other', 'Sonstiges', '#f1c232', '#ffd966')
            ],
            default='programm-other' if programmpunkt is None else programmpunkt.css_class
        )
    Form.submit_programm_form = wtforms.SubmitField('Programmpunkt erstellen' if programmpunkt is None else 'Speichern')

    return Form()

class ProgrammDeleteForm(flask_wtf.FlaskForm):
    submit_programm_delete_form = wtforms.SubmitField('Löschen')

def SignupGuestForm(event):
    def validate_guest_name(form, field):
        name = field.data.strip()
        if form.person.data is None:
            if len(name) == 0:
                raise wtforms.validators.ValidationError('Bitte entweder hier einen Namen angeben oder oben einen Discord-Account auswählen.')
            if any(str(guest) == name for guest in event.guests):
                raise wtforms.validators.ValidationError('Ein Gast mit diesem Namen ist bereits angemeldet.')
        else:
            if len(name) > 0:
                raise wtforms.validators.ValidationError('Dieses Feld ist dazu da, Leute ohne Discord-Account anzumelden. Für Discord-Gäste sollte es leer gelassen werden. Seinen Anzeigenamen kann ein Discord-Gast selbst ändern, entweder in Discord im Servermenü oder in den Einstellungen auf gefolge.org.')

    class Form(flask_wtf.FlaskForm):
        #TODO use radio group with fields (like in Travel section of ProfileForm)
        person = gefolge_web.forms.PersonField('Discord-Account', (guest for guest in gefolge_web.login.DiscordGuest if guest not in event.guests), optional_label='(nicht im Gefolge-Discord)')
        name = wtforms.StringField('Name', [validate_guest_name])
        submit_signup_guest_form = wtforms.SubmitField('Anmelden' if event.anzahlung == gefolge_web.util.Euro() or event.orga('Abrechnung').is_treasurer else 'Weiter')

    return Form()

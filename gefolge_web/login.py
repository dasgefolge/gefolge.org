import functools
import random
import string
import subprocess
import urllib.parse

import flask # PyPI: Flask
import flask_dance.contrib.discord # PyPI: Flask-Dance
import flask_dance.contrib.twitch # PyPI: Flask-Dance
import flask_wtf # PyPI: Flask-WTF
import jinja2 # PyPI: Jinja2
import pytz # PyPI: pytz
import requests # PyPI: requests
import wtforms # PyPI: WTForms
import wtforms.validators # PyPI: WTForms

import lazyjson # https://github.com/fenhl/lazyjson
import peter # https://github.com/dasgefolge/peter-discord

import gefolge_web.db
import gefolge_web.forms
import gefolge_web.person
import gefolge_web.util

GAST = 784929665478557737 # role ID
MENSCH = 386753710434287626 # role ID

class User(gefolge_web.person.Person):
    @property
    def enable_dejavu(self):
        return self.userdata.get('enableDejavu', True)

    @property
    def event_timezone_override(self):
        return self.userdata.get('eventTimezoneOverride', True)

    @property
    def timezone(self):
        if 'timezone' in self.userdata:
            return pytz.timezone(self.userdata['timezone'].value())

    @property
    def userdata(self):
        return lazyjson.PythonFile({})

class DiscordPersonMeta(type):
    def __iter__(self):
        # iterating over the DiscordPerson class yields everyone in the guild
        return (
            DiscordPerson(snowflake)
            for snowflake in subprocess.run(['/home/fenhl/bin/gefolge-web-back', 'profiles', 'list'], stdout=subprocess.PIPE, encoding='utf-8', check=True).stdout.splitlines()
        )

def profile_data_for_snowflake(snowflake):
    return gefolge_web.util.cached_json(gefolge_web.db.PgFile('profiles', snowflake)).value()

class DiscordPerson(User, metaclass=DiscordPersonMeta):
    def __new__(cls, snowflake):
        roles = profile_data_for_snowflake(snowflake).get('roles', [])
        if str(MENSCH) in roles:
            return Mensch(snowflake)
        elif str(GAST) in roles:
            return DiscordGuest(snowflake)
        else:
            return super().__new__(cls)

    def __init__(self, snowflake):
        self.snowflake = int(snowflake)

    def __eq__(self, other):
        return isinstance(other, DiscordPerson) and self.snowflake == other.snowflake

    def __hash__(self):
        return hash(self.snowflake)

    def __html__(self):
        return jinja2.Markup(f'<a title="{self}" href="{self.profile_url}">@{jinja2.escape(self.name)}</a>')

    def __repr__(self):
        return f'gefolge_web.login.DiscordPerson({self.snowflake!r})'

    def __str__(self):
        try:
            if self.discrim is None:
                return f'@{self.username}'
            else:
                return f'{self.username}#{self.discrim}'
        except FileNotFoundError:
            return str(self.snowflake)

    @classmethod
    def by_tag(cls, username, discrim):
        # used in flask_wiki
        for person in cls:
            if username == person.username and (person.discrim is None and (discrim is None or discrim == 0) or f'{discrim:>04}' == person.discrim):
                return person

    def api_key_inner(self, *, create, exclude=None):
        if exclude is None:
            exclude = set()
        if 'apiKey' not in self.userdata:
            if create:
                new_key = None
                while new_key is None or gefolge_web.person.Person.by_api_key(new_key, exclude=exclude | {self}) is not None: # to avoid duplicates
                    new_key = ''.join(random.choice(string.ascii_lowercase + string.digits) for i in range(25))
                self.userdata['apiKey'] = new_key
            else:
                return None
        return self.userdata['apiKey'].value()

    @gefolge_web.person.Person.api_key.deleter
    def api_key(self):
        if 'apiKey' in self.userdata:
            del self.userdata['apiKey']

    @property
    def discrim(self):
        """Returns the Discord discriminator, if any, as a string with leading zeroes."""
        return self.profile_data['discriminator']

    @property
    def is_authenticated(self):
        return True

    @property
    def is_wurstmineberg_member(self):
        try:
            response = requests.get('https://wurstmineberg.de/api/v3/people.json')
            response.raise_for_status()
            return str(self.snowflake) in response.json()['people']
        except requests.RequestException:
            return False

    @property
    def long_name(self):
        if self.nickname is None:
            return str(self)
        else:
            return '{} ({})'.format(self.nickname, self)

    @property
    def name(self): # used in flask_wiki
        if self.nickname is None:
            return self.username
        else:
            return self.nickname

    @property
    def nickname(self):
        return self.profile_data.get('nick')

    @nickname.setter
    def nickname(self, value):
        peter.set_display_name(self, value or '')

    @nickname.deleter
    def nickname(self):
        peter.set_display_name(self, '')

    @property
    def profile_data(self):
        return profile_data_for_snowflake(self.snowflake)

    @property
    def profile_url(self):
        return flask.url_for('profile', person=str(self.snowflake))

    @property
    def url_part(self):
        return str(self.snowflake)

    @property
    def userdata(self):
        return gefolge_web.util.cached_json(gefolge_web.db.PgFile('user-data', self.snowflake, init={}))

    @property
    def username(self):
        return self.profile_data['username']

class MenschMeta(DiscordPersonMeta):
    def __iter__(self):
        # iterating over the Mensch class yields everyone with the role
        return (
            person
            for person in DiscordPerson
            if person.is_mensch
        )

class Mensch(DiscordPerson, metaclass=MenschMeta):
    def __new__(cls, snowflake):
        return object.__new__(cls)

    @classmethod
    def admin(cls):
        return cls(gefolge_web.util.cached_json(lazyjson.File(gefolge_web.util.CONFIG_PATH))['web']['admin'].value())

    @classmethod
    def treasurer(cls):
        snowflake = gefolge_web.util.cached_json(lazyjson.File(gefolge_web.util.CONFIG_PATH))['web'].get('treasurer')
        if snowflake is not None:
            return cls(snowflake)

    def __repr__(self):
        return f'gefolge_web.login.Mensch({self.snowflake!r})'

    def add_transaction(self, transaction):
        if 'transactions' not in self.userdata:
            self.userdata['transactions'] = []
        self.userdata['transactions'].append(transaction.json_data)

    @property
    def balance(self):
        import gefolge_web.event.model

        if self.is_treasurer:
            return sum((
                # Anzahlungen für noch nicht abgerechnete events
                -event.anzahlung_total
                for event in gefolge_web.event.model.Event
                if event.anzahlung is not None and not any(
                    transaction.json_data['type'] == 'eventAbrechnung' and transaction.json_data['event'] == event.event_id
                    for mensch in event.menschen
                    for transaction in mensch.transactions
                )
            ), gefolge_web.util.Euro()) + sum((
                # Guthaben aller anderen Menschen (ohne Schulden)
                -mensch.balance
                for mensch in Mensch
                if not mensch.is_treasurer and mensch.balance > gefolge_web.util.Euro()
            ), gefolge_web.util.Euro())
        else:
            return sum((transaction.amount for transaction in self.transactions), gefolge_web.util.Euro())

    @property
    def is_active(self):
        return str(MENSCH) in self.profile_data.get('roles')

    @property
    def transactions(self):
        return [
            gefolge_web.util.Transaction(transaction_data)
            for transaction_data in self.userdata.get('transactions', [])
        ]

    @property
    def twitch(self):
        return self.userdata.get('twitch')

    @twitch.setter
    def twitch(self, value):
        self.userdata['twitch'] = value

class DiscordGuestMeta(DiscordPersonMeta):
    def __iter__(self):
        # iterating over the DiscordGuest class yields all Discord guests
        return (
            person
            for person in DiscordPerson
            if person.is_guest
        )

class DiscordGuest(DiscordPerson, gefolge_web.person.Guest, metaclass=DiscordGuestMeta):
    def __new__(cls, snowflake):
        return object.__new__(cls)

    def __repr__(self):
        return 'gefolge_web.login.DiscordGuest({!r})'.format(self.snowflake)

    @property
    def is_active(self):
        return str(GAST) in self.profile_data.get('roles')

class AnonymousUser(User):
    def __init__(self):
        pass

    def __html__(self):
        return jinja2.Markup('<i>anonym</i>')

    def __str__(self):
        return 'anonym'

def ProfileForm(mensch):
    def no_admin_nick_change(form, field):
        # Peter does not have permission to change the nickname of the server owner.
        if mensch.is_admin and field.data != mensch.nickname:
            raise wtforms.validators.ValidationError('Der Name eines Administrators kann nur in Discord geändert werden.')

    class Form(flask_wtf.FlaskForm):
        nickname = gefolge_web.forms.AnnotatedStringField('Name', [no_admin_nick_change, wtforms.validators.Optional(), wtforms.validators.Regexp('^([^@#:]{2,32})$')], prefix='@', description={'placeholder': mensch.username}, default=mensch.nickname)
        nickname_notice = gefolge_web.forms.FormText('Dieser Name wird u.A. im Gefolge-Discord, auf dieser website und auf events verwendet. Du kannst ihn auch im Gefolge-Discord über das Servermenü ändern. Wenn du das Feld leer lässt, wird dein Discord username verwendet.')
        timezone = gefolge_web.forms.TimezoneField(featured=['Europe/Berlin', 'Etc/UTC'], default=mensch.timezone)
        timezone_notice = gefolge_web.forms.FormText('„Automatisch“ heißt, dass deine aktuelle Systemzeit verwendet wird, um deine Zeitzone zu erraten. Das kann fehlerhaft sein, wenn es mehrere verschiedene Zeitzonen gibt, die aktuell zu deiner Systemzeit passen aber verschiedene Regeln zur Sommerzeit haben. Wenn du JavaScript deaktivierst, werden alle Uhrzeiten in ihrer ursprünglichen Zeitzone angezeigt und unterpunktet. Du kannst immer mit dem Mauszeiger auf eine Uhrzeit zeigen, um ihre Zeitzone zu sehen.') #TODO update description (rewrite uses more accurate browser APIs)
        event_timezone_override = wtforms.BooleanField('Auf Eventseiten immer die vor Ort gültige Zeitzone verwenden (außer bei online events)', default=mensch.event_timezone_override)
        enable_dejavu = wtforms.BooleanField('DejaVu-Schriftart verwenden (wenn Text vertikal unregelmäßig aussieht, deaktivieren)', default=mensch.enable_dejavu) #TODO remove (no longer used in riir.css)
        submit_profile_form = wtforms.SubmitField('Speichern')

    return Form()

def TransferMoneyForm(mensch):
    class Form(flask_wtf.FlaskForm):
        recipient = gefolge_web.forms.PersonField('An', (iter_mensch for iter_mensch in Mensch if iter_mensch != mensch))
        amount = gefolge_web.forms.EuroField('Betrag', [
            wtforms.validators.InputRequired(),
            gefolge_web.forms.EuroRange(min=gefolge_web.util.Euro('0.01'), message='Nur positive Beträge erlaubt.'),
        ] + ([] if flask.g.user.is_admin or flask.g.user.is_treasurer else [
            gefolge_web.forms.EuroRange(max=mensch.balance, message=jinja2.Markup('Du kannst maximal dein aktuelles Guthaben übertragen.'))
        ]))
        comment = wtforms.TextAreaField('Kommentar (optional)')
        submit_transfer_money_form = wtforms.SubmitField('Übertragen')

    return Form()

def WurstminebergTransferMoneyForm(mensch):
    class Form(flask_wtf.FlaskForm):
        amount = gefolge_web.forms.EuroField('Betrag', [
            wtforms.validators.InputRequired(),
            gefolge_web.forms.EuroRange(min=gefolge_web.util.Euro('0.01'), message='Nur positive Beträge erlaubt.'),
        ] + ([] if flask.g.user.is_admin or flask.g.user.is_treasurer else [
            gefolge_web.forms.EuroRange(max=mensch.balance, message=jinja2.Markup('Du kannst maximal dein aktuelles Guthaben übertragen.'))
        ]))
        submit_wurstmineberg_transfer_money_form = wtforms.SubmitField('Übertragen')

    return Form()

def is_safe_url(target):
    ref_url = urllib.parse.urlparse(flask.request.host_url)
    test_url = urllib.parse.urlparse(urllib.parse.urljoin(flask.request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def mensch_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not flask.g.user.is_authenticated:
            return flask.redirect('/login/discord') #TODO redirect_to parameter
        if not flask.g.user.is_mensch:
            return flask.make_response(('Sie haben keinen Zugriff auf diesen Inhalt, weil Sie nicht im Gefolge Discord server sind oder nicht als Gefolgemensch verifiziert sind.', 403, [])) #TODO template
        return f(*args, **kwargs)

    return wrapper

def setup(index, app):
    if 'clientSecret' not in app.config.get('peter', {}):
        return #TODO mount error messages at /login and /auth
    app.config['SECRET_KEY'] = app.config['peter']['clientSecret']
    app.config['USE_SESSION_FOR_NEXT'] = True

    app.register_blueprint(flask_dance.contrib.twitch.make_twitch_blueprint(
        client_id=app.config['twitch']['clientID'],
        client_secret=app.config['twitch']['clientSecret'],
        redirect_to='twitch_auth_callback'
    ), url_prefix='/login')

    @app.before_request
    def global_users():
        flask.g.admin = Mensch.admin()
        flask.g.treasurer = Mensch.treasurer()
        if 'x-gefolge-authorized-discord-id' in flask.request.headers:
            flask.g.user = DiscordPerson(flask.request.headers['x-gefolge-authorized-discord-id'])
        else:
            flask.g.user = gefolge_web.login.AnonymousUser()

    def auth_callback():
        #TODO similar error handling in Rust
        if not flask_dance.contrib.discord.discord.authorized:
            flask.flash('Discord-Login fehlgeschlagen.', 'error')
            return flask.redirect(flask.url_for('index'))
        response = flask_dance.contrib.discord.discord.get('/api/v6/users/@me')
        if not response.ok:
            return flask.make_response(('Discord meldet Fehler {} auf {}: {}'.format(response.status_code, jinja2.escape(response.url), jinja2.escape(response.text)), response.status_code, []))
        person = DiscordPerson(response.json()['id'])
        if not person.is_active:
            try:
                person.profile_data
            except FileNotFoundError:
                flask.flash('Sie haben sich erfolgreich mit Discord angemeldet, sind aber nicht im Gefolge Discord server.', 'error')
                return flask.redirect(flask.url_for('index'))
            else:
                flask.flash('Dein Account wurde noch nicht freigeschaltet. Stelle dich doch bitte einmal kurz im #general vor und warte, bis ein admin dich bestätigt.', 'error')
                return flask.redirect(flask.url_for('index'))
        flask.flash(jinja2.Markup('Hallo {}.'.format(person.__html__())))
        next_url = flask.session.get('next')
        if next_url is None:
            return flask.redirect(flask.url_for('index'))
        elif is_safe_url(next_url):
            return flask.redirect(next_url)
        else:
            return flask.abort(400)

    @app.route('/auth/twitch')
    def twitch_auth_callback():
        if not flask.g.user.is_active:
            return flask.make_response(('Bitte melden Sie sich zuerst mit Discord an, bevor Sie sich mit Twitch anmelden.', 403, [])) #TODO template
        if not flask.g.user.is_mensch:
            return flask.make_response(('Die Twitch-Integration ist nur für verifizierte Gefolgemenschen verfügbar.', 403, [])) #TODO template
        if not flask_dance.contrib.twitch.twitch.authorized:
            flask.flash('Twitch-Login fehlgeschlagen.', 'error')
            return flask.redirect(flask.url_for('index'))
        response = flask_dance.contrib.twitch.twitch.get('users')
        if not response.ok:
            return flask.make_response(('Twitch meldet Fehler {} auf {}: {}'.format(response.status_code, jinja2.escape(response.url), jinja2.escape(response.text)), response.status_code, []))
        flask.g.user.twitch = response.json()['data'][0]
        flask.flash('Twitch-Konto erfolgreich verknüpft.')
        next_url = flask.session.get('next')
        if next_url is None:
            return flask.redirect(flask.url_for('index'))
        elif is_safe_url(next_url):
            return flask.redirect(next_url)
        else:
            return flask.abort(400)

    @index.child('mensch', 'Menschen und Gäste', decorators=[mensch_required])
    @gefolge_web.util.template('menschen-index')
    def menschen():
        pass

    @menschen.children(DiscordPerson, methods=['GET', 'POST'])
    @gefolge_web.util.template()
    def profile(person):
        import gefolge_web.event.model

        if not person.is_active:
            return gefolge_web.util.render_template('profile-404', mensch=person), 404
        if person.is_mensch and (flask.g.user.is_admin or flask.g.user.is_treasurer or flask.g.user == person):
            transfer_money_form = TransferMoneyForm(person)
            if transfer_money_form.submit_transfer_money_form.data and transfer_money_form.validate():
                recipient = transfer_money_form.recipient.data
                person.add_transaction(gefolge_web.util.Transaction.transfer(recipient, -transfer_money_form.amount.data, transfer_money_form.comment.data))
                recipient.add_transaction(gefolge_web.util.Transaction.transfer(person, transfer_money_form.amount.data, transfer_money_form.comment.data))
                if flask.g.user != person:
                    peter.msg(person, '<@{}> ({}) hat {} von deinem Guthaben an <@{}> ({}) übertragen. {}: <https://gefolge.org/me>'.format(flask.g.user.snowflake, flask.g.user, transfer_money_form.amount.data, recipient.snowflake, recipient, 'Kommentar und weitere Infos' if transfer_money_form.comment.data else 'Weitere Infos'))
                if flask.g.user != recipient:
                    peter.msg(recipient, '<@{}> ({}) hat {} an dich übertragen. {}: <https://gefolge.org/me>'.format(person.snowflake, person, transfer_money_form.amount.data, 'Kommentar und weitere Infos' if transfer_money_form.comment.data else 'Weitere Infos'))
                return flask.redirect(flask.g.view_node.url)
            wurstmineberg_transfer_money_form = WurstminebergTransferMoneyForm(person)
            if wurstmineberg_transfer_money_form.submit_wurstmineberg_transfer_money_form.data and wurstmineberg_transfer_money_form.validate():
                transaction = gefolge_web.util.Transaction.wurstmineberg(wurstmineberg_transfer_money_form.amount.data)
                person.add_transaction(transaction)
                gefolge_web.util.cached_json(lazyjson.File('/opt/wurstmineberg/money.json'))['transactions'].append({
                    'amount': wurstmineberg_transfer_money_form.amount.data.value,
                    'currency': 'EUR',
                    'time': '{:%Y-%m-%dT%H:%M:%SZ}'.format(transaction.time.astimezone(pytz.utc)),
                    'type': 'gefolge'
                })
        else:
            transfer_money_form = None
            wurstmineberg_transfer_money_form = None
        return {
            'events': [event for event in gefolge_web.event.model.Event if person in event.signups],
            'person': person,
            'transfer_money_form': transfer_money_form,
            'wurstmineberg_transfer_money_form': wurstmineberg_transfer_money_form
        }

    @profile.catch_init(ValueError)
    def profile_catch_init(exc, value):
        return gefolge_web.util.render_template('profile-404', snowflake=value), 404

    @profile.child('edit', 'bearbeiten', methods=['GET', 'POST'])
    @gefolge_web.util.template('profile-edit')
    def profile_edit(person):
        if flask.g.user != person and not flask.g.user.is_admin:
            flask.flash('Du bist nicht berechtigt, dieses Profil zu bearbeiten.', 'error')
            return flask.redirect(flask.g.view_node.parent.url)
        profile_form = ProfileForm(person)
        if profile_form.submit_profile_form.data and profile_form.validate():
            gefolge_web.util.log('profileEdit', {
                'mensch': person.snowflake,
                'nickname': profile_form.nickname.data,
                'timezone': None if profile_form.timezone.data is None else str(profile_form.timezone.data),
                'enableDejavu': profile_form.enable_dejavu.data,
                'eventTimezoneOverride': profile_form.event_timezone_override.data
            })
            if not person.is_admin:
                person.nickname = profile_form.nickname.data
            if profile_form.timezone.data is None:
                if 'timezone' in person.userdata:
                    del person.userdata['timezone']
            else:
                person.userdata['timezone'] = str(profile_form.timezone.data)
            person.userdata['enableDejavu'] = profile_form.enable_dejavu.data
            person.userdata['eventTimezoneOverride'] = profile_form.event_timezone_override.data
            return flask.redirect(flask.g.view_node.parent.url)
        else:
            return {
                'person': person,
                'profile_form': profile_form
            }

    @profile.child('reset-key')
    def reset_api_key(person):
        if flask.g.user.is_admin or flask.g.user == person:
            del person.api_key
            return flask.redirect(flask.url_for('api_index'))
        else:
            flask.flash(jinja2.Markup('Du bist nicht berechtigt, den API key für {} neu zu generieren.'.format(person.__html__())), 'error')
            return flask.redirect(flask.url_for('api_index'))

    @index.redirect('me', decorators=[mensch_required]) #TODO profile pages for Discord guests?
    def me():
        return menschen, flask.g.user

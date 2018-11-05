import flask
import flask_dance.contrib.discord
import flask_login
import flask_wtf
import functools
import html
import jinja2
import json
import lazyjson
import pathlib
import peter
import random
import string
import urllib.parse
import wtforms
import wtforms.validators

import gefolge_web.forms
import gefolge_web.util

MENSCHEN = 386753710434287626 # role ID
PROFILES_ROOT = gefolge_web.util.BASE_PATH / 'profiles'
USERDATA_ROOT = gefolge_web.util.BASE_PATH / 'userdata'

class MenschMeta(type):
    def __iter__(self):
        # iterating over the Mensch class yields everyone in the guild
        return (
            Mensch(profile_path.stem)
            for profile_path in sorted(PROFILES_ROOT.iterdir(), key=lambda path: int(path.stem))
            if Mensch(profile_path.stem).is_active
        )

class Mensch(flask_login.UserMixin, metaclass=MenschMeta):
    def __init__(self, snowflake):
        self.snowflake = int(snowflake)

    @classmethod
    def admin(cls):
        with gefolge_web.util.CONFIG_PATH.open() as config_f:
            return cls(json.load(config_f)['web']['admin'])

    @classmethod
    def by_api_key(cls, key=None, *, exclude=None):
        if exclude is None:
            exclude = set()
        if key is None:
            auth = flask.request.authorization
            if auth and auth.username.strip().lower() == 'api':
                key = auth.password.strip().lower()
        for mensch in cls:
            if mensch in exclude:
                continue
            if key == mensch.api_key_inner(exclude=exclude):
                return mensch

    @classmethod
    def get(cls, user_id):
        try:
            return cls(user_id)
        except ValueError:
            return None

    def __eq__(self, other):
        return hasattr(other, 'snowflake') and self.snowflake == other.snowflake

    def __hash__(self):
        return hash(self.snowflake)

    def __html__(self):
        return jinja2.Markup('<a title="{}" href="{}">@{}</a>'.format(self, flask.url_for('profile', mensch=str(self.snowflake)), jinja2.escape(self.name)))

    def __repr__(self):
        return 'gefolge_web.login.Mensch({!r})'.format(self.snowflake)

    def __str__(self):
        try:
            return '{}#{}'.format(self.profile_data['username'], self.discrim)
        except FileNotFoundError:
            return str(self.snowflake)

    def add_transaction(self, transaction):
        if 'transactions' not in self.userdata:
            self.userdata['transactions'] = []
        self.userdata['transactions'].append(transaction.json_data)

    @property
    def api_key(self):
        return self.api_key_inner()

    def api_key_inner(self, *, exclude=None):
        if exclude is None:
            exclude = set()
        if 'apiKey' not in self.userdata:
            new_key = None
            while new_key is None or self.__class__.by_api_key(new_key, exclude=exclude | {self}) is not None: # to avoid duplicates
                new_key = ''.join(random.choice(string.ascii_lowercase + string.digits) for i in range(25))
            self.userdata['apiKey'] = new_key
        return self.userdata['apiKey'].value()

    @api_key.deleter
    def api_key(self):
        if 'apiKey' in self.userdata:
            del self.userdata['apiKey']

    @property
    def balance(self):
        import gefolge_web.event.model

        if self == self.__class__.admin():
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
                for mensch in self.__class__
                if not mensch.is_admin and mensch.balance > gefolge_web.util.Euro()
            ), gefolge_web.util.Euro())
        else:
            return sum((transaction.amount for transaction in self.transactions), gefolge_web.util.Euro())

    @property
    def data(self):
        return lazyjson.File(self.profile_path)

    @property
    def discrim(self):
        """Returns the username discriminator as a string with leading zeroes."""
        return '{:04}'.format(self.profile_data['discriminator'])

    def get_id(self): # required by flask_login
        return str(self.snowflake)

    @property
    def is_active(self):
        return self.profile_path.exists() and MENSCHEN in self.profile_data.get('roles')

    @property
    def is_admin(self):
        return self == self.__class__.admin()

    @property
    def is_guest(self):
        return False

    @property
    def long_name(self):
        if self.profile_data.get('nick') is None:
            return str(self)
        else:
            return '{} ({})'.format(self.profile_data['nick'], self)

    @property
    def name(self):
        if self.profile_data.get('nick') is None:
            return self.profile_data['username']
        else:
            return self.profile_data['nick']

    @property
    def profile_data(self):
        return lazyjson.File(self.profile_path).value()

    @property
    def profile_path(self):
        return PROFILES_ROOT / '{}.json'.format(self.snowflake)

    @property
    def transactions(self):
        return [
            gefolge_web.util.Transaction(transaction_data)
            for transaction_data in self.userdata.get('transactions', [])
        ]

    @property
    def url_part(self):
        return str(self.snowflake)

    @property
    def userdata(self):
        return lazyjson.File(self.userdata_path, init={})

    @property
    def userdata_path(self):
        return USERDATA_ROOT / '{}.json'.format(self.snowflake)

def TransferMoneyForm(mensch):
    class Form(flask_wtf.FlaskForm):
        recipient = gefolge_web.forms.MenschField('An', person_filter=lambda person: person != mensch)
        amount = gefolge_web.forms.EuroField('Betrag', [
            wtforms.validators.InputRequired(),
            wtforms.validators.NumberRange(min=gefolge_web.util.Euro('0.01'), message='Nur positive Beträge erlaubt.'),
        ] + ([] if flask.g.user.is_admin else [
            wtforms.validators.NumberRange(max=mensch.balance, message=jinja2.Markup('Du kannst maximal dein aktuelles Guthaben übertragen.'))
        ]))
        comment = wtforms.TextAreaField('Kommentar (optional)')
        submit_transfer_money_form = wtforms.SubmitField('Übertragen')

    return Form()

def is_safe_url(target):
    ref_url = urllib.parse.urlparse(flask.request.host_url)
    test_url = urllib.parse.urlparse(urllib.parse.urljoin(flask.request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def member_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not flask.g.user.is_active:
            return flask.make_response(('Sie haben keinen Zugriff auf diesen Inhalt, weil Sie nicht im Gefolge Discord server sind.', 403, [])) #TODO template
        return f(*args, **kwargs)

    return flask_login.login_required(wrapper)

def setup(index, app):
    if 'clientID' not in app.config.get('peter', {}) or 'clientSecret' not in app.config.get('peter', {}):
        return #TODO mount error messages at /login and /auth
    app.config['SECRET_KEY'] = app.config['peter']['clientSecret']
    app.config['USE_SESSION_FOR_NEXT'] = True

    app.register_blueprint(flask_dance.contrib.discord.make_discord_blueprint(
        client_id=app.config['peter']['clientID'],
        client_secret=app.config['peter']['clientSecret'],
        scope='identify',
        redirect_to='auth_callback'
    ), url_prefix='/login')

    login_manager = flask_login.LoginManager()
    login_manager.login_view = 'discord.login'
    login_manager.login_message = None # Because discord.login does not show flashes, any login message would be shown after a successful login. This would be confusing.

    @login_manager.user_loader
    def load_user(user_id):
        return Mensch.get(user_id)

    login_manager.init_app(app)

    @app.before_request
    def global_users():
        flask.g.admin = Mensch(app.config['web']['admin'])
        if flask_login.current_user == flask.g.admin and 'viewAs' in app.config['web']:
            flask.g.view_as = True
            flask.g.user = Mensch(app.config['web']['viewAs'])
        else:
            flask.g.view_as = False
            flask.g.user = flask_login.current_user

    @app.route('/auth')
    def auth_callback():
        if not flask_dance.contrib.discord.discord.authorized:
            flask.flash('Login fehlgeschlagen.', 'error')
            return flask.redirect(flask.url_for('index'))
        response = flask_dance.contrib.discord.discord.get('/api/v6/users/@me')
        if not response.ok:
            return flask.make_response(('Discord returned error {} at {}: {}'.format(response.status_code, html.escape(response.url), html.escape(response.text)), response.status_code, []))
        mensch = Mensch(response.json()['id'])
        if not mensch.is_active:
            try:
                mensch.profile_data
            except FileNotFoundError:
                flask.flash('Sie haben sich erfolgreich mit Discord angemeldet, sind aber nicht im Gefolge Discord server.', 'error')
                return flask.redirect(flask.url_for('index'))
            else:
                flask.flash('Dein Account wurde noch nicht freigeschaltet. Stelle dich doch bitte einmal kurz im #general vor und warte, bis ein admin dich bestätigt.', 'error')
                return flask.redirect(flask.url_for('index'))
        flask_login.login_user(mensch, remember=True)
        flask.flash(jinja2.Markup('Hallo {}.'.format(mensch.__html__())))
        next_url = flask.session.get('next')
        if next_url is None:
            return flask.redirect(flask.url_for('index'))
        elif is_safe_url(next_url):
            return flask.redirect(next_url)
        else:
            return flask.abort(400)

    @index.child('mensch', 'Menschen', decorators=[member_required])
    @gefolge_web.util.template('menschen-index')
    def menschen():
        pass

    @menschen.children(Mensch, methods=['GET', 'POST'])
    @gefolge_web.util.template()
    def profile(mensch):
        import gefolge_web.event.model

        if not mensch.is_active:
            return gefolge_web.util.render_template('profile-404', mensch=mensch), 404
        if flask.g.user.is_admin or flask.g.user == mensch:
            transfer_money_form = TransferMoneyForm(mensch)
            if transfer_money_form.submit_transfer_money_form.data and transfer_money_form.validate():
                recipient = transfer_money_form.recipient.data
                mensch.add_transaction(gefolge_web.util.Transaction.transfer(recipient, -transfer_money_form.amount.data, transfer_money_form.comment.data))
                recipient.add_transaction(gefolge_web.util.Transaction.transfer(mensch, transfer_money_form.amount.data, transfer_money_form.comment.data))
                if flask.g.user != mensch:
                    peter.bot_cmd('msg', str(mensch.snowflake), '<@{}> ({}) hat {} von deinem Guthaben an <@{}> ({}) übertragen. {}: <https://gefolge.org/me>'.format(Mensch.admin().snowflake, Mensch.admin(), transfer_money_form.amount.data, recipient.snowflake, recipient, 'Kommentar und weitere Infos' if transfer_money_form.comment.data else 'Weitere Infos'))
                if flask.g.user != recipient:
                    peter.bot_cmd('msg', str(recipient.snowflake), '<@{}> ({}) hat {} an dich übertragen. {}: <https://gefolge.org/me>'.format(mensch.snowflake, mensch, transfer_money_form.amount.data, 'Kommentar und weitere Infos' if transfer_money_form.comment.data else 'Weitere Infos'))
                return flask.redirect(flask.g.view_node.url)
        else:
            transfer_money_form = None
        return {
            'events': [event for event in gefolge_web.event.model.Event if mensch in event.signups],
            'mensch': mensch,
            'transfer_money_form': transfer_money_form
        }

    @profile.catch_init(ValueError)
    def profile_catch_init(exc, value):
        return gefolge_web.util.render_template('profile-404', snowflake=value), 404

    @profile.child('reset-key')
    def reset_api_key(mensch):
        if flask.g.user.is_admin or flask.g.user == mensch:
            del mensch.api_key
            return flask.redirect(flask.url_for('api_index'))
        else:
            flask.flash(jinja2.Markup('Du bist nicht berechtigt, den API key für {} neu zu generieren.'.format(mensch.__html__())), 'error')
            return flask.redirect(flask.url_for('api_index'))

    @index.redirect('me', decorators=[member_required])
    def me():
        return menschen, flask.g.user

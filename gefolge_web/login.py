import flask
import flask_dance.contrib.discord
import flask_login
import functools
import html
import jinja2
import json
import lazyjson
import pathlib
import urllib.parse

import gefolge_web.util

MENSCHEN = 386753710434287626 # role ID
PROFILES_ROOT = pathlib.Path('/usr/local/share/fidera/profiles')
USERDATA_ROOT = pathlib.Path('/usr/local/share/fidera/userdata')

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
    def get(cls, user_id):
        try:
            return cls(user_id)
        except ValueError:
            return None

    def __eq__(self, other):
        return hasattr(other, 'snowflake') and self.snowflake == other.snowflake

    def __hash__(self):
        return hash(self.snowflake)

    def __repr__(self):
        return 'gefolge_web.login.Mensch({!r})'.format(self.snowflake)

    def __str__(self):
        return '{}#{}'.format(self.profile_data['username'], self.discrim)

    @property
    def balance(self):
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

    @app.template_filter()
    def mention(value):
        if not hasattr(value, 'snowflake'):
            value = Mensch(value)
        return jinja2.Markup('<a title="{}" href="{}">@{}</a>'.format(value, flask.url_for('profile', mensch=str(value.snowflake)), jinja2.escape(value.name)))

    @app.before_request
    def global_user():
        flask.g.user = flask_login.current_user

    @app.route('/auth')
    def auth_callback():
        if flask_dance.contrib.discord.discord.authorized:
            response = flask_dance.contrib.discord.discord.get('/api/v6/users/@me')
            if not response.ok:
                return flask.make_response(('Discord returned error {} at {}: {}'.format(response.status_code, html.escape(response.url), html.escape(response.text)), response.status_code, []))
            flask_login.login_user(Mensch(response.json()['id']), remember=True)
            flask.flash('Hallo {}.'.format(response.json()['username']))
        else:
            flask.flash('Login fehlgeschlagen.', 'error')
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

    @menschen.children(Mensch)
    @gefolge_web.util.template()
    def profile(mensch):
        if not mensch.is_active:
            flask.abort(404)
        return {'mensch': mensch}

    @index.redirect('me', decorators=[member_required])
    def me():
        return menschen, flask.g.user

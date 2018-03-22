import flask
import flask_dance.contrib.discord
import flask_login
import functools
import html
import jinja2
import lazyjson
import pathlib
import urllib.parse

MENSCHEN = 386753710434287626 # role ID

class Mensch(flask_login.UserMixin):
    def __init__(self, snowflake):
        self.snowflake = int(snowflake)

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
        return '{}#{:04}'.format(self.data['username'], self.data['discriminator'])

    @property
    def data(self):
        return lazyjson.File(self.profile_path)

    @property
    def discrim(self):
        """Returns the username discriminator as a string with leading zeroes."""
        return '{:04}'.format(self.data['discriminator'])

    def get_id(self): # required by flask_login
        return str(self.snowflake)

    @property
    def is_active(self):
        return self.profile_path.exists() and MENSCHEN in self.data.get('roles')

    @property
    def name(self):
        if self.data.get('nick') is None:
            return self.data['username'].value()
        else:
            return self.data['nick'].value()

    @property
    def profile_path(self):
        return pathlib.Path('/usr/local/share/fidera/profiles/{}.json'.format(self.snowflake))

    @property
    def url_part(self):
        return str(self.snowflake)

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

def setup(app):
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
    login_manager.login_message = 'Du musst dich anmelden, um diese Seite sehen zu können.'
    login_manager.refresh_view = 'discord.login' #TODO separate view?
    login_manager.login_message = 'Bitte melde dich nochmal an, um diese Änderungen zu bestätigen.'

    @login_manager.user_loader
    def load_user(user_id):
        return Mensch.get(user_id)

    login_manager.init_app(app)

    @app.template_filter()
    @jinja2.evalcontextfilter
    def mention(eval_ctx, value):
        if not hasattr(value, 'snowflake'):
            value = Mensch(value)
        result = '<a href="{}">@{}</a>'.format(flask.url_for('profile', snowflake=str(value.snowflake)), jinja2.escape(value.name))
        if eval_ctx.autoescape:
            result = jinja2.Markup(result)
        return result

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
            return flask.redirect(flask.url_for('me' if flask_dance.contrib.discord.discord.authorized else 'discord.login'))
        elif is_safe_url(next_url):
            return flask.redirect(next_url)
        else:
            return flask.abort(400)

    @app.before_request
    def global_user():
        flask.g.user = flask_login.current_user

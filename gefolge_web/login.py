import flask
import flask_dance.contrib.discord
import flask_login
import urllib.parse

class Mensch(flask_login.UserMixin):
    def __init__(self, flake):
        #TODO check if valid
        self.snowflake = flake

    @classmethod
    def get(cls, user_id):
        try:
            flake = int(user_id)
        except ValueError:
            return None
        return cls(flake) #TODO catch exceptions caused by invalid snowflakes

    def get_id(self): # required by flask_login
        return str(self.snowflake)

    @property
    def is_authenticated(self):
        if self.is_anonymous:
            return False
        return super().is_authenticated

def is_safe_url(target):
    ref_url = urllib.parse.urlparse(flask.request.host_url)
    test_url = urllib.parse.urlparse(urllib.parse.urljoin(flask.request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def setup(app, config):
    if 'clientID' not in config.get('peter', {}) or 'clientSecret' not in config.get('peter', {}):
        return #TODO mount error messages at /login and /auth
    app.config['SECRET_KEY'] = config['peter']['clientSecret']
    app.config['USE_SESSION_FOR_NEXT'] = True

    app.register_blueprint(flask_dance.contrib.discord.make_discord_blueprint(
        client_id=config['peter']['clientID'],
        client_secret=config['peter']['clientSecret'],
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

    @app.route('/auth')
    def auth_callback():
        if flask_dance.contrib.discord.discord.authorized:
            response = flask_dance.contrib.discord.discord.get('/apt/v6/users/@me')
            if not response.ok:
                return flask.make_response(('Discord returned error: {!r}'.format(response), 500, []))
            flask_login.login_user(Mensch(response.json()['id']), remember=True)
            flask.flash('Hallo {}.'.format(response.json()['username']))
        else:
            flask.flash('Login fehlgeschlagen.')
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

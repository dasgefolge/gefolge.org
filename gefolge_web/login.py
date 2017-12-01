import flask
import flask_dance.contrib.discord
import flask_login

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

def setup(app, config):
    if 'clientID' not in config.get('peter', {}) or 'clientSecret' not in config.get('peter', {}):
        return #TODO mount error messages at /login and /auth
    app.config['SECRET_KEY'] = config['peter']['clientSecret']

    app.register_blueprint(flask_dance.contrib.discord.make_discord_blueprint(
        client_id=config['peter']['clientID'],
        client_secret=config['peter']['clientSecret'],
        scope='identify',
        redirect_to='auth'
    ), url_prefix='/login')

    login_manager = flask_login.LoginManager()
    login_manager.login_view = 'login'
    login_manager.login_message = 'Du musst dich anmelden, um diese Seite sehen zu können.'
    login_manager.refresh_view = 'login' #TODO separate view?
    login_manager.login_message = 'Bitte melde dich nochmal an, um diese Änderungen zu bestätigen.'

    @login_manager.user_loader
    def load_user(user_id):
        return Mensch.get(user_id)

    login_manager.init_app(app)

    @app.route('/auth')
    def auth_callback():
        if flask_dance.contrib.discord.discord.authorized:
            response = flask_dance.contrib.discord.discord.get('/users/@me')
            assert response.ok
            flask_login.login_user(Mensch(response.json()['id']), remember=True)
            flask.flash('Hallo {}.'.format(response.json()['username']))
        else:
            flask.flash('Login fehlgeschlagen.')
        #TODO redirect

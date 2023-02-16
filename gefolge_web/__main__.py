#!/usr/bin/env python3

import sys

sys.path.append('/opt/py')

import os

import challonge # PyPI: pychallonge
import flask # PyPI: Flask
import flask_bootstrap # PyPI: Flask-Bootstrap
import flask_pagedown # PyPI: Flask-PageDown
import flask_sqlalchemy # PyPI: Flask-SQLAlchemy
import flaskext.markdown # PyPI: Flask-Markdown
import gql # PyPI: --pre gql[all]
import gql.transport.aiohttp # PyPI: --pre gql[all]
import jinja2 # PyPI: Jinja2
import pymdownx.emoji # PyPI: pymdown-extensions
import pymdownx.extra # PyPI: pymdown-extensions
import pymdownx.tilde # PyPI: pymdown-extensions

import flask_view_tree # https://github.com/fenhl/flask-view-tree
import flask_wiki # https://github.com/fenhl/flask-wiki
import lazyjson # https://github.com/fenhl/lazyjson
import peter # https://github.com/dasgefolge/peter-discord

try:
    import ricochet_robots # extension for Ricochet Robots online, closed-source for IP reasons
except ImportError:
    ricochet_robots = None
try:
    import spacealert.web # extension for the Space Alert brainscan database, closed-source for IP reasons
except ImportError:
    spacealert = None
try:
    import werewolf_web # extension for Werewolf games, closed-source to allow the admin to make relevant changes before a game without giving away information to players
except ImportError:
    werewolf_web = None

import gefolge_web.api
import gefolge_web.event
import gefolge_web.games
import gefolge_web.login
import gefolge_web.util

DOCUMENT_ROOT = os.environ.get('FLASK_ROOT_PATH', '/opt/git/github.com/dasgefolge/gefolge.org/master')
WIKI_CHANNEL_ID = 739623881719021728

app = application = flask.Flask('gefolge_web', root_path=DOCUMENT_ROOT, instance_path=DOCUMENT_ROOT)

with app.app_context():
    app.url_map.strict_slashes = False
    app.jinja_env.autoescape = jinja2.select_autoescape(
        default_for_string=True,
        enabled_extensions=('html', 'xml', 'j2')
    )
    # load config
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql:///gefolge'
    if gefolge_web.util.CONFIG_PATH.exists():
        app.config.update(gefolge_web.util.cached_json(lazyjson.File(gefolge_web.util.CONFIG_PATH)).value())
    # set up database
    db = flask_sqlalchemy.SQLAlchemy(app)
    # set up API clients
    if 'challonge' in app.config:
        challonge.set_credentials(app.config['challonge']['username'], app.config['challonge']['apiKey'])
    if 'startggToken' in app.config:
        gefolge_web.util.CACHE['startggClient'] = gql.Client(transport=gql.transport.aiohttp.AIOHTTPTransport(url='https://api.start.gg/gql/alpha', headers={'Authorization': f'Bearer {app.config["startggToken"]}'}), fetch_schema_from_transport=True)
    # set up Bootstrap
    flask_bootstrap.Bootstrap(app)
    # set up Markdown
    md = flaskext.markdown.Markdown(app, extensions=['toc'], extension_configs={
        'toc': {
            'marker': ''
        }
    })
    emoji_ext = pymdownx.emoji.EmojiExtension()
    emoji_ext.setConfig('emoji_generator', pymdownx.emoji.to_alt)
    emoji_ext.setConfig('emoji_index', pymdownx.emoji.twemoji)
    md._instance.registerExtensions([emoji_ext], {})
    md.register_extension(pymdownx.extra.ExtraExtension)
    md.register_extension(pymdownx.tilde.DeleteSubExtension)
    # set up Markdown preview
    flask_pagedown.PageDown(app)

@flask_view_tree.index(app)
@gefolge_web.util.template('index')
def index():
    pass

def wiki_save_hook(namespace, title, text, author, summary):
    if namespace == 'wiki':
        url = f'https://gefolge.org/wiki/{title}'
    else:
        url = f'https://gefolge.org/wiki/{title}/{namespace}'
    msg = f'<{url}> wurde von <@{author.snowflake}> bearbeitet'
    if summary:
        msg += f':\n> {peter.escape(summary)}'
    peter.channel_msg(WIKI_CHANNEL_ID, msg)

with app.app_context():
    # set up submodules
    gefolge_web.api.setup(index)
    gefolge_web.event.setup(index, app)
    games_index = gefolge_web.games.setup(index)
    if ricochet_robots is not None:
        ricochet_robots.setup(games_index)
    if spacealert is not None:
        spacealert.web.setup(games_index)
    if werewolf_web is not None:
        werewolf_web.setup(games_index)
    gefolge_web.login.setup(index, app)
    gefolge_web.util.setup(app)
    flask_wiki.child(
        index,
        db=db,
        decorators=[gefolge_web.login.mensch_required],
        md=md,
        save_hook=wiki_save_hook,
        user_class=gefolge_web.login.Mensch,
        wiki_name='GefolgeWiki'
    )

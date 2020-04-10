#!/usr/bin/env python3

import sys

sys.path.append('/opt/py')

import os
import pathlib

import challonge # PyPI: pychal
import flask # PyPI: Flask
import flask_bootstrap # PyPI: Flask-Bootstrap
import flask_pagedown # PyPI: Flask-PageDown
import flask_sqlalchemy # Flask-SQLAlchemy
import flaskext.markdown # PyPI: Flask-Markdown
import jinja2 # PyPI: jinja2
import pymdownx.emoji # PyPI: pymdown-extensions
import pymdownx.extra # PyPI: pymdown-extensions
import pymdownx.tilde # PyPI: pymdown-extensions

import flask_view_tree # https://github.com/fenhl/flask-view-tree
import flask_wiki # https://github.com/fenhl/flask-wiki
import lazyjson # https://github.com/fenhl/lazyjson

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
    # set up Challonge API client
    if 'challonge' in app.config:
        challonge.set_credentials(app.config['challonge']['username'], app.config['challonge']['apiKey'])
    # set up Bootstrap
    flask_bootstrap.Bootstrap(app)
    # set up Markdown
    md = flaskext.markdown.Markdown(app)
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

with app.app_context():
    # set up submodules
    gefolge_web.api.setup(index)
    gefolge_web.login.setup(index, app)
    flask_wiki.child(
        index,
        db=db,
        edit_decorators=[gefolge_web.login.member_required],
        md=md,
        user_class=gefolge_web.login.Mensch,
        wiki_name='GefolgeWiki'
    )
    gefolge_web.event.setup(index, app)
    games_index = gefolge_web.games.setup(index)
    gefolge_web.util.setup(app)
    if spacealert is not None:
        spacealert.web.setup(games_index)
    if werewolf_web is not None:
        werewolf_web.setup(games_index)

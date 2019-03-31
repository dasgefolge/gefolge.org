#!/usr/bin/env python3

import sys

sys.path.append('/opt/py')

import flask
import flask_bootstrap
import flask_pagedown
import flask_view_tree
import flaskext.markdown
import lazyjson
import os
import pathlib
import pymdownx.emoji
import pymdownx.extra
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
import gefolge_web.wiki

DOCUMENT_ROOT = os.environ.get('FLASK_ROOT_PATH', '/opt/git/github.com/dasgefolge/gefolge.org/master')

app = application = flask.Flask('gefolge_web', root_path=DOCUMENT_ROOT, instance_path=DOCUMENT_ROOT)

with app.app_context():
    app.url_map.strict_slashes = False
    # load config
    if gefolge_web.util.CONFIG_PATH.exists():
        app.config.update(gefolge_web.util.cached_json(lazyjson.File(gefolge_web.util.CONFIG_PATH)).value())
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
    gefolge_web.wiki.setup(index, md)
    gefolge_web.event.setup(index, app)
    games_index = gefolge_web.games.setup(index)
    gefolge_web.util.setup(app)
    if spacealert is not None:
        spacealert.web.setup(games_index)
    if werewolf_web is not None:
        werewolf_web.setup(games_index)

#!/usr/bin/env python3

"""
gefolge.org
"""

import sys

sys.path.append('/opt/py')

import flask
import flask_bootstrap
import flask_login
import flaskext.markdown
import json
import os
import pathlib
import pymdownx.emoji
import pymdownx.extra

import gefolge_web.event
import gefolge_web.login
import gefolge_web.util
import gefolge_web.wiki

CONFIG_PATH = pathlib.Path('/usr/local/share/fidera/config.json')
DOCUMENT_ROOT = os.environ.get('FLASK_ROOT_PATH', '/opt/git/github.com/dasgefolge/gefolge.org/master')

app = application = flask.Flask('gefolge_web', root_path=DOCUMENT_ROOT, instance_path=DOCUMENT_ROOT)

with app.app_context():
    # load config
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as config_f:
            flask.g.config = json.load(config_f)
    else:
        flask.g.config = {}
    # set up Bootstrap
    flask_bootstrap.Bootstrap(app)
    # set up Markdown
    md = flaskext.markdown.Markdown(app)
    emoji_ext = pymdownx.emoji.EmojiExtension()
    emoji_ext.setConfig('emoji_generator', pymdownx.emoji.to_alt)
    emoji_ext.setConfig('emoji_index', pymdownx.emoji.twemoji)
    md._instance.registerExtensions([emoji_ext], {})
    md.register_extension(pymdownx.extra.ExtraExtension)
    # set up submodules
    gefolge_web.login.setup(app, flask.g.config)
    gefolge_web.wiki.setup(app, md)
    gefolge_web.event.setup(app)
    gefolge_web.util.setup(app)

@app.route('/')
@gefolge_web.util.template('index')
def index():
    pass

@app.route('/me')
@flask_login.login_required
def me():
    return flask.redirect(flask.url_for('profile', snowflake=str(flask.g.user.snowflake)))

@app.route('/mensch/<snowflake>')
@gefolge_web.login.member_required
@gefolge_web.util.template()
def profile(snowflake):
    mensch = gefolge_web.login.Mensch(snowflake)
    if not mensch.is_active:
        return flask.make_response(('Dieser Discord account existiert nicht oder ist nicht im Gefolge.', 404, []))
    return {'mensch': mensch}

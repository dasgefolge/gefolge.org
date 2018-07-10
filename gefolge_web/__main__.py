#!/usr/bin/env python3

import sys

sys.path.append('/opt/py')

import flask
import flask_bootstrap
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
    app.url_map.strict_slashes = False
    # load config
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as config_f:
            app.config.update(json.load(config_f))
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
    gefolge_web.login.setup(app)
    gefolge_web.wiki.setup(app, md)
    gefolge_web.event.setup(app)
    gefolge_web.util.setup(app)

@app.route('/')
@gefolge_web.util.template('index')
def index():
    pass

@app.route('/me')
@gefolge_web.login.member_required
def me():
    return flask.redirect(flask.url_for('profile', snowflake=str(flask.g.user.snowflake)))

@app.route('/mensch')
@gefolge_web.login.member_required
@gefolge_web.util.path(('mensch', 'Menschen'))
@gefolge_web.util.template('menschen-index')
def menschen():
    return {
        'menschen_list': [
            gefolge_web.login.Mensch(profile_path.stem)
            for profile_path in sorted(gefolge_web.login.PROFILES_ROOT.iterdir(), key=lambda path: int(path.stem))
            if gefolge_web.login.Mensch(profile_path.stem).is_active
        ]
    }

@app.route('/mensch/<snowflake>')
@gefolge_web.login.member_required
@gefolge_web.util.path(gefolge_web.login.Mensch, menschen)
@gefolge_web.util.template()
def profile(snowflake):
    mensch = gefolge_web.login.Mensch(snowflake)
    if not mensch.is_active:
        return flask.make_response(('Dieser Discord account existiert nicht oder ist nicht im Gefolge.', 404, []))
    return {'mensch': mensch}

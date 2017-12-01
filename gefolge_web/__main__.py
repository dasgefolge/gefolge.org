#!/usr/bin/env python3

"""
gefolge.org
"""

import flask
import flask_login
import json
import os
import pathlib

import gefolge_web.login

CONFIG_PATH = pathlib.Path('/usr/local/share/fidera/config.json')
DOCUMENT_ROOT = os.environ.get('FLASK_ROOT_PATH', '/opt/git/github.com/dasgefolge/gefolge.org/master')

app = application = flask.Flask('gefolge_web', root_path=DOCUMENT_ROOT, instance_path=DOCUMENT_ROOT)

with app.app_context():
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as config_f:
            flask.g.config = json.load(config_f)
    else:
        flask.g.config = {}
    gefolge_web.login.setup(app, flask.g.config)

@app.route('/')
def index():
    return """<!DOCTYPE html>
    <html>
        <head>
            <meta charset="utf-8" />
            <title>Das Gefolge</title>
            <link rel="stylesheet" href="https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap.min.css" />
            <link rel="stylesheet" href="https://netdna.bootstrapcdn.com/font-awesome/3.2.1/css/font-awesome.css" />
            <link rel="stylesheet" href="/static/common.css" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta name="description" content="Das Gefolge" />
            <meta name="author" content="Fenhl & contributors" />
        </head>
        <body>
            <div id="container" style="text-align: center;">
                <div><img style="max-width: 100%; max-height: 500px;" src="/static/gefolge.png" /></div>
                <p>Das <b><a href="//wiki.gefolge.org/Gefolge">Gefolge</a></b> ist eine lose Gruppe von <a href="//wiki.gefolge.org/Mensch">Menschen</a> und <a href="//wiki.gefolge.org/Benutzer:Xor">anderen Lebewesen</a>, die sich größtenteils über die <a href="//wiki.gefolge.org/Camp">Mensa Juniors Camps</a> kennen.</a>
                <p>Wir haben ein <a href="//wiki.gefolge.org/">Wiki</a> und einen <a href="https://discordapp.com/">Discord server</a> (Einladung für Gefolgemenschen auf Anfrage).</p>
                <hr/>
                <footer>
                    <p class="muted text-center">
                        <a href="http://fenhl.net/">hosted by fenhl.net</a> — <a href="http://fenhl.net/disc">disclaimer</a>
                    </p>
                    <p class="muted text-center">
                        Bild CC-BY-SA 2.5 Ronald Preuss, aus Wikimedia Commons (<a href="https://commons.wikimedia.org/wiki/File:Ritter_gefolge.jpg">Link</a>)
                    </p>
                </footer>
            </div>
            <script src="https://code.jquery.com/jquery.js"></script>
            <script src="https://netdna.bootstrapcdn.com/bootstrap/3.0.0/js/bootstrap.min.js"></script>
        </body>
    </html>
    """

@app.route('/me')
@flask_login.login_required
def me():
    return flask.redirect(flask.url_for('profile', snowflake=str(flask.g.user.snowflake)))

@app.route('/mensch/<snowflake>')
@flask_login.login_required
def profile(snowflake):
    if not flask.g.user.is_active:
        #TODO make this a decorator
        return flask.make_response(('Sie haben keinen Zugriff auf diesen Inhalt, weil Sie nicht im Gefolge Discord server sind.', 403, []))
    mensch = gefolge_web.login.Mensch(snowflake)
    if not mensch.is_active:
        return flask.make_response(('Dieser Discord account existiert nicht oder ist nicht im Gefolge.', 404, []))
    return '{}'.format(snowflake) #TODO template, more user info

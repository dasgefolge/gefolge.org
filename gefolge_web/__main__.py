#!/usr/bin/env python3

"""
gefolge.org
"""

import sys

sys.path.append('/opt/py')

import flask
import flask_bootstrap
import flask_login
import functools
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
    flask_bootstrap.Bootstrap(app)

def template(template_name=None):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if template_name is None:
                template_path = '{}.html'.format(flask.request.endpoint.replace('.', '/'))
            else:
                template_path = '{}.html'.format(template_name.replace('.', '/'))
            context = f(*args, **kwargs)
            if context is None:
                context = {}
            elif not isinstance(context, dict):
                return context
            return flask.render_template(template_path, **context)

        return wrapper

    return decorator

@app.route('/')
@template('index')
def index():
    pass

@app.route('/me')
@flask_login.login_required
def me():
    return flask.redirect(flask.url_for('profile', snowflake=str(flask.g.user.snowflake)))

@app.route('/mensch/<snowflake>')
@gefolge_web.login.member_required
@template()
def profile(snowflake):
    mensch = gefolge_web.login.Mensch(snowflake)
    if not mensch.is_active:
        return flask.make_response(('Dieser Discord account existiert nicht oder ist nicht im Gefolge.', 404, []))
    return {'mensch': mensch}

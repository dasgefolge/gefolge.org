#!/usr/bin/env python3

"""
gefolge.org
"""

import bottle

DOCUMENT_ROOT = '/opt/git/github.com/dasgefolge/gefolge.org/master'

bottle.debug()

application = bottle.Bottle()

@application.route('/')
def index():
    return """<!DOCTYPE html>
    <html>
        <head>
            <meta charset="utf-8" />
            <title>Das Gefolge</title>
            <link rel="stylesheet" href="https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap.min.css" />
            <link rel="stylesheet" href="https://netdna.bootstrapcdn.com/font-awesome/3.2.1/css/font-awesome.css" />
            <link rel="stylesheet" href="/common.css" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta name="description" content="Das Gefolge" />
            <meta name="author" content="Fenhl & contributors" />
        </head>
        <body>
            <div id="container" style="text-align: center;">
                <div><img style="max-width: 100%; max-height: 500px;" src="gefolge.png" /></div>
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

@application.route('/common.css')
def logo():
    return bottle.static_file('static/common.css', root=DOCUMENT_ROOT)

@application.route('/gefolge.png')
def logo():
    return bottle.static_file('static/gefolge.png', root=DOCUMENT_ROOT)

if __name__ == '__main__':
    bottle.run(app=application, host='0.0.0.0', port=8081)

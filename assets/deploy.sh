#!/bin/zsh

set -e

if [[ x"$(hostname -f)" == x'mercredi.fenhl.net' ]]; then
    # deploy peter
    cd /opt/git/github.com/dasgefolge/peter-discord/master
    git --git-dir=/opt/git/github.com/dasgefolge/peter-discord/master/.git pull
    cargo build --release --package=peter-python
    # deploy ricochet-robots
    cd /opt/git/github.com/dasgefolge/ricochet-robots/master
    git --git-dir=/opt/git/github.com/dasgefolge/ricochet-robots/master/.git pull
    cargo build --release --package=ricochet-robots-websocket
    # deploy flask-view-tree
    cd /opt/git/github.com/fenhl/flask-view-tree/master
    git --git-dir=/opt/git/github.com/fenhl/flask-view-tree/master/.git pull
    # deploy spacealert
    cd /opt/git/github.com/dasgefolge/spacealert/master
    git --git-dir=/opt/git/github.com/dasgefolge/spacealert/master/.git pull
    # deploy werewolf_web
    cd /opt/git/localhost/werewolf_web/master
    git --git-dir=/opt/git/localhost/werewolf_web/master/.git pull
    # deploy gefolge.org
    cd /opt/git/github.com/dasgefolge/gefolge.org/master
    git --git-dir=/opt/git/github.com/dasgefolge/gefolge.org/master/.git pull
    # restart nginx (since nginx config is tracked by git) and uWSGI
    sudo systemctl daemon-reload
    sudo systemctl reload nginx
    sudo systemctl reload uwsgi
else
    ssh mercredi.fenhl.net gefolge-web-deploy
fi

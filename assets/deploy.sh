#!/bin/zsh

set -e

if [[ x"$(hostname -f)" == x'vendredi.fenhl.net' ]]; then
    # deploy flask-view-tree
    echo 'deploying flask-view-tree'
    cd /opt/git/github.com/fenhl/flask-view-tree/main
    git --git-dir=/opt/git/github.com/fenhl/flask-view-tree/main/.git pull
    # deploy spacealert
    echo 'deploying spacealert'
    cd /opt/git/github.com/dasgefolge/spacealert/main
    git --git-dir=/opt/git/github.com/dasgefolge/spacealert/main/.git pull
    # deploy gefolge.org
    echo 'deploying gefolge.org'
    cd /opt/git/github.com/dasgefolge/gefolge.org/main
    git --git-dir=/opt/git/github.com/dasgefolge/gefolge.org/main/.git pull
    # restart nginx (since nginx config is tracked by git) and uWSGI
    sudo systemctl daemon-reload
    sudo systemctl reload nginx
    sudo systemctl reload uwsgi
else
    echo 'this deploy script is no longer necessary, see https://status.gefolge.org/ for deployment status'
    exit 1
fi

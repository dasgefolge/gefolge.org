#!/bin/zsh

set -e

if [[ x"$(hostname -f)" == x'vendredi.fenhl.net' ]]; then
    # deploy flask-view-tree
    echo 'deploying flask-view-tree'
    env -C /opt/git/github.com/fenhl/flask-view-tree/main git --git-dir=/opt/git/github.com/fenhl/flask-view-tree/main/.git pull
    # deploy spacealert
    echo 'deploying spacealert'
    env -C /opt/git/github.com/dasgefolge/spacealert/main git --git-dir=/opt/git/github.com/dasgefolge/spacealert/main/.git pull
    # deploy gefolge.org
    echo 'deploying gefolge.org'
    rustup update stable
    #TODO cargo sweep (limit to once per Rust version)
    cargo build --jobs=-1 --release --package=gefolge-web --package=gefolge-web-back
    sudo systemctl stop gefolge-web
    env -C /opt/git/github.com/dasgefolge/gefolge.org/main git --git-dir=/opt/git/github.com/dasgefolge/gefolge.org/main/.git pull
    cp target/release/gefolge-web /home/fenhl/bin/gefolge-web
    cp target/release/gefolge-web-back ~/bin/gefolge-web-back
    sudo systemctl start gefolge-web
    # restart nginx (since nginx config is tracked by git) and uWSGI
    sudo systemctl daemon-reload
    sudo systemctl reload nginx
    sudo systemctl reload uwsgi
else
    echo 'this deploy script is no longer necessary, see https://status.gefolge.org/ for deployment status'
    exit 1
fi

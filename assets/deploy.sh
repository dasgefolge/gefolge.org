#!/bin/zsh

set -e

if [[ x"$(hostname -f)" == x'vendredi.fenhl.net' ]]; then
    # deploy peter
    cd /opt/git/github.com/dasgefolge/peter-discord/main
    git --git-dir=/opt/git/github.com/dasgefolge/peter-discord/main/.git pull
    cargo build --release --package=peter-python
    # deploy flask-view-tree
    cd /opt/git/github.com/fenhl/flask-view-tree/main
    git --git-dir=/opt/git/github.com/fenhl/flask-view-tree/main/.git pull
    # deploy spacealert
    cd /opt/git/github.com/dasgefolge/spacealert/main
    git --git-dir=/opt/git/github.com/dasgefolge/spacealert/main/.git pull
    # deploy werewolf_web
    cd /opt/git/localhost/werewolf_web/main
    git --git-dir=/opt/git/localhost/werewolf_web/main/.git pull
    # deploy gefolge.org
    cd /opt/git/github.com/dasgefolge/gefolge.org/main
    git --git-dir=/opt/git/github.com/dasgefolge/gefolge.org/main/.git pull
    # restart nginx (since nginx config is tracked by git) and uWSGI
    sudo systemctl daemon-reload
    sudo systemctl reload nginx
    sudo systemctl reload uwsgi
else
    git push
    cargo build --release --target=x86_64-unknown-linux-musl --package=gefolge-web --package=gefolge-web-back
    scp target/x86_64-unknown-linux-musl/release/gefolge-web gefolge.org:bin/gefolge-web
    scp target/x86_64-unknown-linux-musl/release/gefolge-web-back gefolge.org:bin/gefolge-web-back
    ssh gefolge.org /opt/git/github.com/dasgefolge/gefolge.org/main/assets/deploy.sh
fi

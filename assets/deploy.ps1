git push
if (-not $?)
{
    throw 'Native Failure'
}

# copy the tree to the WSL file system to improve compile times
wsl rsync --delete -av /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/ /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/ --exclude target
if (-not $?)
{
    throw 'Native Failure'
}

wsl env -C /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org cargo build --release --target=x86_64-unknown-linux-musl --package=gefolge-web --package=gefolge-web-back
if (-not $?)
{
    throw 'Native Failure'
}

wsl cp /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/target/x86_64-unknown-linux-musl/release/gefolge-web /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/target/wsl/release/gefolge-web
if (-not $?)
{
    throw 'Native Failure'
}

wsl cp /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/target/x86_64-unknown-linux-musl/release/gefolge-web-back /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/target/wsl/release/gefolge-web-back
if (-not $?)
{
    throw 'Native Failure'
}

ssh gefolge.org env -C /opt/git/github.com/dasgefolge/gefolge.org/main git pull
if (-not $?)
{
    throw 'Native Failure'
}

ssh gefolge.org sudo systemctl stop gefolge-web
if (-not $?)
{
    throw 'Native Failure'
}

scp .\target\wsl\release\gefolge-web gefolge.org:bin/gefolge-web
if (-not $?)
{
    throw 'Native Failure'
}

scp .\target\wsl\release\gefolge-web-back gefolge.org:bin/gefolge-web-back
if (-not $?)
{
    throw 'Native Failure'
}

ssh gefolge.org /opt/git/github.com/dasgefolge/gefolge.org/main/assets/deploy.sh
if (-not $?)
{
    throw 'Native Failure'
}

ssh gefolge.org sudo systemctl start gefolge-web
if (-not $?)
{
    throw 'Native Failure'
}

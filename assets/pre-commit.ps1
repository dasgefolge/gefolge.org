#!/usr/bin/env pwsh

cargo check
if (-not $?)
{
    throw 'Native Failure'
}

cargo sqlx prepare --workspace --check -- -p gefolge-web -p gefolge-web-lib -p gefolge-web-back -p gefolge-paypal
if (-not $?)
{
    throw 'Native Failure'
}

# copy the tree to the WSL file system to improve compile times
wsl -d ubuntu-m2 rsync --mkpath --delete -av /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/ /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/ --exclude target
if (-not $?)
{
    throw 'Native Failure'
}

wsl -d ubuntu-m2 env -C /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org /home/fenhl/.cargo/bin/cargo check --workspace
if (-not $?)
{
    throw 'Native Failure'
}

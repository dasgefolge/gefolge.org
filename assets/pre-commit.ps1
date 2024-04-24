#!/usr/bin/env pwsh

function ThrowOnNativeFailure {
    if (-not $?)
    {
        throw 'Native Failure'
    }
}

cargo check
ThrowOnNativeFailure

cargo sqlx prepare --workspace --check -- -p gefolge-web -p gefolge-web-back
ThrowOnNativeFailure

# copy the tree to the WSL file system to improve compile times
wsl rsync --delete -av /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/ /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/ --exclude target
ThrowOnNativeFailure

wsl env -C /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org cargo check --workspace
ThrowOnNativeFailure

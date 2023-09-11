function ThrowOnNativeFailure {
    if (-not $?)
    {
        throw 'Native Failure'
    }
}

git push
ThrowOnNativeFailure

# copy the tree to the WSL file system to improve compile times
wsl rsync --delete -av /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/ /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/ --exclude target
ThrowOnNativeFailure

wsl env -C /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org cargo build --release --target=x86_64-unknown-linux-musl --package=gefolge-web --package=gefolge-web-back
ThrowOnNativeFailure

wsl cp /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/target/x86_64-unknown-linux-musl/release/gefolge-web /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/target/wsl/release/gefolge-web
ThrowOnNativeFailure

wsl cp /home/fenhl/wslgit/github.com/dasgefolge/gefolge.org/target/x86_64-unknown-linux-musl/release/gefolge-web-back /mnt/c/Users/fenhl/git/github.com/dasgefolge/gefolge.org/stage/target/wsl/release/gefolge-web-back
ThrowOnNativeFailure

ssh gefolge.org env -C /opt/git/github.com/dasgefolge/gefolge.org/main git pull
ThrowOnNativeFailure

ssh gefolge.org sudo systemctl stop gefolge-web
ThrowOnNativeFailure

scp .\target\wsl\release\gefolge-web gefolge.org:bin/gefolge-web
ThrowOnNativeFailure

scp .\target\wsl\release\gefolge-web-back gefolge.org:bin/gefolge-web-back
ThrowOnNativeFailure

ssh gefolge.org sudo systemctl start gefolge-web
ThrowOnNativeFailure

ssh gefolge.org gefolge-web-deploy
ThrowOnNativeFailure

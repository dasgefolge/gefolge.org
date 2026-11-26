use {
    std::{
        collections::HashMap,
        env,
        io::prelude::*,
        path::{
            Path,
            PathBuf,
        },
        pin::Pin,
    },
    futures::{
        future::Future,
        stream::TryStreamExt as _,
    },
    git2::{
        Oid,
        Repository,
    },
    tokio::pin,
    wheel::{
        fs::{
            self,
            File,
        },
        io::Annotate as _,
    },
};

#[derive(Debug, thiserror::Error)]
enum Error {
    #[error(transparent)] Git(#[from] git2::Error),
    #[error(transparent)] Io(#[from] wheel::io::Error),
    #[error(transparent)] PathStripPrefix(#[from] std::path::StripPrefixError),
}

fn check_static_file(cache: &mut HashMap<PathBuf, Oid>, workspace: &Path, repo: &Repository, relative_path: &Path, path: PathBuf) -> Result<(), Error> {
    let mut iter_commit = repo.head()?.peel_to_commit()?;
    let commit_id = loop {
        let iter_commit_id = iter_commit.id();
        if iter_commit.parent_count() != 1 {
            // initial commit or merge commit; mark the file as updated here for simplicity's sake
            break iter_commit_id
        }
        let parent = iter_commit.parent(0)?;
        let diff = repo.diff_tree_to_tree(Some(&parent.tree()?), Some(&iter_commit.tree()?), Some(git2::DiffOptions::default().pathspec(&path.strip_prefix(workspace)?)))?;
        if diff.deltas().next().is_some() {
            break iter_commit_id
        }
        iter_commit = parent;
    };
    cache.insert(relative_path.to_owned(), commit_id);
    Ok(())
}

fn check_static_dir<'a>(cache: &'a mut HashMap<PathBuf, Oid>, workspace: &'a Path, repo: &'a Repository, relative_path: &'a Path, path: PathBuf) -> Pin<Box<dyn Future<Output = Result<(), Error>> + 'a>> {
    Box::pin(async move {
        pin! {
            let entries = fs::read_dir(&path);
        }
        while let Some(entry) = entries.try_next().await? {
            if entry.file_type().await.at(entry.path())?.is_dir() {
                check_static_dir(cache, workspace, repo, &relative_path.join(entry.file_name()), entry.path()).await?;
            } else {
                check_static_file(cache, workspace, repo, &relative_path.join(entry.file_name()), entry.path())?;
            }
        }
        Ok(())
    })
}

#[wheel::main]
async fn main() -> Result<(), Error> {
    println!("cargo:rerun-if-changed=nonexistent.foo"); // check a nonexistent file to make sure build script is always run (see https://github.com/rust-lang/cargo/issues/4213 and https://github.com/rust-lang/cargo/issues/5663)
    let workspace = fs::canonicalize(PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap())).await?.parent().unwrap().parent().unwrap().to_owned();
    let static_dir = workspace.join("assets").join("static");
    let mut cache = HashMap::default();
    let repo = Repository::open(&workspace)?;
    pin! {
        let entries = fs::read_dir(&static_dir);
    }
    while let Some(entry) = entries.try_next().await? {
        if entry.file_type().await.at(entry.path())?.is_dir() {
            check_static_dir(&mut cache, &workspace, &repo, entry.file_name().as_ref(), entry.path()).await?;
        } else {
            check_static_file(&mut cache, &workspace, &repo, entry.file_name().as_ref(), entry.path())?;
        }
    }
    let out_path = Path::new(&env::var_os("OUT_DIR").unwrap()).join("static_files.rs");
    let mut out_f = File::create(&out_path).await?.into_std().await;
    writeln!(&mut out_f, "#[allow(unused)]").at(&out_path)?; //TODO remove after Rust migration is completed
    writeln!(&mut out_f, "macro_rules! static_url {{").at(&out_path)?;
    for (path, commit_id) in cache {
        let unix_path = path.to_str().expect("non-UTF-8 static file path").replace('\\', "/");
        let uri = format!("/static/{unix_path}?v={commit_id}");
        writeln!(&mut out_f, "    ({unix_path:?}) => {{").at(&out_path)?;
        writeln!(&mut out_f, "        ::rocket_util::Origin(::rocket::uri!({uri:?}))").at(&out_path)?;
        writeln!(&mut out_f, "    }};").at(&out_path)?;
    }
    writeln!(&mut out_f, "}}").at(out_path)?;
    Ok(())
}

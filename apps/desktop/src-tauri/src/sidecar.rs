//! Lifetime of the Python core.
//!
//! The shell spawns it, learns which port it landed on, and kills it on quit. A
//! journal app that leaves an orphaned server behind after you quit — still
//! holding your notes open, still listening — is a worse bug than a crash, so
//! teardown gets as much care here as startup.
//!
//! Two things travel across the boundary in opposite directions: a per-launch
//! bearer token goes down in the environment, and the port the OS handed out
//! comes back up on stdout. Neither is ever written to disk.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::Duration;

use tauri::AppHandle;
#[cfg(not(debug_assertions))]
use tauri::Manager;

/// The prefix `tilt.serve` writes before its one line of JSON.
const READY_PREFIX: &str = "TILT_READY ";

/// Generous: a cold PyInstaller bundle pays for unpacking and imports on first
/// run. Short enough that a genuinely dead sidecar reports rather than hangs.
const READY_TIMEOUT: Duration = Duration::from_secs(45);

/// Where the repository's Python lives, resolved at compile time. Only used by
/// debug builds — a release bundle runs the packaged binary and never looks for
/// a checkout that will not be there.
#[cfg(debug_assertions)]
const REPO_CORE: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../core");

pub struct Core {
    pub base_url: String,
    pub token: String,
    child: Mutex<Option<Child>>,
    /// Held open and never written to. Its only job is to close when this
    /// process ends, which is how the core learns the shell is gone even when
    /// the shell had no chance to say so.
    _lifeline: Mutex<Option<ChildStdin>>,
}

impl Core {
    /// Spawn the core and block until it reports the port it is listening on.
    pub fn start(app: &AppHandle) -> Result<Self, String> {
        let token = mint_token();
        let mut command = command_for(app)?;

        command
            .env("TILT_HOST", "127.0.0.1")
            // 0 means "any free port". Two copies of Tilt then never collide,
            // and neither does anything else already holding a fixed number.
            .env("TILT_PORT", "0")
            .env("TILT_AUTH_TOKEN", &token)
            // Killing the core on quit covers an orderly exit. This covers the
            // rest: if the shell panics or is killed outright, the pipe below
            // closes and the core stops on its own.
            .env("TILT_EXIT_WITH_PARENT", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not start the Tilt core: {e}"))?;

        let lifeline = child.stdin.take();
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "The Tilt core produced no output.".to_string())?;
        if let Some(stderr) = child.stderr.take() {
            forward(BufReader::new(stderr), "core");
        }

        match await_ready(stdout) {
            Ok(port) => Ok(Self {
                base_url: format!("http://127.0.0.1:{port}"),
                token,
                child: Mutex::new(Some(child)),
                _lifeline: Mutex::new(lifeline),
            }),
            Err(reason) => {
                // Never leave a half-started process behind on a failed launch.
                let _ = child.kill();
                let _ = child.wait();
                Err(reason)
            }
        }
    }

    /// Stop the core. Safe to call more than once — quitting can arrive as both
    /// a window close and an application exit.
    pub fn shutdown(&self) {
        let Ok(mut slot) = self.child.lock() else {
            return;
        };
        if let Some(mut child) = slot.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for Core {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// 32 bytes of entropy as hex. Regenerated every launch, so a token that leaks
/// into a log is worthless by the next time you open the app.
fn mint_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the operating system has no entropy source");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Read stdout until the ready line arrives, then hand the rest to the logger.
fn await_ready(stdout: ChildStdout) -> Result<u16, String> {
    let (tx, rx) = mpsc::channel();
    let mut reader = BufReader::new(stdout);

    std::thread::spawn(move || {
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break, // the pipe closed: the core exited
                Ok(_) => {}
            }
            if let Some(rest) = line.trim().strip_prefix(READY_PREFIX) {
                let port = serde_json::from_str::<serde_json::Value>(rest)
                    .ok()
                    .and_then(|v| v.get("port").and_then(|p| p.as_u64()))
                    .and_then(|p| u16::try_from(p).ok());
                if tx.send(port).is_err() {
                    return; // nobody is waiting any more
                }
                break;
            }
            eprint!("[core] {line}");
        }
        let _ = tx.send(None);
        // Whatever the core says after startup is diagnostics, not protocol.
        forward(reader, "core");
    });

    match rx.recv_timeout(READY_TIMEOUT) {
        Ok(Some(port)) => Ok(port),
        Ok(None) => Err("The Tilt core stopped before it was ready.".into()),
        Err(_) => Err("The Tilt core did not start in time.".into()),
    }
}

fn forward<R: BufRead + Send + 'static>(reader: R, tag: &'static str) {
    std::thread::spawn(move || {
        for line in reader.lines().map_while(Result::ok) {
            eprintln!("[{tag}] {line}");
        }
    });
}

/// The checkout's Python in a development build, the packaged core otherwise.
///
/// The order matters, and it used to be the other way round. A frozen sidecar
/// left in `binaries/` by an earlier `build-sidecar.sh` is a resource of the
/// debug build too, so checking for it first meant `npm run tauri dev` silently
/// ran that stale freeze instead of the working tree — you pull, restart, and
/// the app reports the version you just replaced, with nothing to say why.
/// Development means the checkout; there is no reading of it under which a
/// months-old binary is what someone editing `core/` asked to run.
fn command_for(app: &AppHandle) -> Result<Command, String> {
    #[cfg(debug_assertions)]
    {
        let _ = app;
        let root = PathBuf::from(REPO_CORE);
        let venv = root.join(".venv/bin/python");
        let python = if venv.exists() {
            venv
        } else {
            PathBuf::from("python3")
        };
        let mut command = Command::new(python);
        command.args(["-m", "tilt"]).current_dir(&root);
        Ok(command)
    }

    #[cfg(not(debug_assertions))]
    {
        bundled(app).map(Command::new).ok_or_else(|| {
            "The Tilt core is missing from this build. Run scripts/build-sidecar.sh.".into()
        })
    }
}

/// PyInstaller's `--onedir` output, copied into the bundle as a resource
/// directory. It cannot be an `externalBin`: those are single files, and the
/// core ships alongside a folder of native libraries.
#[cfg(not(debug_assertions))]
fn bundled(app: &AppHandle) -> Option<PathBuf> {
    let name = if cfg!(windows) {
        "tilt-core/tilt-core.exe"
    } else {
        "tilt-core/tilt-core"
    };
    let path = app.path().resource_dir().ok()?.join(name);
    path.exists().then_some(path)
}

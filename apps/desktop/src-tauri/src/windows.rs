//! The windows, and the one script that tells the UI where the core is.
//!
//! Both windows are built at runtime rather than declared in `tauri.conf.json`.
//! That is not incidental: the address and token only exist once the core has
//! started, and a window created before then would have to be told afterwards —
//! which is a race the UI would lose by firing its first request into nothing.

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

use crate::sidecar::Core;

const MAIN: &str = "main";
const CAPTURE: &str = "capture";

/// Runs before the page loads, so the UI's first request already knows where to
/// go. The token never touches disk and never leaves this process pair.
fn bootstrap(core: &Core) -> String {
    let payload = serde_json::json!({
        "baseUrl": core.base_url,
        "token": core.token,
        "shell": "tauri",
    });
    format!("window.__TILT__ = {payload};")
}

fn failure(reason: &str) -> String {
    let payload = serde_json::json!({ "shell": "tauri", "error": reason });
    format!("window.__TILT__ = {payload};")
}

pub fn open_all(app: &AppHandle, core: &Core) -> tauri::Result<()> {
    let script = bootstrap(core);
    let main = build_main(app, &script)?;
    main.show()?;
    main.set_focus()?;

    // Built now and kept hidden: ⌥Space should feel instantaneous, and it will
    // not if the first press has to construct a webview.
    build_capture(app, &script)?;
    Ok(())
}

/// The core never came up. Open the journal window anyway so the reason is
/// visible in the UI instead of only in a log nobody is reading.
pub fn open_failed(app: &AppHandle, reason: &str) -> tauri::Result<()> {
    let main = build_main(app, &failure(reason))?;
    main.show()?;
    main.set_focus()?;
    Ok(())
}

fn build_main(app: &AppHandle, script: &str) -> tauri::Result<WebviewWindow> {
    let builder = WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App("index.html".into()))
        .title("Tilt")
        .inner_size(1080.0, 760.0)
        .min_inner_size(720.0, 520.0)
        .visible(false)
        .initialization_script(script);

    #[cfg(target_os = "macos")]
    let builder = builder
        // Content runs to the edge of the window; the traffic lights float over
        // it. The UI insets its sidebar to make room.
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);

    builder.build()
}

/// Small, floating, borderless. The one window that uses the system's own
/// material rather than the app's glass — at this size a real vibrant blur is
/// what makes it read as part of macOS instead of a web page on top of it.
fn build_capture(app: &AppHandle, script: &str) -> tauri::Result<WebviewWindow> {
    let builder = WebviewWindowBuilder::new(
        app,
        CAPTURE,
        WebviewUrl::App("index.html?capture=1".into()),
    )
    .title("Quick Capture")
    .inner_size(620.0, 168.0)
    .resizable(false)
    .decorations(false)
    .transparent(true)
    .always_on_top(true)
    .skip_taskbar(true)
    .center()
    .visible(false)
    .initialization_script(script);

    let window = builder.build()?;

    #[cfg(target_os = "macos")]
    {
        use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial, NSVisualEffectState};
        // `Active` keeps the blur lit even though the window gives up key focus
        // to nothing — a HUD that greys out the moment it appears looks broken.
        let _ = apply_vibrancy(
            &window,
            NSVisualEffectMaterial::HudWindow,
            Some(NSVisualEffectState::Active),
            Some(14.0),
        );
    }

    Ok(window)
}

/// Reached from the tray and, on macOS, from clicking the Dock icon — neither
/// of which exists on Linux, where the shell only ever runs for development.
#[cfg_attr(target_os = "linux", allow(dead_code))]
pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// Press to summon, press again to dismiss. The same key doing both is why the
/// hotkey never needs a second thought.
pub fn toggle_capture(app: &AppHandle) {
    let Some(window) = app.get_webview_window(CAPTURE) else {
        // The core has not finished starting. Ignoring the press is right:
        // there is nowhere to save a thought to yet.
        return;
    };

    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
        return;
    }
    let _ = window.center();
    let _ = window.show();
    let _ = window.set_focus();
}

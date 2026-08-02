// The release build is a windowed app; a console flashing up behind it on
// Windows would be the first thing anyone noticed.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;
mod windows;

use std::sync::Arc;

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

use sidecar::Core;

/// The two-second path, from anywhere. Not configurable yet — one hotkey that
/// always works beats a preference nobody sets.
fn capture_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::ALT), Code::Space)
}

/// Quit, because the journal underneath the window has gone.
///
/// Erasing and importing both stop the service on purpose: the next start has
/// to read a directory that is not the one this process opened. Until now the
/// window stayed up over nothing and the panel asked you to quit by hand.
///
/// A command of the app's own rather than the process plugin. The plugin would
/// be a dependency and a capability entry for one call, and a capability whose
/// identifier is wrong fails the build rather than the feature — on the one
/// platform that cannot be checked here. Commands declared in `invoke_handler`
/// need no ACL entry, and `app.exit` runs `ExitRequested` on the way out, which
/// is what stops the core.
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

fn main() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![quit_app])
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    // Fires on press and release; acting on both would toggle
                    // the window open and shut in one keystroke.
                    if event.state() == ShortcutState::Pressed && shortcut == &capture_shortcut() {
                        windows::toggle_capture(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            let handle = app.handle().clone();

            // Starting the core blocks: it waits for the port. Do it off the
            // main thread so the app is responsive, then come back to build the
            // windows with the address it reported.
            std::thread::spawn(move || {
                let core = match Core::start(&handle) {
                    Ok(core) => Arc::new(core),
                    Err(reason) => {
                        eprintln!("[shell] {reason}");
                        // Still open a window. A silent bounce in the Dock tells
                        // you nothing; the UI can at least name the failure.
                        let handle = handle.clone();
                        let _ = handle.clone().run_on_main_thread(move || {
                            if let Err(e) = windows::open_failed(&handle, &reason) {
                                eprintln!("[shell] could not open a window: {e}");
                            }
                        });
                        return;
                    }
                };

                handle.manage(core.clone());
                let _ = handle.clone().run_on_main_thread(move || {
                    if let Err(e) = windows::open_all(&handle, &core) {
                        eprintln!("[shell] could not open a window: {e}");
                    }
                    // Linux is left out on purpose. The tray there is built on
                    // libappindicator, which panics on the main thread rather
                    // than returning an error when the library is absent — and
                    // a missing menu bar item must not be able to take the app
                    // down with it. Tilt targets macOS; this is a dev platform.
                    #[cfg(not(target_os = "linux"))]
                    if let Err(e) = install_tray(&handle) {
                        eprintln!("[shell] could not install the tray: {e}");
                    }
                });
            });

            app.global_shortcut().register(capture_shortcut())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Closing a window is not quitting — the Mac convention, and the
                // one that keeps ⌥Space alive after you close the journal.
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to start Tilt");

    app.run(|handle, event| match event {
        // Clicking the Dock icon with no window showing should bring it back.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => windows::show_main(handle),
        RunEvent::ExitRequested { .. } | RunEvent::Exit => {
            if let Some(core) = handle.try_state::<Arc<Core>>() {
                core.shutdown();
            }
        }
        _ => {}
    });
}

#[cfg_attr(target_os = "linux", allow(dead_code))]
fn install_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open Tilt", true, None::<&str>)?;
    let capture = MenuItem::with_id(app, "capture", "Quick Capture", true, Some("Alt+Space"))?;
    let quit = MenuItem::with_id(app, "quit", "Quit Tilt", true, Some("CmdOrCtrl+Q"))?;
    let menu = Menu::with_items(
        app,
        &[&open, &capture, &PredefinedMenuItem::separator(app)?, &quit],
    )?;

    // Not the app icon: a menu bar mark is a template — one solid shape on
    // transparency that macOS recolours. The rounded square would render as a
    // black blob.
    let mark = tauri::image::Image::from_bytes(include_bytes!("../icons/tray@2x.png"))?;

    TrayIconBuilder::with_id("tilt")
        .icon(mark)
        .icon_as_template(true)
        .tooltip("Tilt")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => windows::show_main(app),
            "capture" => windows::toggle_capture(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

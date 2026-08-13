// B4/B5: platform detection (detect_form) + system tray + sidecar crash watchdog + sidecar self-healing.
// Related: docs/04-技术方案/tokeneff-B4-*.md and tokeneff-B5-*.md

use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Holds the sidecar child process handle (replaced on crash-watchdog restart).
/// Mutex<Option<>>: None = not started / exited, Some = running.
static SIDECAR_CHILD: Mutex<Option<CommandChild>> = Mutex::new(None);

/// Detect interaction form: Windows → ball (full floating ball), Linux Wayland → tray (tray fallback),
/// macOS / others → tray as fallback. Decided on the Rust side rather than frontend JS (env is unreliable inside the AppImage sandbox, M2).
#[tauri::command]
fn detect_form() -> String {
    let os = std::env::consts::OS;
    match os {
        "windows" => "ball".to_string(),
        "macos" => "tray".to_string(),
        "linux" => {
            let session = std::env::var("XDG_SESSION_TYPE").unwrap_or_default();
            match session.as_str() {
                "wayland" => "tray".to_string(),
                _ => "ball".to_string(),
            }
        }
        _ => "tray".to_string(),
    }
}

/// Start the sidecar via tauri-plugin-shell (the tokeneff-sidecar declared via externalBin).
/// Returns true on success. When the main process exits, Tauri tears down the child automatically.
fn spawn_sidecar(app: &tauri::AppHandle) -> bool {
    match app
        .shell()
        .sidecar("tokeneff-sidecar")
        .and_then(|cmd| cmd.spawn())
    {
        Ok((_rx, child)) => {
            if let Ok(mut guard) = SIDECAR_CHILD.lock() {
                // The old child (if any) is dropped directly; CommandChild drop does not kill,
                // but the old process has already exited by the time we get here (watchdog confirms down before restarting).
                *guard = Some(child);
            }
            true
        }
        Err(e) => {
            eprintln!("[tokeneff] sidecar spawn failed: {e}");
            false
        }
    }
}

/// Background-poll sidecar (7861) liveness; consecutive failures → notify frontend + auto-restart sidecar (B5 self-healing).
fn spawn_sidecar_watchdog(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        // sidecar startup takes time; wait 3s before probing
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
        let mut consecutive_fail = 0u32;
        loop {
            let ok = match reqwest::get("http://127.0.0.1:7861/api/health").await {
                Ok(resp) => resp.status().is_success(),
                Err(_) => false,
            };
            if ok {
                if consecutive_fail > 0 {
                    let _ = app.emit("sidecar-status", "up");
                }
                consecutive_fail = 0;
            } else {
                consecutive_fail += 1;
                if consecutive_fail == 1 {
                    let _ = app.emit("sidecar-status", "down");
                }
                // 2 consecutive failures → auto-restart sidecar (B5 self-healing, addresses the B4 TODO)
                if consecutive_fail >= 2 {
                    eprintln!("[tokeneff] sidecar unresponsive for {consecutive_fail} consecutive probes, attempting restart");
                    // Clear the old handle
                    if let Ok(mut guard) = SIDECAR_CHILD.lock() {
                        *guard = None;
                    }
                    // Wait for the port to be released before spawn
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    if spawn_sidecar(&app) {
                        let _ = app.emit("sidecar-status", "up");
                        consecutive_fail = 0;
                    }
                }
            }
            tokio::time::sleep(std::time::Duration::from_secs(10)).await;
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![detect_form])
        .setup(|app| {
            // ── Start sidecar (managed with the main process lifecycle) ────────────────────
            spawn_sidecar(app.handle());

            // ── System tray: show meter / settings / quit ───────────────────────────────
            let show = MenuItem::with_id(app, "show", "显示电表", true, None::<&str>)?;
            let settings = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &settings, &quit])?;

            TrayIconBuilder::with_id("main-tray")
                .tooltip("tokeneff 电表")
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(panel) = app.get_webview_window("panel") {
                            let _ = panel.show();
                            let _ = panel.set_focus();
                        }
                    }
                    "settings" => {
                        if let Some(s) = app.get_webview_window("settings") {
                            let _ = s.show();
                            let _ = s.set_focus();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // ── sidecar crash watchdog + self-healing ──────────────────────────────────────────
            spawn_sidecar_watchdog(app.handle().clone());

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

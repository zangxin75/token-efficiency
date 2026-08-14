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

/// Read the sidecar's ACTUAL port from ~/.tokeneff/sidecar.port (★ port-drift
/// fix: when 7861 is occupied the sidecar drifts to 7862+; hardcoded consumers
/// were permanently disconnected). Returns None when the file is missing or
/// unparseable — callers fall back to the default 7861 and probe liveness.
#[tauri::command]
fn get_sidecar_port() -> Option<u16> {
    let path = std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .map(|home| std::path::PathBuf::from(home).join(".tokeneff").join("sidecar.port"))
        .ok()?;
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| s.trim().parse::<u16>().ok())
}

/// Start the sidecar via tauri-plugin-shell (the tokeneff-sidecar declared via externalBin).
/// Returns true on success.
///
/// ★ review fix: the previous comment claimed "Tauri tears down the child automatically on
/// exit" — verified against tauri-plugin-shell 2.3.5 source this is FALSE for Rust-side
/// spawns: the plugin's exit cleanup (RunEvent::Exit → shell.children kill loop) only
/// tracks children spawned from JS via the `spawn` command; Command::spawn from Rust
/// never registers into it, and CommandChild has no Drop impl. Actual teardown is done
/// by our own RunEvent::Exit handler in run().
fn spawn_sidecar(app: &tauri::AppHandle) -> bool {
    let sidecar = app.shell().sidecar("tokeneff-sidecar");
    // ★ dev-build escape hatch for sidecar CORS: `tauri dev` still spawns the
    // PACKAGED sidecar exe (externalBin → PyInstaller frozen → sys.frozen=True),
    // so the sidecar's frozen-based CORS would reject the vite dev origin and the
    // dev ball stays grey. cfg!(debug_assertions) is true only in `tauri dev`
    // builds; release/NSIS builds never set it, keeping production CORS tight.
    let command = if cfg!(debug_assertions) {
        sidecar.map(|cmd| cmd.env("SIDECAR_DEV", "1"))
    } else {
        sidecar
    };
    match command.and_then(|cmd| cmd.spawn())
    {
        Ok((_rx, child)) => {
            if let Ok(mut guard) = SIDECAR_CHILD.lock() {
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

/// Kill the tracked sidecar child (if any). Called on exit and before watchdog restarts.
fn kill_sidecar() {
    if let Ok(mut guard) = SIDECAR_CHILD.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }
}

/// Background-poll sidecar (7861) liveness; consecutive failures → notify frontend + auto-restart sidecar (B5 self-healing).
///
/// ★ review fixes:
/// - probe requests carry a 2s timeout (reqwest defaults to NO total timeout — a hung
///   sidecar accepting connections but never replying would freeze the watchdog itself,
///   exactly when it is needed most);
/// - restart is bounded (MAX_RESTARTS) with exponential backoff, instead of an
///   unbounded respawn loop leaking a ~40MB PyInstaller process every ~25s;
/// - the old child is explicitly killed before respawning (probe failure ≠ process
///   death — a zombie sidecar can hold port 7861, making every restart drift ports).
fn spawn_sidecar_watchdog(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        const MAX_RESTARTS: u32 = 5;
        let client = match reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(2))
            .build()
        {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[tokeneff] watchdog http client build failed: {e}");
                return;
            }
        };
        // sidecar startup takes time; wait 3s before probing
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
        let mut consecutive_fail = 0u32;
        let mut restarts = 0u32;
        loop {
            // ★ port-drift fix: probe the sidecar's ACTUAL port (read fresh each
            // cycle — a restart may have landed on a different port); fall back
            // to the default when the port file is missing/stale.
            let port = get_sidecar_port().unwrap_or(7861);
            let ok = match client
                .get(format!("http://127.0.0.1:{port}/api/health"))
                .send()
                .await
            {
                Ok(resp) => resp.status().is_success(),
                Err(_) => false,
            };
            if ok {
                if consecutive_fail > 0 {
                    let _ = app.emit("sidecar-status", "up");
                }
                consecutive_fail = 0;
                restarts = 0; // healthy again → allow fresh restart budget
            } else {
                consecutive_fail += 1;
                if consecutive_fail == 1 {
                    let _ = app.emit("sidecar-status", "down");
                }
                // 2 consecutive failures → auto-restart sidecar (B5 self-healing)
                if consecutive_fail >= 2 {
                    if restarts >= MAX_RESTARTS {
                        eprintln!("[tokeneff] sidecar restart budget exhausted ({MAX_RESTARTS}); giving up — check ~/.tokeneff or kill stale tokeneff-sidecar processes");
                        // ★ review fix: "down" is a transient state the ball treats as
                        // "reconnecting"; a terminal give-up needs its own signal so the
                        // UI can tell the user self-healing stopped (stderr alone is invisible)
                        let _ = app.emit("sidecar-status", "given-up");
                        consecutive_fail = 0; // stop re-triggering this branch every probe
                    } else {
                        eprintln!("[tokeneff] sidecar unresponsive for {consecutive_fail} consecutive probes, attempting restart {}/{}", restarts + 1, MAX_RESTARTS);
                        // Probe failure ≠ process death: kill the old child so it
                        // releases port 7861 before the respawn (prevents port drift)
                        kill_sidecar();
                        // Exponential backoff: 2s, 4s, 8s, 16s, 32s — also covers the
                        // port-release window and slow PyInstaller onefile startup
                        let wait = 2u64 << restarts;
                        tokio::time::sleep(std::time::Duration::from_secs(wait)).await;
                        if spawn_sidecar(&app) {
                            restarts += 1;
                            consecutive_fail = 0;
                            // emit "up" only after a probe confirms it, not on spawn success
                            // (onefile extraction takes seconds; premature "up" flickers the ball)
                        } else {
                            restarts += 1;
                        }
                    }
                }
            }
            tokio::time::sleep(std::time::Duration::from_secs(10)).await;
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // ★ Settings 开机自启开关：NSIS 装后写的 HKCU Run 键与此插件操作同一注册表
    // 值（tauri-plugin-autostart Windows 实现也是 HKCU Run），插件 isEnabled 能
    // 读到安装器写入的状态，双轨不会打架
    let autostart = tauri_plugin_autostart::MacosLauncher::LaunchAgent;
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(
            autostart,
            Some(vec!["--hidden"]),
        ))
        .invoke_handler(tauri::generate_handler![detect_form, get_sidecar_port])
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
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // ★ review fix: Rust-side spawned children are NOT tracked by the shell
            // plugin's own exit cleanup (verified against tauri-plugin-shell 2.3.5),
            // so we must kill the sidecar ourselves on exit — otherwise every tray
            // quit leaks a ~40MB orphan holding port 7861 (compounded by the HKCU
            // Run autostart re-spawning the main app each login).
            if let tauri::RunEvent::Exit = event {
                kill_sidecar();
            }
            let _ = app;
        });
}

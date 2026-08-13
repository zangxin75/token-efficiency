// B4/B5：平台检测（detect_form）+ 系统托盘 + sidecar 崩溃守护 + sidecar 自愈。
// 关联 docs/04-技术方案/tokeneff-B4-*.md 与 tokeneff-B5-*.md

use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// 持有 sidecar 子进程句柄（崩溃守护重启时替换）。
/// Mutex<Option<>>：None=未启动/已退出，Some=运行中。
static SIDECAR_CHILD: Mutex<Option<CommandChild>> = Mutex::new(None);

/// 探测交互形态：Windows→ball（完整悬浮球），Linux Wayland→tray（托盘降级），
/// macOS / 其他→tray 保底。在 Rust 侧判定而非前端 JS（AppImage 沙箱内 env 不可靠，M2）。
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

/// 用 tauri-plugin-shell 启动 sidecar（externalBin 声明的 tokeneff-sidecar）。
/// 成功返回 true。主程序退出时 Tauri 自动收尾子进程。
fn spawn_sidecar(app: &tauri::AppHandle) -> bool {
    match app
        .shell()
        .sidecar("tokeneff-sidecar")
        .and_then(|cmd| cmd.spawn())
    {
        Ok((_rx, child)) => {
            if let Ok(mut guard) = SIDECAR_CHILD.lock() {
                // 旧 child（若有）直接丢弃，CommandChild drop 不会 kill，
                // 但旧进程已退出才走到这（watchdog 确认 down 后才重启）。
                *guard = Some(child);
            }
            true
        }
        Err(e) => {
            eprintln!("[tokeneff] sidecar spawn 失败: {e}");
            false
        }
    }
}

/// 后台轮询 sidecar（7861）存活，连续失败 → 通知前端 + 自动重启 sidecar（B5 自愈）。
fn spawn_sidecar_watchdog(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        // sidecar 启动需要时间，先等 3s 再开始探测
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
                // 连续 2 次失败 → 自动重启 sidecar（B5 自愈，补 B4 的 TODO）
                if consecutive_fail >= 2 {
                    eprintln!("[tokeneff] sidecar 连续 {consecutive_fail} 次无响应，尝试重启");
                    // 清旧句柄
                    if let Ok(mut guard) = SIDECAR_CHILD.lock() {
                        *guard = None;
                    }
                    // 等待端口释放后再 spawn
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
            // ── 启动 sidecar（随主程序生命周期管理）─────────────────────────────
            spawn_sidecar(app.handle());

            // ── 系统托盘：显示电表 / 设置 / 退出 ───────────────────────────────
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

            // ── sidecar 崩溃守护 + 自愈 ──────────────────────────────────────────
            spawn_sidecar_watchdog(app.handle().clone());

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

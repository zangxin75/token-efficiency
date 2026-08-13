// B4：平台检测（detect_form）+ 系统托盘（TrayIconBuilder）+ sidecar 崩溃守护。
// 关联 docs/04-技术方案/tokeneff-B4-平台检测托盘降级-Windows执行指令.md

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};

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

/// 后台轮询 sidecar（7861）存活，连续失败则通知前端进入"连接中"态。
/// 注意：本地开发时 sidecar 是手动启动的 Python 进程，无打包 exe 路径，
/// 故此处不自动重启（仅探测 + 通知）；打包后再补 Command::spawn 重启。
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
                    // 恢复上线
                    let _ = app.emit("sidecar-status", "up");
                }
                consecutive_fail = 0;
            } else {
                consecutive_fail += 1;
                if consecutive_fail == 1 {
                    // 首次失败即通知前端显示"连接中"
                    let _ = app.emit("sidecar-status", "down");
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
        .invoke_handler(tauri::generate_handler![detect_form])
        .setup(|app| {
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

            // ── sidecar 崩溃守护 ──────────────────────────────────────────────
            spawn_sidecar_watchdog(app.handle().clone());

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

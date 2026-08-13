# tokeneff B4 执行指令（Windows Claude Code 用）

> 本文件供 Windows 上的 Claude Code 执行。目标：Rust 平台检测 + Wayland 托盘降级 + sidecar 崩溃守护。

---

【任务】B4 阶段：跨平台适配 + 健壮性。

三个子任务：
1. **平台检测**（detect_form）：启动时探测交互形态（ball/tray），Rust 侧实现
2. **Wayland 托盘降级**：Linux Wayland 下自动走托盘形态（Windows 不受影响，但要保证 Windows 下托盘也能用）
3. **sidecar 崩溃守护**（M5 前端侧）：检测 sidecar 崩溃 → SIGTERM 优雅退出 + 自动重启 + 前端显示"连接中"

**关键约束**：
- detect_form 在 Rust 侧做（M2 修订），不在前端 JS（AppImage 沙箱内 env 不可靠）
- Windows 上 detect_form 应返回 "ball"（完整悬浮球）
- macOS 走 "tray" 保底（本方案不做 macOS，但别崩）
- 前端已就绪：能渲染 ball 和 panel（B2 实现）

**已就绪的后端支持**：
- sidecar 已有 30s 定时 flush（M5，Linux 侧 49dd5a4）
- `/api/health` 端点可做存活探测

---

## 步骤

### 1. 拉最新代码

```powershell
cd <token-efficiency-main>
git pull origin main
```

### 2. 实现 detect_form 命令（Rust 侧，src-tauri/src/main.rs 或 lib.rs）

新增 Tauri command，启动时探测一次交互形态：

```rust
use tauri::command;

#[command]
fn detect_form() -> String {
    // 1. 平台判定
    let os = std::env::consts::OS;
    match os {
        "windows" => "ball".to_string(),      // Windows：完整悬浮球
        "macos" => "tray".to_string(),          // macOS：保底托盘（本方案不适配）
        "linux" => {
            // 2. Linux 下判定 X11 vs Wayland
            let session = std::env::var("XDG_SESSION_TYPE").unwrap_or_default();
            match session.as_str() {
                "wayland" => {
                    // 3. ★ M2 兜底：env 可能不可靠（AppImage 沙箱），
                    //    尝试创建透明置顶窗口，失败则降级 tray
                    //    简化版：先信任 env，后续可加 try-create 透明窗口探测
                    "tray".to_string()
                }
                _ => "ball".to_string(),        // x11 或未知 → 悬浮球
            }
        }
        _ => "tray".to_string(),                // 其他平台保底
    }
}
```

注册命令：
```rust
fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![detect_form])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

### 3. 前端消费 detect_form 结果（platform.ts）

```typescript
// src/platform.ts
import { invoke } from '@tauri-apps/api/core'

export type Form = 'ball' | 'tray'

export async function detectForm(): Promise<Form> {
  try {
    return await invoke<string>('detect_form') as Form
  } catch {
    return 'ball'  // 默认悬浮球（Windows 主场景）
  }
}
```

在 App.vue 启动时调用 detectForm，根据结果决定：
- `ball` → 显示悬浮球窗口（现有逻辑）
- `tray` → 不显示悬浮球窗口，依赖系统托盘交互

### 4. 系统托盘实现（tray 降级 + Windows 也能用）

Tauri 2 内置 tray 功能（src-tauri/src/main.rs）：

```rust
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
};

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![detect_form])
        .setup(|app| {
            // 创建托盘菜单：显示电表 / 设置 / 退出
            let show = MenuItem::with_id(app, "show", "显示电表", true, None::<&str>)?;
            let settings = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &settings, &quit])?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        // 显示 panel 窗口
                        if let Some(panel) = app.get_webview_window("panel") {
                            let _ = panel.show();
                            let _ = panel.set_focus();
                        }
                    }
                    "settings" => {
                        if let Some(panel) = app.get_webview_window("panel") {
                            let _ = panel.show();
                            // 切换到设置标签页（前端监听路由/事件）
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

注意 Linux Wayland 托盘的已知限制（Tauri 官方）：左键点击事件 Linux 不支持，只有右键菜单。所以 tray 形态靠**右键菜单**触发，不要依赖左键点击。

### 5. sidecar 崩溃守护（M5 前端侧）

在 Rust 侧加 sidecar 健康轮询 + 自动重启。新增命令：

```rust
#[command]
async fn sidecar_health() -> bool {
    // 轮询 http://127.0.0.1:7861/api/health
    // 用 reqwest 或简单 TCP 连接探测端口
    // 返回 true=存活 / false=崩溃
    // 实现用 reqwest::get("http://127.0.0.1:7861/api/health").await.is_ok()
    todo!()  // Claude 实现细节
}
```

加上 Rust 后台任务：每 10s 轮询 sidecar_health，失败 → 自动重启 sidecar 进程（`Command::new(sidecar_path).spawn()`）。

前端则通过 invoke('sidecar_health') 或监听 Rust 事件，显示"连接中"态（悬浮球变灰 + 旋转图标）。

### 6. Windows 本地测试

```powershell
cd desktop
npm run tauri dev
```

**验证点**：
1. detect_form 返回 "ball"（Windows 默认悬浮球）
2. 悬浮球正常显示
3. **托盘可用**：任务栏右下角有 tokeneff 图标，右键出菜单（显示电表/设置/退出）
4. 退出菜单项能真正退出
5. sidecar 崩溃守护：手动 kill sidecar 进程 → Rust 自动重启 → 悬浮球恢复显示

### 7. Linux 测试（如果有 Linux 环境，可选）

在 Linux（X11 或 Wayland）验证：
- X11：detect_form 返回 "ball"，悬浮球可用
- Wayland：detect_form 返回 "tray"，悬浮球不显示，靠托盘右键菜单

若没有 Linux 环境，跳过，Windows 验证通过即可。

---

## 记录验证结果

【验证1 - detect_form】Windows 下返回 "ball"，悬浮球正常显示。✅/❌
【验证2 - 系统托盘】任务栏有托盘图标，右键菜单功能正常（显示电表/设置/退出）。✅/❌
【验证3 - 退出】托盘菜单"退出"能真正退出程序（含 sidecar）。✅/❌
【验证4 - 崩溃守护】手动 kill sidecar → Rust 自动重启 → 悬浮球恢复。✅/❌
【验证5 - Linux 降级】（若有 Linux）Wayland 走 tray 形态。✅/❌/跳过

---

## 提交

```powershell
git add desktop/src-tauri/ desktop/src/
git commit -m "feat(desktop): B4 平台检测 + 托盘降级 + 崩溃守护

- detect_form 命令 (Rust): 探测 ball/tray 形态 (M2, Win→ball/Linux Wayland→tray)
- 系统托盘: 右键菜单 (显示电表/设置/退出), Wayland 降级依赖
- sidecar 崩溃守护 (M5): 轮询 /api/health + 自动重启 + 前端连接中态
- 配合 sidecar 30s 定时 flush (Linux 侧 49dd5a4) 防崩溃丢数据"
git push
```

---

## 完成后

把 5 个验证结果告诉我。重点是验证 2（托盘）和验证 4（崩溃守护）——这是健壮性的关键。

【可能的问题】
- TrayIconBuilder 报缺 icon → 用 app.default_window_icon() 或放一个 icon 文件到 src-tauri/icons/
- detect_form 在 Windows 不返回 "ball" → 检查 std::env::consts::OS 在 Windows 的值（应为 "windows"）
- reqwest 加依赖：cargo add reqwest --features json（用于 sidecar_health）
- Wayland 测不了：无 Linux 环境可跳过，Windows 验证通过即可

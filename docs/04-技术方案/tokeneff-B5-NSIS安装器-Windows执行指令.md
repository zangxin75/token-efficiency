# tokeneff B5 执行指令（Windows Claude Code 用）

> 本文件供 Windows 上的 Claude Code 执行。目标：NSIS 安装器，产出可分发的 .exe 安装包。

---

【任务】B5 阶段：NSIS 安装器 + sidecar 集成 + WebView2 自动安装 + 开机自启。

**核心目标**：用户下载一个 `tokeneff-setup.exe`，双击一路下一步就装好——悬浮球自动启动，零环境配置。

**最终交付物**：`desktop/src-tauri/target/release/bundle/nsis/tokeneff_0.1.0_x64-setup.exe`

**关键约束**：
- sidecar exe 要作为 externalBin 打进安装包（用户不单独装 Python）
- WebView2 缺失时自动安装（downloadBootstrapper 模式）
- 开机自启（可选，默认开）
- 卸载干净（删程序 + 自启项 + 提示删数据）

---

## 步骤

### 1. 拉最新代码

```powershell
cd <token-efficiency-main>
git pull origin main
```

### 2. 打包 sidecar exe（PyInstaller，已验证的脚本）

```powershell
# 确保 sidecar exe 是最新代码打的
bash packaging/build-sidecar.sh
# 若无 bash，手动：
.venv\Scripts\python -m PyInstaller --onefile --name tokeneff-sidecar --additional-hooks-dir packaging/hooks --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-submodules tokeneff --distpath dist --noconfirm packaging/sidecar_entry.py
```

产物：`dist/tokeneff-sidecar.exe`（约 46MB，含 keyring hook）

### 3. 把 sidecar 重命名为 Tauri 要求的格式

Tauri externalBin 要求二进制命名 `<name>-<target-triple>.exe`，target-triple 用 `rustc --print host-tuple` 获取（Windows 一般是 `x86_64-pc-windows-msvc`）。

```powershell
# 获取 target triple
$triple = rustc --print host-tuple
# 建目录放 sidecar
mkdir desktop\src-tauri\binaries -Force
# 复制并重命名
copy dist\tokeneff-sidecar.exe "desktop\src-tauri\binaries\tokeneff-sidecar-$triple.exe"
# 确认
dir desktop\src-tauri\binaries\
```

### 4. 配置 tauri.conf.json 集成 sidecar + NSIS + WebView2

编辑 `desktop/src-tauri/tauri.conf.json`，在 `bundle` 对象里加：

```jsonc
{
  "bundle": {
    "active": true,
    "targets": ["nsis"],
    "icon": ["icons/icon.ico"],
    "externalBin": ["binaries/tokeneff-sidecar"],
    "windows": {
      "webviewInstallMode": {
        "type": "downloadBootstrapper"
      },
      "nsis": {
        "installerHooks": "./windows/hooks.nsh"
      }
    },
    "resources": []
  }
}
```

关键点：
- `externalBin`：声明 sidecar（不带 target-triple 后缀，Tauri 会自动找 `binaries/tokeneff-sidecar-<triple>.exe`）
- `webviewInstallMode: downloadBootstrapper`：检测到系统无 WebView2 → 下载官方 bootstrapper 静默装（Win11/Win10 自带则跳过）
- `nsis.installerHooks`：自定义安装/卸载钩子（开机自启等）

### 5. 写 NSIS hooks（开机自启 + 卸载逻辑）

创建 `desktop/src-tauri/windows/hooks.nsh`：

```nsis
!macro NSIS_HOOK_PREINSTALL
  ; 安装前：无特殊操作
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; ★ 安装后：注册开机自启（写注册表 Run 键）
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tokeneff" "$INSTDIR\tokeneff.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; ★ 卸载前：清理开机自启
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tokeneff"
  ; kill 残留进程（悬浮球 + sidecar）
  nsExec::Taskkill /IM "tokeneff.exe" /F
  nsExec::Taskkill /IM "tokeneff-sidecar.exe" /F
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; 卸载后：提示是否删本地数据（~/.tokeneff）
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除 tokeneff 本地数据（用量历史、配置）？" IDNO skip_data
    RMDir /r "$PROFILE\.tokeneff"
  skip_data:
!macroend
```

### 6. 让 Rust 启动 sidecar（改用 Tauri sidecar API）

之前 B4 的崩溃守护是用 `Command::new` 启动独立 exe，现在改为 Tauri 的 sidecar API（随主程序生命周期管理）。

加依赖：
```powershell
cd desktop
npm run tauri add shell
# 或手动 cargo add tauri-plugin-shell
```

在 `src-tauri/src/main.rs` 启动 sidecar：
```rust
use tauri_plugin_shell::ShellExt;

// 在 setup 里启动 sidecar
.setup(|app| {
    // 启动 sidecar（externalBin 声明的 tokeneff-sidecar）
    let sidecar = app.shell().sidecar("tokeneff-sidecar").unwrap();
    let _child = sidecar.spawn().expect("failed to start sidecar");
    // 注意：保存 _child 以便退出时 kill（或靠 Tauri 自动管理）
    Ok(())
})
```

> 注：崩溃守护（B4 已实现）继续保留，detect sidecar 崩溃后用 sidecar API 重新 spawn。

### 7. 设置图标

确保 `desktop/src-tauri/icons/icon.ico` 存在（NSIS 安装器需要）。若无，用 Tauri 默认图标先生成：
```powershell
npm run tauri icon path/to/your-logo.png
# 或用默认：把任意 256x256 png 转成 ico 放进去
```

### 8. 构建安装包

```powershell
cd desktop
npm run tauri build
```

首次构建较慢（Rust release 编译 + NSIS 打包）。产物路径：
```
desktop\src-tauri\target\release\bundle\nsis\tokeneff_0.1.0_x64-setup.exe
```
大小预计 50-60MB（含 sidecar 46MB + 悬浮球 + WebView2 引导）。

### 9. 端到端验证（关键！在干净的 Windows 上测）

**找一台没装过 tokeneff 的 Windows 机器**（或先卸载干净），双击 `tokeneff_0.1.0_x64-setup.exe`：

【验证1 - 安装】双击 → 一路下一步 → 安装成功，无报错。✅/❌
【验证2 - 自动启动】安装完成自动启动悬浮球（桌面出现悬浮球）。✅/❌
【验证3 - 首次引导】悬浮球自动弹 onboarding（选 provider → 贴 key → 验证 → 指向代理）。✅/❌
【验证4 - 开机自启】重启 Windows → 悬浮球自动出现（检查注册表 Run 键已写）。✅/❌
【验证5 - WebView2】若测试机无 WebView2，安装时自动下载安装（不弹窗让用户自己装）。✅/❌/跳过(已有)
【验证6 - 卸载】控制面板卸载 → 弹"是否删数据" → 程序 + 自启项 + 数据都清理干净。✅/❌

### 10. 提交

```powershell
git add desktop/src-tauri/tauri.conf.json desktop/src-tauri/windows/ desktop/src-tauri/src/
git commit -m "feat(desktop): B5 NSIS 安装器 + sidecar 集成 + WebView2 自装

- externalBin: sidecar exe 打进安装包（用户免装 Python）
- WebView2 downloadBootstrapper: 缺失自动静默安装
- NSIS hooks: 开机自启 + 卸载清理（自启项/进程/数据询问）
- tauri-plugin-shell: sidecar 随主程序生命周期管理
- 产物: tokeneff_0.1.0_x64-setup.exe (~55MB, 零配置)"
git push
```

> 注意：`desktop/src-tauri/binaries/*.exe`（sidecar 二进制，46MB）和 `target/` 不提交，加 .gitignore。

---

## 完成后

把 6 个验证结果告诉我，重点是：
- 验证1-2：安装能成、自动启动
- 验证4：开机自启（用户最常问的"重启还在不在"）
- 验证6：卸载干净（不留垃圾）

**这是整个桌面版的最终交付**——产出 `tokeneff-setup.exe`，用户双击即用。

【可能的问题】
- NSIS 构建报缺 makensis → Tauri 会自动下载 NSIS 工具，确保联网
- sidecar 找不到 → 检查 `binaries/tokeneff-sidecar-<triple>.exe` 命名是否正确（triple 用 rustc --print host-tuple）
- 安装后悬浮球不启动 → 检查 tauri-plugin-shell 的 sidecar spawn 是否报错
- 杀软拦截安装包 → NSIS 安装器可能被误报，需数字签名（后续可加，B5 先不签名）
- icon 缺失 → 先用任意 ico 占位

【关于代码签名】
B5 先不做代码签名（需要购买证书）。未签名的安装包首次运行 Windows 会弹 SmartScreen 警告，用户需点"仍要运行"。这是开源软件常态，README 里说明即可。后续用户量起来再买证书签名。

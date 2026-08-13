# tokeneff B3 执行指令（Windows Claude Code 用）

> 本文件供 Windows 上的 Claude Code 执行。目标：设置窗口 + 首次启动 onboarding，提升转化率（M3）。

---

【任务】B3 阶段：设置窗口 + 首次启动 onboarding。

**核心目标**：悬浮球首次启动时，引导用户完成关键配置（选 provider → 贴 key → 验证 → 指向代理），确保用户真正用起来而非流失。

**关键约束**：
- 技术栈：Vue 3 + TypeScript（已在 desktop/）
- sidecar 新端点已就绪：
  - `GET /api/providers` — 可用 provider 列表
  - `POST /api/config/verify` — 验证 key 有效性
  - `POST /api/config/key` — 存 key 到 keyring
  - `GET /api/config` / `POST /api/config` — 读写配置
- 转化率关键：onboarding 必须闭环到「第一次计费成功」

---

## 步骤

### 1. 拉取最新代码

```powershell
cd <token-efficiency-main>
git pull origin main
```

确保拉取到最新的 sidecar B3 端点（providers/verify）。

### 2. 设计设置窗口 UI（Vue 组件）

在 `desktop/src/` 下创建 `Settings.vue`，包含：

**标签页结构**：
- **Provider** — 选择/编辑 API key
  - 下拉选 provider（从 `GET /api/providers` 拉列表）
  - 输入 key + 「验证」按钮（调用 `POST /api/config/verify`）
  - 验证成功 → 存 key（`POST /api/config/key`）
  - 显示已配置的 provider 列表 + 可删除
- **预算** — 月度预算 + 告警阈值
  - 输入预算金额（CNY/USD 自动换算）
  - 告警阈值滑块（默认 80%）
- **区域** — CN / Global 切换（影响币种）
- **启动** — 开机自启开关

**UI 风格**：
- 右侧滑出面板或独立窗口
- 现代化深色主题，与悬浮球一致
- 每个标签页底部「保存」按钮

### 3. 实现 onboarding 首次启动引导

**触发条件**：用户首次启动（检测 `GET /api/config` 返回 `providers_configured` 为空）。

**引导流程**（参考方案 §6.5）：

```
Step 1: 选择 Provider
  - 显示 provider 下拉（从 /api/providers 拉）
  - 用户选一个

Step 2: 粘贴 API Key
  - 输入框 + 粘贴按钮
  - 点击「验证」→ POST /api/config/verify
  - 成功 → 进入下一步；失败 → 提示错误，重试

Step 3: 引导指向代理
  - 显示「代理地址：127.0.0.1:7860」
  - 一键复制按钮
  - 展示客户端配置示例（curl / Python / Claude Code）
  - 示例：curl -x http://127.0.0.1:7860 ...

Step 4: 完成
  - 提示「配置完成，首次计费后悬浮球会显示花费」
  - 关闭 onboarding，之后可在设置里改
```

**实现方式**：
- 在 `App.vue` 或单独 `Onboarding.vue` 组件
- 检测 `providers_configured` 是否为空 → 决定是否显示
- 用 Vue Router 或 Modal 方式呈现

### 4. 前后端联调

确保设置窗口能正确调用 sidecar 端点：

```javascript
// 获取 provider 列表
const { data: { providers } } = await axios.get('http://127.0.0.1:7861/api/providers')

// 验证 key（关键：验证后才存）
const verifyRes = await axios.post('http://127.0.0.1:7861/api/config/verify', {
  provider: 'glm',
  key: 'sk-xxx'
})
// verifyRes.data = { ok: true/false, message: '...' }

// 存 key
await axios.post('http://127.0.0.1:7861/api/config/key', {
  provider: 'glm',
  key: 'sk-xxx'
})

// 读取当前配置
const configRes = await axios.get('http://127.0.0.1:7861/api/config')
// configRes.data = { mode, region, currency, budget_monthly_usd, alert_threshold, providers_configured: [...] }
```

### 5. 本地测试

启动 sidecar + 悬浮球：
```powershell
# 先启动 sidecar（确保是新版本有 verify/providers 端点）
Start-Process -FilePath "..\dist\tokeneff-sidecar.exe"

# 启动 Tauri
cd desktop
npm run tauri dev
```

**验证点**：
1. 首次启动 → 自动弹出 onboarding 引导
2. 选 provider → 贴 key → 验证 → 成功提示
3. 完成后悬浮球显示今日花费（即使 0）
4. 设置窗口能修改预算/告警阈值/区域
5. 重启后设置持久化（存在 config.toml）

### 6. 验证转化率关键路径

**必须闭环**：onboarding 完成 → 用户实际发请求 → 悬浮球显示花费

测试方式：
- onboarding 完成后，在 onboarding 界面或设置里提供一个「测试请求」按钮
- 点击后调用一个简单 LLM 请求（如 "hi"）
- 请求经过 sidecar 代理（7860 端口）
- 成功后悬浮球应立即更新显示花费

---

## 记录验证结果

【验证1 - 首次启动 onboarding】首次启动时自动弹出引导流程。✅/❌
【验证2 - key 验证】输入无效 key → 提示错误；输入有效 key → 验证成功，可存。✅/❌
【验证3 - 代理引导】显示代理地址 127.0.0.1:7860，提供一键复制。✅/❌
【验证4 - 设置窗口】设置窗口能修改预算/告警/区域，保存后重启不丢失。✅/❌
【验证5 - 转化闭环】onboarding 完成后，能通过测试请求让悬浮球显示非 0 花费。✅/❌

---

## 提交

```powershell
git add desktop/src/
git commit -m "feat(desktop): B3 设置窗口 + 首次启动 onboarding

- Settings.vue: provider/key 管理、预算、告警阈值、区域、开机自启
- Onboarding.vue: 首次启动引导（选 provider → 贴 key → 验证 → 指向代理）
- 连接 sidecar /api/providers, /api/config/verify, /api/config/key 端点
- 转化闭环：测试请求后悬浮球显示花费"
git push
```

---

## 完成后

把 5 个验证结果告诉我，重点是验证 2（key 验证）和验证 5（转化闭环）。

【可能遇到的问题】
- CORS 报错：确认 sidecar 是最新版本（有 /api/config/verify 端点）
- key 验证失败但 key 有效：可能是 provider 的 verify_endpoint 不对，检查 byok_router 的 PROVIDER_REGISTRY
- onboarding 弹不出：检查 config.providers_configured 是否真的为空

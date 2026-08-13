# tokeneff B2 执行指令（Windows Claude Code 用）

> 本文件供 Windows 上的 Claude Code 执行。目标：搭建 Tauri 悬浮球骨架，连接已验证的 Python sidecar，在 Windows 上跑通"悬浮球显示电表数据"的完整闭环。

---

【任务】B2 阶段：Tauri 悬浮球骨架 + 展开面板，连接已验证的 Python sidecar（7861 端口），在 Windows 上实现"悬浮球实时显示电表"。

【前置条件】
- tokeneff sidecar 已能在 Windows 打包运行（B0 已验证通过）
- Python 已装（sidecar 用，已具备）

【关键约束】
- 技术栈：Tauri 2 + Vue 3 + TypeScript
- 悬浮球连 http://127.0.0.1:7861/api（sidecar 只读 API，已验证）
- 悬浮球要：透明无边框 + 置顶 + 可拖拽 + 点击展开
- 先不做设置窗口/onboarding（那是 B3），本阶段只要悬浮球能显示真实电表数据

---

## 步骤

### 1. 安装 Rust + Node 环境（Tauri 依赖）

检测是否已装：
```powershell
rustc --version
node --version
npm --version
```

- 若 rustc 报错 → 装 Rust：浏览器开 https://rustup.rs/ 下 rustup-init.exe 运行，全程默认（会装 MSVC 工具链）。装完关掉重开 PowerShell 让 PATH 生效。
- 若 node/npm 报错 → 装 Node.js LTS：https://nodejs.org/ 下 LTS 版安装包，默认选项。
- Tauri 还需 Visual Studio C++ 构建工具：大多数 Windows 开发机已有；若 cargo build 报缺 MSVC，装 "Visual Studio Build Tools"（勾选 "Desktop development with C++"）。

装完三个（rustc/node/npm）都确认能输出版本号再继续。

### 2. 创建 Tauri 项目（放在 tokeneff 仓库同级或内部都行）

在 token-efficiency-main 目录内创建一个 desktop 子目录放 Tauri 项目：
```powershell
cd <你的 token-efficiency-main 目录>
npm create tauri-app@latest
```
交互式回答：
- Project name: `desktop`
- Identifier: `com.tokeneff.app`
- Choose which language: `TypeScript / JavaScript`
- Package manager: `npm`
- UI template: `Vue`
- UI flavor: `TypeScript`

这会生成 desktop/ 目录，内含 Vue 前端 + src-tauri/ Rust 壳。

### 3. 进入 desktop 目录，确认能跑起来

```powershell
cd desktop
npm install
npm run tauri dev
```
首次会编译 Rust（较慢，几分钟），成功后会弹出一个默认窗口。能弹出就说明 Tauri 环境通了，关掉它继续。

### 4. 改造为悬浮球窗口

编辑 `desktop/src-tauri/tauri.conf.json`，把主窗口改成悬浮球配置。关键配置（参考 Tauri 2 语法）：
```jsonc
{
  "productName": "tokeneff",
  "app": {
    "windows": [
      {
        "label": "ball",
        "title": "tokeneff",
        "width": 90,
        "height": 90,
        "decorations": false,
        "transparent": true,
        "alwaysOnTop": true,
        "skipTaskbar": true,
        "resizable": false,
        "center": false,
        "x": 100,
        "y": 100,
        "shadow": false
      },
      {
        "label": "panel",
        "title": "tokeneff 电表",
        "width": 320,
        "height": 420,
        "decorations": false,
        "transparent": true,
        "alwaysOnTop": true,
        "skipTaskbar": true,
        "resizable": false,
        "visible": false
      }
    ]
  }
}
```
- `ball` 窗口：90x90 圆形悬浮球，默认可见
- `panel` 窗口：展开面板，默认隐藏（visible:false），点悬浮球时显示

### 5. 安装前端依赖

```powershell
cd desktop
npm install @tauri-apps/api axios
```

### 6. 实现悬浮球 UI（Vue 组件）

改 `desktop/src/App.vue` 为悬浮球组件。要求：
- 一个圆形 div（90x90），渐变背景，CSS 阴影，圆角 50%
- 显示：今日花费（大字）+ ¥/min 速率（小字）
- 颜色逻辑：budget_pct 为 null 或 <60 → 绿色；60-80 → 黄色；≥80 → 红色
- 拖拽：用 Tauri 的 `getCurrentWindow().startDragging()` 实现拖动（mousedown 触发）
- 点击展开：click 时调用 `WebviewWindow.getByLabel('panel').show()`，并定位到悬浮球旁边

示例结构（Claude 自己实现细节）：
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getCurrentWindow, WebviewWindow } from '@tauri-apps/api/window'
import axios from 'axios'

const API = 'http://127.0.0.1:7861'
const today = ref(0)
const rate = ref(0)
const budgetPct = ref<number | null>(null)
const currency = ref('USD')

async function refresh() {
  try {
    const { data } = await axios.get(`${API}/api/meter/summary`)
    today.value = data.today
    rate.value = data.rate_per_min
    budgetPct.value = data.budget_pct
    currency.value = data.currency
  } catch (e) { /* sidecar 没起，显示连接中态 */ }
}
onMounted(() => { refresh(); setInterval(refresh, 1000) })

function ballColor() {
  if (budgetPct.value === null) return '#22c55e'  // 未设预算，绿
  if (budgetPct.value >= 80) return '#ef4444'
  if (budgetPct.value >= 60) return '#eab308'
  return '#22c55e'
}
function symbol() { return currency.value === 'CNY' ? '¥' : '$' }

async function startDrag() { await getCurrentWindow().startDragging() }
async function togglePanel() {
  const panel = await WebviewWindow.getByLabel('panel')
  if (panel) await panel.show()
}
</script>

<template>
  <div class="ball" :style="{ background: ballColor() }"
       @mousedown="startDrag" @click="togglePanel">
    <div class="today">{{ symbol() }}{{ today.toFixed(4) }}</div>
    <div class="rate">{{ symbol() }}{{ rate.toFixed(4) }}/min</div>
  </div>
</template>

<style scoped>
.ball {
  width: 90px; height: 90px; border-radius: 50%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  color: white; cursor: grab; user-select: none;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  font-family: -apple-system, sans-serif;
}
.today { font-size: 13px; font-weight: 700; }
.rate { font-size: 9px; opacity: 0.85; }
</style>
```

### 7. 实现展开面板 UI

在 `desktop/src/` 新建一个 `Panel.vue`，作为 panel 窗口的内容。但注意：Tauri 默认所有窗口共用同一个前端入口。简单做法是：
- 用 URL query 或窗口 label 区分渲染哪个组件
- 改 `main.ts`，根据 `getCurrentWindow().label` 决定挂载 App.vue（ball）还是 Panel.vue（panel）

Panel.vue 要求：
- 显示完整电表：今日/本月/月终预测（含置信度）/累计节省
- 模型分布表格（model / 花费 / tokens）
- 实时速率
- 数据从 `${API}/api/meter/summary` + `${API}/api/meter/models` 拉取
- 右上角关闭按钮（点 panel 窗口的 hide）
- 半透明圆角面板，现代感（CSS）

### 8. 启动 sidecar + 悬浮球联调

先启动 sidecar（已打包好的 exe）：
```powershell
Start-Process -FilePath "..\dist\tokeneff-sidecar.exe"
# 等几秒
```
确认 sidecar 在跑：
```powershell
curl http://127.0.0.1:7861/api/health
```

然后跑悬浮球（开发模式）：
```powershell
cd desktop
npm run tauri dev
```

预期：屏幕左上角出现一个圆形悬浮球，显示 ¥0.0000（电表空数据）。往 sidecar 写一笔数据：
```powershell
# 模拟一笔计费（用 sidecar 的 key 端点 + 手动写 meter——实际没有直接写 meter 的端点，
# 可跳过这步，只要悬浮球能显示 0 且每秒刷新不报错即说明 API 联通）
```

悬浮球应：
- 显示今日花费 + 速率（哪怕是 0）
- 每 1 秒刷新一次
- 能拖拽移动
- 点击展开面板，面板显示完整电表

### 9. 记录验证结果

【验证1 - 悬浮球显示】悬浮球出现，显示 ¥0.0000 或真实数据，每秒刷新。✅/❌
【验证2 - 拖拽】鼠标按住悬浮球能拖动到屏幕任意位置。✅/❌
【验证3 - 展开面板】点击悬浮球，展开面板出现，显示今日/本月/预测/模型分布。✅/❌
【验证4 - 透明置顶】悬浮球透明背景，始终在别的窗口上面。✅/❌
【验证5 - sidecar 联通】悬浮球数据来自 7861 API（关掉 sidecar 后悬浮球显示"连接中"态）。✅/❌

### 10. 提交到 git

在 desktop 目录初始化 git 或直接把 desktop/ 加入 token-efficiency 仓库。
```powershell
cd <token-efficiency-main 目录>
git add desktop/
git commit -m "feat(desktop): B2 Tauri 悬浮球骨架 + 展开面板，连接 sidecar 7861

- Vue 3 + TypeScript + Tauri 2
- 悬浮球：透明无边框/置顶/可拖拽/点击展开
- 展开面板：今日/本月/月终预测/模型分布/实时速率
- 连接 sidecar 7861 只读 API，每秒刷新"
git push
```

---

【完成后】把第 9 步五个验证的结果告诉我（成功/失败 + 截图描述或报错）。尤其确认：
- 悬浮球视觉效果如何（圆不圆、透明不透明、置顶不置顶）
- 数据是否每秒刷新
- 有没有报错

【可能的问题】
- `npm run tauri dev` 报 MSVC 缺失 → 装 VS Build Tools（C++ 桌面开发）
- transparent:true 窗口有黑底 → Windows 上正常，Vue 里 body 背景设 transparent 即可
- axios 请求被 CORS 拦 → sidecar 已配 allow_origins 含 tauri://localhost，应该不会；若拦，检查 sidecar 日志
- startDragging 报错 → 确认 @tauri-apps/api 版本与 tauri 2 匹配

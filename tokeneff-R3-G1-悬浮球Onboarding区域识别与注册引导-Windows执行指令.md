# tokeneff R3+G1 执行指令（Windows Claude Code 用）

> 悬浮球 onboarding：静默区域判断（R3）+ 网关注册引导（G1）
> 前置：R1+R2 已 push（sidecar 有 `/api/region/detect` 端点 + config.set_region 联动 platform_url）

---

【任务】改造悬浮球 Onboarding.vue：
1. **R3 静默区域判断**：启动时调 `/api/region/detect` → 自动设 region（联动 platform_url），**不询问用户**（与网站 geo.js / CLI wizard 一致，程序按真实位置直接引导）
2. **G1 网关注册引导**：区域判断后，新增"接入方式选择"（推荐网关 / BYOK）；选网关则引导注册（打开对应区域注册页 + 粘贴 key 验证 + 切平台模式）

**关键约束**：
- region 完全静默，不问用户、不显示选择，程序直接判断
- 注册页 URL 按区域：cn→`tokeneff.com/register`，global→`global.tokeneff.com/register`
- BYOK 路径保留现有流程（不破坏 B3 已做的）

---

## 步骤

### 1. 拉最新代码 + 重打 sidecar

R1 改了 sidecar（新增 `/api/region/detect`），必须重打 exe：
```powershell
cd token-efficiency
git pull origin main
bash packaging/build-sidecar.sh
# 或手动：.venv\Scripts\python -m PyInstaller --onefile --name tokeneff-sidecar --additional-hooks-dir packaging/hooks --collect-submodules tokeneff --distpath dist --noconfirm packaging/sidecar_entry.py
```
重启悬浮球加载新 sidecar。

### 2. sidecar.ts 加 detectRegion 方法

在 `desktop/src/sidecar.ts` 加（调 R1 新端点）：
```typescript
/** GET /api/region/detect — 多信号区域识别（R1，穿透 VPN） */
export async function detectRegion(): Promise<{
  timezone: string; locale: string; ip_country: string | null;
  win_locale: string | null; cn_score: number; global_score: number;
  recommended: "cn" | "global" | null; reason: string;
}> {
  const r = await fetch(`${SIDECAR_BASE}/api/region/detect`);
  if (!r.ok) throw new Error("region detect failed");
  return r.json();
}
```

### 3. Onboarding.vue — R3 静默区域判断

在 `<script setup>` 的 `onMounted` 里加静默判断（**不问用户，不显示选择**）：
```typescript
import { detectRegion } from "./sidecar";

const detectedRegion = ref<"cn"|"global">("cn");  // 默认 cn，会被覆盖

onMounted(async () => {
  // ★ R3 静默区域判断（与网站/CLI 一致，程序直接定，不询问）
  try {
    const sig = await detectRegion();
    // recommended 为 null（边界）时 fallback locale：zh→cn，否则 global
    detectedRegion.value = sig.recommended ?? (sig.locale.startsWith("zh") ? "cn" : "global");
    // 联动 platform_url（sidecar 的 POST /api/config 触发 set_region 逻辑）
    await updateConfig({ region: detectedRegion.value });
  } catch {
    detectedRegion.value = "cn";  // 探测失败默认 cn
  }
});

// 注册页 URL 按区域（G1 引导用）
const registerUrl = computed(() =>
  detectedRegion.value === "cn"
    ? "https://tokeneff.com/register?source=tokeneff-cli"
    : "https://global.tokeneff.com/register?source=tokeneff-cli"
);
```

> 注：`updateConfig` 和 `verifyPlatformKey`/`savePlatformKey` 在 sidecar.ts 已有（B3.1）。若 `POST /api/config` 不自动联动 platform_url，补一个 region→platform_url 的映射（cn→tokeneff.com / global→global.tokeneff.com）一并 POST。

### 4. Onboarding.vue — G1 接入方式选择（Step 1 改造）

把现有 Step 1（选 provider）前面加一个"接入方式选择"步骤。改 step 流程：

**新增 Step 1：接入方式选择**（网关推荐 / BYOK）
```vue
<!-- Step 1: 接入方式选择（G1） -->
<div v-if="step === 1" class="step">
  <h2>你想怎么用电表？</h2>
  <div class="mode-cards">
    <!-- 推荐网关（默认高亮） -->
    <div class="mode-card recommended" @click="choosePlatform">
      <div class="mode-icon">🚀</div>
      <div class="mode-title">tokeneff 网关（推荐）</div>
      <div class="mode-desc">一个 key 通吃所有模型，首月免费，比官方便宜 33-88%</div>
    </div>
    <!-- BYOK -->
    <div class="mode-card" @click="chooseByok">
      <div class="mode-icon">🔑</div>
      <div class="mode-title">用我自己的 key（BYOK）</div>
      <div class="mode-desc">免费直连，0 加价，key 不离开本机</div>
    </div>
  </div>
</div>
```

```typescript
function choosePlatform() { mode.value = "platform"; step.value = 2; }
function chooseByok()     { mode.value = "byok";     step.value = 10; }  // BYOK 走原有流程（step 10+）
const mode = ref<"platform"|"byok">("platform");
```

**Step 2：网关注册引导**（选网关后）
```vue
<!-- Step 2: 网关注册引导（G1） -->
<div v-else-if="step === 2 && mode === 'platform'" class="step">
  <h2>注册 tokeneff 网关账号</h2>
  <ol>
    <li>点击打开注册页（已按你的区域选择）：
      <a :href="registerUrl" target="_blank" class="register-link">
        🌐 打开 {{ detectedRegion === 'cn' ? 'tokeneff.com' : 'global.tokeneff.com' }}/register
      </a>
    </li>
    <li>注册后在「API Keys」页创建一个 key</li>
    <li>复制 key，粘贴到下面：</li>
  </ol>
  <input v-model="platformKey" placeholder="sk-tf-..." class="key-input" />
  <button class="primary" :disabled="!platformKey" @click="verifyAndSavePlatform">
    验证并保存
  </button>
  <button class="ghost" @click="step = 1">返回</button>
  <div v-if="platformMsg" :class="['msg', platformOk ? 'ok' : 'err']">{{ platformMsg }}</div>
  <!-- 已有账号快捷入口 -->
  <div class="have-key">已有账号？<a href="#" @click.prevent="step = 2">直接粘贴 key</a></div>
</div>
```

```typescript
const platformKey = ref("");
const platformMsg = ref("");
const platformOk = ref(false);

async function verifyAndSavePlatform() {
  platformMsg.value = "验证中...";
  try {
    // 验证 key（B3.1 的 verifyPlatformKey）
    const v = await verifyPlatformKey(platformKey.value);
    if (!v.ok) { platformMsg.value = v.message || "key 无效"; platformOk.value = false; return; }
    // 保存 key
    await savePlatformKey(platformKey.value);
    // 切平台模式
    await updateConfig({ mode: "platform" });
    platformMsg.value = "✓ 网关 key 有效，已切换到平台模式";
    platformOk.value = true;
    setTimeout(() => { step.value = 3; }, 800);  // 进入"指向代理"步骤
  } catch (e) {
    platformMsg.value = "验证失败: " + e; platformOk.value = false;
  }
}
```

**Step 3+：指向代理 + 测试**（两条路径收敛，B3 已有，保留）
**Step 10+：BYOK 路径**（原 Step 1-4 的选 provider→贴 key 流程，平移到 step 10+）

### 5. 样式（mode-cards）

在 Onboarding.vue 的 `<style>` 加：
```css
.mode-cards { display: flex; gap: 1rem; margin: 1rem 0; }
.mode-card {
  flex: 1; padding: 1.5rem; border: 2px solid #e2e8f0; border-radius: 12px;
  cursor: pointer; transition: all 0.2s; text-align: center;
}
.mode-card:hover { border-color: #6366f1; transform: translateY(-2px); }
.mode-card.recommended { border-color: #6366f1; background: #eef2ff; position: relative; }
.mode-card.recommended::after {
  content: "推荐"; position: absolute; top: -10px; right: 10px;
  background: #6366f1; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem;
}
.mode-icon { font-size: 2rem; margin-bottom: 0.5rem; }
.mode-title { font-weight: 600; margin-bottom: 0.25rem; }
.mode-desc { font-size: 0.85rem; color: #64748b; }
.register-link { display: inline-block; margin: 0.5rem 0; color: #6366f1; }
.key-input { width: 100%; padding: 0.6rem; margin: 0.5rem 0; border: 1px solid #e2e8f0; border-radius: 6px; }
.msg.ok { color: #22c55e; } .msg.err { color: #ef4444; }
.have-key { margin-top: 1rem; font-size: 0.85rem; color: #64748b; }
```

---

## 验证

【验证1 - 静默区域】悬浮球首次启动 → 无区域选择/提示 → 后台自动判 region（看 /api/config 返回 region + platform_url 联动正确）
【验证2 - 接入方式】Step 1 显示网关/BYOK 两张卡片，网关标"推荐"
【验证3 - 注册引导】选网关 → 显示对应区域注册页链接（cn 用户 tokeneff.com/register，global 用户 global.tokeneff.com/register）→ 点击浏览器打开
【验证4 - key 验证】粘贴网关 key → 验证通过 → 切平台模式 → 进入指向代理
【验证5 - BYOK 回退】选 BYOK → 走原有 provider+key 流程，不受影响
【验证6 - 转化闭环】网关模式配置完 → 测试请求 → 悬浮球显示 platform 模式计费（saved>0）

## 提交
```powershell
git add desktop/src/Onboarding.vue desktop/src/sidecar.ts
git commit -m "feat(desktop): R3+G1 悬浮球 onboarding 静默区域判断 + 网关注册引导

R3 静默区域判断（与网站/CLI 一致）：
- onMounted 调 /api/region/detect → 自动设 region（不询问用户）
- 联动 platform_url（cn→tokeneff.com / global→global站）

G1 网关注册引导：
- 接入方式选择（网关推荐 / BYOK）
- 网关路径：注册页（按区域）+ 粘贴 key 验证 + 切平台模式
- BYOK 路径：保留原有流程"
git push
```

## 可能问题
- `/api/config` POST region 不联动 platform_url：sidecar 的 update_config 只存字段，需补 set_region 逻辑。检查 local_server.py 的 update_config，region 改动时调 cfg.set_region（或前端额外 POST platform_url）
- verifyPlatformKey 打的 platform_url：确认 sidecar 用的是联动后的 platform_url（cn→tokeneff.com/v1/models）
- 静默 region 用户无感知：完成摘要或设置页可显示当前 region（结果展示，非询问）

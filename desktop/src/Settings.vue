<script setup lang="ts">
import { ref, onMounted, watch } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Onboarding from "./Onboarding.vue";
import {
  fetchConfig,
  fetchProviders,
  verifyKey,
  saveKey,
  verifyPlatformKey,
  savePlatformKey,
  updateConfig,
  type AppConfig,
  type ProviderInfo,
} from "./sidecar";

// Load state: null=undetermined, true=onboarding needed, false=regular settings
const needsOnboarding = ref<boolean | null>(null);
const config = ref<AppConfig | null>(null);
const loadErr = ref("");

// Tabs
type Tab = "provider" | "budget" | "region" | "startup";
const activeTab = ref<Tab>("provider");

// Access mode (B3.1): byok = own provider key / platform = tokeneff gateway key
const mode = ref<"byok" | "platform">("byok");

// Provider tab (BYOK)
const providers = ref<ProviderInfo[]>([]);
const selProvider = ref("");
const apiKey = ref("");
const verifyState = ref<"idle" | "verifying" | "ok" | "fail">("idle");
const verifyMsg = ref("");
const saveMsg = ref("");

// Gateway tab (platform, B3.1)
const platformKey = ref("");
const platformUrl = ref("");
const platformVerifyState = ref<"idle" | "verifying" | "ok" | "fail">("idle");
const platformVerifyMsg = ref("");
const platformSaveMsg = ref("");

// Budget tab
const budget = ref(10);
const threshold = ref(80);
const budgetSaved = ref(false);

// Region tab
const region = ref("CN");
const regionSaved = ref(false);

// Startup tab (autostart plugin not integrated, grayed out)
const autostart = ref(false);
const autostartUnavailable = ref(true);

async function load() {
  try {
    config.value = await fetchConfig();
    providers.value = await fetchProviders();
    budget.value = config.value.budget_monthly_usd || 10;
    threshold.value = config.value.alert_threshold || 80;
    region.value = config.value.region || "CN";
    mode.value = (config.value.mode as "byok" | "platform") || "byok";
    platformUrl.value = config.value.platform_url || "";
    // Onboarding check: BYOK has no provider, or platform has no key
    const byokEmpty = (config.value.providers_configured?.length ?? 0) === 0;
    const platformEmpty = !config.value.has_platform_key;
    needsOnboarding.value =
      (mode.value === "platform" && platformEmpty) ||
      (mode.value === "byok" && byokEmpty);
  } catch (e) {
    loadErr.value = String(e);
    needsOnboarding.value = false;
  }
}

// Switch access mode (B3.1)
async function switchMode(m: "byok" | "platform") {
  if (m === mode.value) return;
  mode.value = m;
  try {
    await updateConfig({ mode: m });
  } catch {
    /* ignore, next load will correct it */
  }
}

// Gateway key verify + store (B3.1)
async function doPlatformVerify() {
  if (!platformKey.value) return;
  platformVerifyState.value = "verifying";
  platformVerifyMsg.value = "";
  try {
    const r = await verifyPlatformKey(platformKey.value, platformUrl.value || undefined);
    if (r.ok) {
      platformVerifyState.value = "ok";
      platformVerifyMsg.value = r.message || "网关 key 有效";
      const s = await savePlatformKey(platformKey.value);
      platformSaveMsg.value = s.ok ? "已验证并存储" : s.error || "存储失败";
    } else {
      platformVerifyState.value = "fail";
      platformVerifyMsg.value = r.message || "验证失败";
    }
  } catch (e) {
    platformVerifyState.value = "fail";
    platformVerifyMsg.value = String(e);
  }
}

// Debounce-save on gateway address change (non-sensitive config, via /api/config)
let urlSaveTimer: number | undefined;
watch(platformUrl, (v) => {
  if (urlSaveTimer) window.clearTimeout(urlSaveTimer);
  urlSaveTimer = window.setTimeout(async () => {
    try {
      await updateConfig({ platform_url: v });
    } catch {
      /* ignore */
    }
  }, 500);
});

onMounted(() => {
  load();
  // Intercept titlebar × close: hide instead, so the window isn't destroyed and openSettings can find it again.
  // Tauri decorations:true × triggers close (destroy) by default; here we prevent default and hide instead.
  getCurrentWindow().onCloseRequested(async (e) => {
    e.preventDefault();
    await getCurrentWindow().hide();
  });
});

// ── provider tab operations ───────────────────────────────────────────────────────
async function doVerify() {
  if (!selProvider.value || !apiKey.value) return;
  verifyState.value = "verifying";
  verifyMsg.value = "";
  try {
    const r = await verifyKey(selProvider.value, apiKey.value);
    if (r.ok) {
      verifyState.value = "ok";
      verifyMsg.value = r.message || "Key 有效";
      // Auto-store on verify success
      const s = await saveKey(selProvider.value, apiKey.value);
      saveMsg.value = s.ok ? "已验证并存储" : s.error || "存储失败";
      // Refresh provider configured state
      providers.value = await fetchProviders();
    } else {
      verifyState.value = "fail";
      verifyMsg.value = r.message || "验证失败";
    }
  } catch (e) {
    verifyState.value = "fail";
    verifyMsg.value = String(e);
  }
}

// ── budget save ────────────────────────────────────────────────────────────────
async function saveBudget() {
  try {
    await updateConfig({
      budget_monthly_usd: budget.value,
      alert_threshold: threshold.value,
    });
    budgetSaved.value = true;
    setTimeout(() => (budgetSaved.value = false), 1500);
  } catch {
    /* ignore */
  }
}

// ── region save ────────────────────────────────────────────────────────────────
async function saveRegion() {
  try {
    await updateConfig({ region: region.value });
    regionSaved.value = true;
    setTimeout(() => (regionSaved.value = false), 1500);
  } catch {
    /* ignore */
  }
}

// ── Onboarding done callback ─────────────────────────────────────────────────────
async function onOnboardingDone() {
  await load();
  needsOnboarding.value = false;
}
</script>

<template>
  <div class="settings-root">
    <!-- loading -->
    <div v-if="needsOnboarding === null" class="loading">
      <p v-if="loadErr" class="err">连接 sidecar 失败：{{ loadErr }}</p>
      <p v-else>⚡ 加载配置中…</p>
    </div>

    <!-- First launch → Onboarding -->
    <Onboarding v-else-if="needsOnboarding" @done="onOnboardingDone" />

    <!-- Regular settings -->
    <div v-else class="settings-shell">
      <nav class="tabs">
        <button
          :class="{ active: activeTab === 'provider' }"
          @click="activeTab = 'provider'"
        >
          Provider
        </button>
        <button
          :class="{ active: activeTab === 'budget' }"
          @click="activeTab = 'budget'"
        >
          预算
        </button>
        <button
          :class="{ active: activeTab === 'region' }"
          @click="activeTab = 'region'"
        >
          区域
        </button>
        <button
          :class="{ active: activeTab === 'startup' }"
          @click="activeTab = 'startup'"
        >
          启动
        </button>
      </nav>

      <section class="content">
        <!-- Provider -->
        <div v-show="activeTab === 'provider'" class="pane">
          <h3>API Provider 管理</h3>

          <!-- B3.1: access mode selection -->
          <div class="field">
            <label>接入模式</label>
            <div class="mode-cards">
              <div
                class="mode-card"
                :class="{ active: mode === 'byok' }"
                @click="switchMode('byok')"
              >
                <div class="mode-title">自带 Key（BYOK）</div>
                <div class="mode-desc">用你自己的 provider key（GLM/OpenAI 等），直连上游</div>
              </div>
              <div
                class="mode-card"
                :class="{ active: mode === 'platform' }"
                @click="switchMode('platform')"
              >
                <div class="mode-title">tokeneff 网关</div>
                <div class="mode-desc">用一个网关 key 通吃多模型，按量计费享批发价</div>
              </div>
            </div>
          </div>

          <!-- BYOK mode: provider + key -->
          <template v-if="mode === 'byok'">
            <div class="field">
              <label>选择 Provider</label>
              <select v-model="selProvider">
                <option value="" disabled>请选择…</option>
                <option
                  v-for="p in providers"
                  :key="p.name"
                  :value="p.name"
                >
                  {{ p.label }}{{ p.configured ? " ✓" : "" }}
                </option>
              </select>
            </div>

            <div class="field">
              <label>API Key</label>
              <textarea
                v-model="apiKey"
                rows="2"
                :placeholder="'粘贴 ' + (selProvider || 'provider') + ' 的 API Key'"
              ></textarea>
            </div>

            <div class="actions">
              <button
                class="primary"
                :disabled="!selProvider || !apiKey || verifyState === 'verifying'"
                @click="doVerify"
              >
                {{ verifyState === "verifying" ? "验证中…" : "验证并保存" }}
              </button>
            </div>

            <p v-if="verifyState === 'ok'" class="hint ok">
              ✓ {{ verifyMsg }}<span v-if="saveMsg"> · {{ saveMsg }}</span>
            </p>
            <p v-else-if="verifyState === 'fail'" class="hint err">
              ✗ {{ verifyMsg }}
            </p>

            <div class="configured-list" v-if="providers.some((p) => p.configured)">
              <h4>已配置</h4>
              <ul>
                <li v-for="p in providers.filter((x) => x.configured)" :key="p.name">
                  {{ p.label }}
                  <span class="muted">（{{ p.models[0] || p.name }}）</span>
                </li>
              </ul>
            </div>
          </template>

          <!-- Platform mode: gateway key -->
          <template v-else>
            <div class="field">
              <label>tokeneff 网关 API Key</label>
              <textarea
                v-model="platformKey"
                rows="2"
                placeholder="粘贴从 tokeneff 网关获取的 API Key"
              ></textarea>
              <p class="hint muted">没有 key？前往 tokeneff.com 注册获取</p>
            </div>

            <div class="field">
              <label>网关地址（可选）</label>
              <input
                type="text"
                v-model="platformUrl"
                placeholder="留空用默认（tokeneff.com / global.tokeneff.com）"
              />
            </div>

            <div class="actions">
              <button
                class="primary"
                :disabled="!platformKey || platformVerifyState === 'verifying'"
                @click="doPlatformVerify"
              >
                {{ platformVerifyState === "verifying" ? "验证中…" : "验证并保存" }}
              </button>
            </div>

            <p v-if="platformVerifyState === 'ok'" class="hint ok">
              ✓ {{ platformVerifyMsg }}<span v-if="platformSaveMsg"> · {{ platformSaveMsg }}</span>
            </p>
            <p v-else-if="platformVerifyState === 'fail'" class="hint err">
              ✗ {{ platformVerifyMsg }}
            </p>
            <p v-if="config?.has_platform_key" class="hint ok">
              ✓ 已配置网关 key
            </p>
          </template>
        </div>

        <!-- budget -->
        <div v-show="activeTab === 'budget'" class="pane">
          <h3>月度预算</h3>
          <div class="field">
            <label>预算金额（USD）</label>
            <input type="number" v-model.number="budget" min="0" step="1" />
          </div>
          <div class="field">
            <label>告警阈值：{{ threshold }}%</label>
            <input type="range" v-model.number="threshold" min="10" max="100" step="5" />
          </div>
          <div class="actions">
            <button class="primary" @click="saveBudget">
              {{ budgetSaved ? "已保存 ✓" : "保存" }}
            </button>
          </div>
        </div>

        <!-- region -->
        <div v-show="activeTab === 'region'" class="pane">
          <h3>区域与币种</h3>
          <div class="field radio-group">
            <label>
              <input type="radio" v-model="region" value="CN" /> 中国大陆（CNY ¥）
            </label>
            <label>
              <input type="radio" v-model="region" value="Global" /> 全球（USD $）
            </label>
          </div>
          <div class="actions">
            <button class="primary" @click="saveRegion">
              {{ regionSaved ? "已保存 ✓" : "保存" }}
            </button>
          </div>
        </div>

        <!-- startup -->
        <div v-show="activeTab === 'startup'" class="pane">
          <h3>开机自启</h3>
          <div class="field">
            <label class="switch-row">
              <input
                type="checkbox"
                v-model="autostart"
                :disabled="autostartUnavailable"
              />
              <span>登录时自动启动 tokeneff</span>
            </label>
            <p class="hint muted" v-if="autostartUnavailable">
              （此功能需集成 Tauri autostart 插件，当前版本暂未启用）
            </p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.settings-root {
  width: 100%;
  height: 100vh;
  background: #1f2937;
  color: #e5e7eb;
  font-family: -apple-system, "Segoe UI", sans-serif;
  display: flex;
}
.loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 14px;
}
.err {
  color: #ef4444;
}
.settings-shell {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.tabs {
  width: 130px;
  background: #111827;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  gap: 2px;
  border-right: 1px solid #374151;
}
.tabs button {
  background: transparent;
  border: none;
  color: #9ca3af;
  text-align: left;
  padding: 10px 18px;
  font-size: 13px;
  cursor: pointer;
  border-left: 3px solid transparent;
}
.tabs button:hover {
  background: #1f2937;
  color: #e5e7eb;
}
.tabs button.active {
  color: #fff;
  background: #1f2937;
  border-left-color: #6366f1;
}
.content {
  flex: 1;
  padding: 24px 28px;
  overflow-y: auto;
}
.pane h3 {
  font-size: 15px;
  margin: 0 0 18px;
  color: #fff;
}
.field {
  margin-bottom: 16px;
}
.field > label {
  display: block;
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 6px;
}
select,
input[type="number"],
input[type="text"],
textarea {
  width: 100%;
  background: #111827;
  border: 1px solid #374151;
  color: #e5e7eb;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  box-sizing: border-box;
}
textarea {
  font-family: monospace;
  resize: vertical;
}
/* B3.1: access mode card selector */
.mode-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.mode-card {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.mode-card:hover {
  border-color: #4b5563;
}
.mode-card.active {
  border-color: #6366f1;
  background: #1e1b4b;
}
.mode-title {
  font-size: 13px;
  font-weight: 600;
  color: #e5e7eb;
  margin-bottom: 4px;
}
.mode-card.active .mode-title {
  color: #a5b4fc;
}
.mode-desc {
  font-size: 11px;
  color: #9ca3af;
  line-height: 1.4;
}
input[type="range"] {
  width: 100%;
  accent-color: #6366f1;
}
.radio-group label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #e5e7eb;
  margin-bottom: 10px;
  cursor: pointer;
}
.switch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.actions {
  margin-top: 8px;
}
button.primary {
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 8px 20px;
  font-size: 13px;
  cursor: pointer;
}
button.primary:hover:not(:disabled) {
  background: #4f46e5;
}
button.primary:disabled {
  background: #374151;
  color: #6b7280;
  cursor: not-allowed;
}
.hint {
  font-size: 12px;
  margin-top: 8px;
}
.hint.ok {
  color: #22c55e;
}
.hint.err {
  color: #ef4444;
}
.muted {
  color: #6b7280;
}
.configured-list {
  margin-top: 22px;
  border-top: 1px solid #374151;
  padding-top: 14px;
}
.configured-list h4 {
  font-size: 12px;
  color: #9ca3af;
  margin: 0 0 8px;
}
.configured-list ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.configured-list li {
  font-size: 13px;
  padding: 4px 0;
  color: #e5e7eb;
}
</style>

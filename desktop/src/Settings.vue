<script setup lang="ts">
import { ref, onMounted } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Onboarding from "./Onboarding.vue";
import {
  fetchConfig,
  fetchProviders,
  verifyKey,
  saveKey,
  updateConfig,
  type AppConfig,
  type ProviderInfo,
} from "./sidecar";

// 加载状态：null=未确定，true=需 onboarding，false=常规设置
const needsOnboarding = ref<boolean | null>(null);
const config = ref<AppConfig | null>(null);
const loadErr = ref("");

// 标签页
type Tab = "provider" | "budget" | "region" | "startup";
const activeTab = ref<Tab>("provider");

// provider 标签
const providers = ref<ProviderInfo[]>([]);
const selProvider = ref("");
const apiKey = ref("");
const verifyState = ref<"idle" | "verifying" | "ok" | "fail">("idle");
const verifyMsg = ref("");
const saveMsg = ref("");

// 预算标签
const budget = ref(10);
const threshold = ref(80);
const budgetSaved = ref(false);

// 区域标签
const region = ref("CN");
const regionSaved = ref(false);

// 启动标签（autostart 插件未集成，置灰）
const autostart = ref(false);
const autostartUnavailable = ref(true);

async function load() {
  try {
    config.value = await fetchConfig();
    providers.value = await fetchProviders();
    budget.value = config.value.budget_monthly_usd || 10;
    threshold.value = config.value.alert_threshold || 80;
    region.value = config.value.region || "CN";
    needsOnboarding.value =
      (config.value.providers_configured?.length ?? 0) === 0;
  } catch (e) {
    loadErr.value = String(e);
    needsOnboarding.value = false;
  }
}

onMounted(() => {
  load();
  // 拦截标题栏 × 关闭：改为隐藏，避免窗口被销毁后再次 openSettings 找不到窗口。
  // Tauri decorations:true 的 × 默认触发 close（销毁），这里阻止默认、改 hide。
  getCurrentWindow().onCloseRequested(async (e) => {
    e.preventDefault();
    await getCurrentWindow().hide();
  });
});

// ── provider 标签操作 ───────────────────────────────────────────────────────
async function doVerify() {
  if (!selProvider.value || !apiKey.value) return;
  verifyState.value = "verifying";
  verifyMsg.value = "";
  try {
    const r = await verifyKey(selProvider.value, apiKey.value);
    if (r.ok) {
      verifyState.value = "ok";
      verifyMsg.value = r.message || "Key 有效";
      // 验证通过自动存储
      const s = await saveKey(selProvider.value, apiKey.value);
      saveMsg.value = s.ok ? "已验证并存储" : s.error || "存储失败";
      // 刷新 provider configured 状态
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

// ── 预算保存 ────────────────────────────────────────────────────────────────
async function saveBudget() {
  try {
    await updateConfig({
      budget_monthly_usd: budget.value,
      alert_threshold: threshold.value,
    });
    budgetSaved.value = true;
    setTimeout(() => (budgetSaved.value = false), 1500);
  } catch {
    /* 忽略 */
  }
}

// ── 区域保存 ────────────────────────────────────────────────────────────────
async function saveRegion() {
  try {
    await updateConfig({ region: region.value });
    regionSaved.value = true;
    setTimeout(() => (regionSaved.value = false), 1500);
  } catch {
    /* 忽略 */
  }
}

// ── Onboarding 完成回调 ─────────────────────────────────────────────────────
async function onOnboardingDone() {
  await load();
  needsOnboarding.value = false;
}
</script>

<template>
  <div class="settings-root">
    <!-- 加载中 -->
    <div v-if="needsOnboarding === null" class="loading">
      <p v-if="loadErr" class="err">连接 sidecar 失败：{{ loadErr }}</p>
      <p v-else>⚡ 加载配置中…</p>
    </div>

    <!-- 首次启动 → Onboarding -->
    <Onboarding v-else-if="needsOnboarding" @done="onOnboardingDone" />

    <!-- 常规设置 -->
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
        </div>

        <!-- 预算 -->
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

        <!-- 区域 -->
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

        <!-- 启动 -->
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

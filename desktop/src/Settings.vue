<script setup lang="ts">
import { ref, onMounted, watch, computed } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  enable,
  disable,
  isEnabled,
} from "@tauri-apps/plugin-autostart";
import Onboarding from "./Onboarding.vue";
import { initLang, setRegion, useT } from "./i18n";

const t = useT();
import {
  fetchConfig,
  fetchProviders,
  verifyKey,
  saveKey,
  verifyPlatformKey,
  discoverSidecarPort,
  installSidecarRecovery,
  savePlatformKey,
  updateConfig,
  detectRegion,
  type AppConfig,
  type ProviderInfo,
  type RegionSignals,
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

// ★ G1 register URL routed by detected region (consistent with Onboarding)
const registerUrl = computed(() =>
  config.value?.region === "global"
    ? "https://global.tokeneff.com/register?source=tokeneff-cli"
    : "https://tokeneff.com/register?source=tokeneff-cli"
);

// Budget tab
const budget = ref(10);
const threshold = ref(80);
const budgetSaved = ref(false);

// Region tab
const region = ref("cn");
const regionSaved = ref(false);

// Startup tab — tauri-plugin-autostart (Windows 写 HKCU Run，与 NSIS 装后注册
// 的同一键，装后默认开的状态能被 isEnabled 正确读到)
const autostart = ref(false);
const autostartUnavailable = ref(false);
const autostartMsg = ref("");

async function load() {
  try {
    config.value = await fetchConfig();
    providers.value = await fetchProviders();
    budget.value = config.value.budget_monthly_usd || 10;
    // backend stores percent (10-100); guard against legacy 0-1 values
    const t = config.value.alert_threshold || 80;
    threshold.value = t <= 1 ? t * 100 : t;
    region.value = config.value.region || "cn";
    regionLocked.value = config.value.region_manual ?? false;
    mode.value = (config.value.mode as "byok" | "platform") || "byok";
    platformUrl.value = config.value.platform_url || "";
    // Onboarding check: BYOK has no provider, or platform has no key
    const byokEmpty = (config.value.providers_configured?.length ?? 0) === 0;
    const platformEmpty = !config.value.has_platform_key;
    needsOnboarding.value =
      (mode.value === "platform" && platformEmpty) ||
      (mode.value === "byok" && byokEmpty);
    // 开机自启状态（插件读 HKCU Run；dev 未装时不可用→开关灰）
    try {
      autostart.value = await isEnabled();
    } catch {
      autostartUnavailable.value = true;
    }
    // 区域探测（进入设置页时静默刷新一次判定依据展示）
    redetectRegion();
  } catch (e) {
    loadErr.value = String(e);
    needsOnboarding.value = false;
  }
}

async function toggleAutostart() {
  autostartMsg.value = "";
  try {
    if (autostart.value) {
      await enable();
    } else {
      await disable();
    }
    autostart.value = await isEnabled();
  } catch (e) {
    // 回滚 UI 状态并提示（失败常见原因：无 HKCU 写权限）
    autostart.value = !autostart.value;
    autostartMsg.value = t.value("stSetFail") + String(e);
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
      platformVerifyMsg.value = r.message || t.value("stGwKeyValid");
      const s = await savePlatformKey(platformKey.value);
      platformSaveMsg.value = s.ok ? t.value("stVerifiedStored") : s.error || t.value("stStoreFail");
    } else {
      platformVerifyState.value = "fail";
      platformVerifyMsg.value = r.message || t.value("stVerifyFail");
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
  // ★ port-drift fix: learn the sidecar's actual port before first load
  discoverSidecarPort();
  installSidecarRecovery();
  initLang();
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
      verifyMsg.value = r.message || t.value("stKeyValid");
      // Auto-store on verify success
      const s = await saveKey(selProvider.value, apiKey.value);
      saveMsg.value = s.ok ? t.value("stVerifiedStored") : s.error || t.value("stStoreFail");
      // Refresh provider configured state
      providers.value = await fetchProviders();
    } else {
      verifyState.value = "fail";
      verifyMsg.value = r.message || t.value("stVerifyFail");
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

// ── region: auto-detect with manual override ────────────────────────────────
// ★ R1 多信号探测已有（时区主/IP次，防 VPN 误判）；这里把探测结果可视化，
// 默认自动跟随判定，手动选择折叠为"高级"入口（出差/VPN 用户兜底）
const regionSignals = ref<RegionSignals | null>(null);
const regionDetecting = ref(false);
const showManualRegion = ref(false);
// ★ manual-override lock: after a manual save, silent auto-detect only refreshes
// the detection-basis display — it must NOT rewrite the user's region. Only the
// explicit "重新检测" button applies a new detection and clears the lock.
const regionLocked = ref(false);

async function redetectRegion(explicit = false) {
  regionDetecting.value = true;
  try {
    const sig = await detectRegion();
    regionSignals.value = sig;
    // 锁定状态下的静默检测：只更新判定依据展示，不改写区域
    if (!explicit && regionLocked.value) return;
    const recommended = sig.recommended ?? (sig.locale.startsWith("zh") ? "cn" : "global");
    if (recommended !== region.value) {
      region.value = recommended;
      await updateConfig({ region: recommended, region_manual: false });
      setRegion(recommended); // 广播：球/面板窗口即时切换语言与币种显示
      regionLocked.value = false;
      regionSaved.value = true;
      setTimeout(() => (regionSaved.value = false), 1500);
    } else if (explicit) {
      // 显式重测但推荐值与当前一致：仅确认解锁状态
      await updateConfig({ region_manual: false });
      regionLocked.value = false;
    }
  } catch {
    /* 探测失败保留当前区域 */
  } finally {
    regionDetecting.value = false;
  }
}

async function saveRegion() {
  try {
    await updateConfig({ region: region.value, region_manual: true });
    setRegion(region.value); // 广播：球/面板窗口即时切换语言与币种显示
    regionLocked.value = true;
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
      <p v-if="loadErr" class="err">{{ t("stConnFail") }}{{ loadErr }}</p>
      <p v-else>{{ t("stLoading") }}</p>
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
          {{ t("stTabBudget") }}
        </button>
        <button
          :class="{ active: activeTab === 'region' }"
          @click="activeTab = 'region'"
        >
          {{ t("stTabRegion") }}
        </button>
        <button
          :class="{ active: activeTab === 'startup' }"
          @click="activeTab = 'startup'"
        >
          {{ t("stTabStartup") }}
        </button>
      </nav>

      <section class="content">
        <!-- Provider -->
        <div v-show="activeTab === 'provider'" class="pane">
          <h3>{{ t("stProviderTitle") }}</h3>

          <!-- B3.1: access mode selection -->
          <div class="field">
            <label>{{ t("stAccessMode") }}</label>
            <div class="mode-cards">
              <div
                class="mode-card"
                :class="{ active: mode === 'byok' }"
                @click="switchMode('byok')"
              >
                <div class="mode-title">{{ t("stByokTitle") }}</div>
                <div class="mode-desc">{{ t("stByokDesc") }}</div>
              </div>
              <div
                class="mode-card"
                :class="{ active: mode === 'platform' }"
                @click="switchMode('platform')"
              >
                <div class="mode-title">{{ t("stPlatformTitle") }}</div>
                <div class="mode-desc">{{ t("stPlatformDesc") }}</div>
              </div>
            </div>
          </div>

          <!-- BYOK mode: provider + key -->
          <template v-if="mode === 'byok'">
            <div class="field">
              <label>{{ t("stSelectProvider") }}</label>
              <select v-model="selProvider">
                <option value="" disabled>{{ t("stSelectPh") }}</option>
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
              <label>{{ t("stApiKeyLabel") }}</label>
              <textarea
                v-model="apiKey"
                rows="2"
                :placeholder="t('obPastePre') + (selProvider || 'provider') + t('obPasteSuf')"
              ></textarea>
            </div>

            <div class="actions">
              <button
                class="primary"
                :disabled="!selProvider || !apiKey || verifyState === 'verifying'"
                @click="doVerify"
              >
                {{ verifyState === "verifying" ? t("obVerifying") : t("stVerifySave") }}
              </button>
            </div>

            <p v-if="verifyState === 'ok'" class="hint ok">
              ✓ {{ verifyMsg }}<span v-if="saveMsg"> · {{ saveMsg }}</span>
            </p>
            <p v-else-if="verifyState === 'fail'" class="hint err">
              ✗ {{ verifyMsg }}
            </p>

            <div class="configured-list" v-if="providers.some((p) => p.configured)">
              <h4>{{ t("stConfigured") }}</h4>
              <ul>
                <li v-for="p in providers.filter((x) => x.configured)" :key="p.name">
                  {{ p.label }}
                  <span class="muted">({{ p.models[0] || p.name }})</span>
                </li>
              </ul>
            </div>
          </template>

          <!-- Platform mode: gateway key -->
          <template v-else>
            <div class="gw-intro">
              <b>{{ t("stGwIntro") }}</b>
              <p>{{ t("stGwTag") }}</p>
              <ul class="gw-points">
                <li>{{ t("stGw1") }}</li>
                <li>{{ t("stGw2") }}</li>
                <li>{{ t("stGw3") }}</li>
              </ul>
            </div>

            <div class="field">
              <label>{{ t("stGwKeyLabel") }}</label>
              <textarea
                v-model="platformKey"
                rows="2"
                :placeholder="t('stGwKeyPh')"
              ></textarea>
              <p class="hint">
                {{ t("stNoKey") }}
                <a
                  href="#"
                  class="register-link"
                  @click.prevent="openUrl(registerUrl)"
                >
                  {{ t("stRegisterPre") }}{{
                    config?.region === "global"
                      ? "global.tokeneff.com"
                      : "tokeneff.com"
                  }}{{ t("stRegisterSuf") }}
                </a>
              </p>
            </div>

            <div class="field">
              <label>{{ t("stUrlLabel") }}</label>
              <input
                type="text"
                v-model="platformUrl"
                :placeholder="t('stUrlPh')"
              />
            </div>

            <div class="actions">
              <button
                class="primary"
                :disabled="!platformKey || platformVerifyState === 'verifying'"
                @click="doPlatformVerify"
              >
                {{ platformVerifyState === "verifying" ? t("obVerifying") : t("stVerifySave") }}
              </button>
            </div>

            <p v-if="platformVerifyState === 'ok'" class="hint ok">
              ✓ {{ platformVerifyMsg }}<span v-if="platformSaveMsg"> · {{ platformSaveMsg }}</span>
            </p>
            <p v-else-if="platformVerifyState === 'fail'" class="hint err">
              ✗ {{ platformVerifyMsg }}
            </p>
            <p v-if="config?.has_platform_key" class="hint ok">
              {{ t("stGwConfigured") }}
            </p>
          </template>
        </div>

        <!-- budget -->
        <div v-show="activeTab === 'budget'" class="pane">
          <h3>{{ t("stBudgetTitle") }}</h3>
          <div class="field">
            <label>{{ t("stBudgetLabel") }}</label>
            <input type="number" v-model.number="budget" min="0" step="1" />
          </div>
          <div class="field">
            <label>{{ t("stThreshold") }}: {{ threshold }}%</label>
            <input type="range" v-model.number="threshold" min="10" max="100" step="5" />
          </div>
          <div class="actions">
            <button class="primary" @click="saveBudget">
              {{ budgetSaved ? t("stSaved") : t("stSave") }}
            </button>
          </div>
        </div>

        <!-- region -->
        <div v-show="activeTab === 'region'" class="pane">
          <h3>{{ t("stRegionTitle") }}</h3>

          <!-- 自动判定结果卡片 -->
          <div class="detect-card">
            <div class="detect-line">
              <span class="detect-badge" :class="region === 'cn' ? 'cn' : 'global'">
                {{ region === "cn" ? t("stBadgeCn") : t("stBadgeGlobal") }}
              </span>
              <button
                class="ghost-btn"
                :disabled="regionDetecting"
                @click="redetectRegion(true)"
              >
                {{ regionDetecting ? t("stDetecting") : t("stRedetect") }}
              </button>
            </div>
            <p class="detect-reason" v-if="regionSignals">
              {{ regionSignals.reason }}
            </p>
            <p v-if="regionLocked" class="hint locked-hint">
              {{ t("stLocked") }}
            </p>
            <p class="hint muted">
              {{ t("stRegionHint") }}
            </p>
          </div>

          <!-- 手动覆盖（折叠，出差/VPN 兜底） -->
          <div class="manual-region">
            <button class="link-btn" @click="showManualRegion = !showManualRegion">
              {{ showManualRegion ? "▾" : "▸" }} {{ t("stManualToggle") }}
            </button>
            <div v-if="showManualRegion" class="field radio-group">
              <label>
                <input type="radio" v-model="region" value="cn" /> {{ t("stRadioCn") }}
              </label>
              <label>
                <input type="radio" v-model="region" value="global" /> {{ t("stRadioGlobal") }}
              </label>
              <div class="actions">
                <button class="primary" @click="saveRegion">
                  {{ regionSaved ? t("stSaved") : t("stSaveManual") }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- startup -->
        <div v-show="activeTab === 'startup'" class="pane">
          <h3>{{ t("stStartupTitle") }}</h3>
          <div class="field">
            <label class="switch-row">
              <input
                type="checkbox"
                v-model="autostart"
                :disabled="autostartUnavailable"
                @change="toggleAutostart"
              />
              <span>{{ t("stAutoStartLabel") }}</span>
            </label>
            <p class="hint muted" v-if="autostartUnavailable">
              {{ t("stAutoStartErr") }}
            </p>
            <p class="hint" v-if="autostartMsg" :class="{ err: autostartMsg.startsWith(t('stSetFail')) }">
              {{ autostartMsg }}
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
/* G1 gateway intro card */
.gw-intro {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.gw-intro b {
  color: #fff;
  font-size: 14px;
}
.gw-intro p {
  margin: 4px 0 8px;
  font-size: 12px;
  color: #818cf8;
  font-weight: 600;
}
.gw-points {
  list-style: none;
  margin: 0;
  padding: 0;
}
.gw-points li {
  font-size: 12.5px;
  color: #cbd5e1;
  line-height: 1.8;
}
.hint a,
.register-link {
  color: #818cf8;
  font-weight: 600;
  text-decoration: none;
}
.register-link:hover {
  text-decoration: underline;
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
.detect-card {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 14px;
}
.detect-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.detect-badge {
  font-size: 13px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
}
.detect-badge.cn {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
}
.detect-badge.global {
  background: rgba(59, 130, 246, 0.15);
  color: #93c5fd;
}
.detect-reason {
  font-size: 11px;
  color: #9ca3af;
  margin: 8px 0 6px;
}
.ghost-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #d1d5db;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
}
.ghost-btn:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.4);
}
.ghost-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.manual-region {
  margin-top: 4px;
}
.link-btn {
  background: transparent;
  border: none;
  color: #818cf8;
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.link-btn:hover {
  text-decoration: underline;
}
.locked-hint {
  color: #b45309;
  background: rgba(251, 191, 36, 0.12);
  border-radius: 6px;
  padding: 5px 8px;
}
</style>

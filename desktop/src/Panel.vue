<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import {
  fetchSummary,
  fetchModels,
  fetchConfig,
  currencySymbol,
  fmt,
  type MeterSummary,
  type ModelBreakdown,
} from "./sidecar";
import { initLang, useT } from "./i18n";

const summary = ref<MeterSummary | null>(null);
const models = ref<ModelBreakdown[]>([]);
const connected = ref(false);
const lastUpdate = ref("");
// B3.1: only show "cumulative savings" in platform mode (BYOK saved is always 0; showing it would mislead)
const mode = ref("byok");

let timer: number | undefined;

const t = useT();

const symbol = computed(() =>
  currencySymbol(summary.value?.currency ?? "USD")
);

async function refresh() {
  try {
    const [s, m] = await Promise.all([fetchSummary(), fetchModels()]);
    summary.value = s;
    models.value = m;
    connected.value = true;
    lastUpdate.value = new Date().toLocaleTimeString("en-GB", { hour12: false });
  } catch {
    connected.value = false;
  }
}

onMounted(() => {
  refresh();
  timer = window.setInterval(refresh, 1000);
  // Region (drives language) + mode: both low-frequency, fetched once
  initLang();
  fetchConfig()
    .then((c) => (mode.value = c.mode))
    .catch(() => {});
  // dev 自愈：HMR 断连后 webview 停在旧页面且 hide/show 不重载——
  // 右键面板任意处强制重载（仅调试需要；生产页面来自打包产物不存在此问题）
  window.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    window.location.reload();
  });
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});

async function hidePanel() {
  await getCurrentWindow().hide();
}

/** Open the settings/onboarding window */
async function openSettings() {
  const settings = await WebviewWindow.getByLabel("settings");
  if (settings) {
    await settings.show();
    await settings.setFocus();
  }
}

/** Confidence 0~1 → percentage text */
function confidenceText(c: number | undefined): string {
  if (c === undefined || !Number.isFinite(c)) return "—";
  return `${Math.round(c * 100)}%`;
}

/** Max spend across model rows, used for bar width */
const maxCharged = computed(() => {
  const m = Math.max(...models.value.map((x) => x.charged), 0);
  return m > 0 ? m : 1;
});

/** Budget progress bar: shown when a budget is set; color follows the user's
 * alert threshold (yellow at 3/4 of it, red at/above it) — same logic as the ball */
const budgetBar = computed(() => {
  const s = summary.value;
  if (!s || s.budget_pct === null || !Number.isFinite(s.budget_pct)) return null;
  const pct = Math.min(100, s.budget_pct);
  const thr = s.alert_threshold || 80;
  const color = s.budget_pct >= thr ? "#ef4444" : s.budget_pct >= thr * 0.75 ? "#eab308" : "#22c55e";
  return { pct, color, label: `${s.budget_pct.toFixed(0)}%` };
});
</script>

<template>
  <div class="panel">
    <div class="header" data-tauri-drag-region>
      <span class="title" data-tauri-drag-region>{{ t("panelTitle") }}</span>
      <button class="close" :title="t('collapse')" @click="hidePanel">×</button>
    </div>

    <div v-if="!connected" class="connecting">
      <p>{{ t("connecting") }}</p>
      <p class="hint">{{ t("connectingHint") }}</p>
    </div>

    <template v-else-if="summary">
      <div class="grid">
        <div class="cell">
          <div class="label">{{ t("today") }}</div>
          <div class="value">{{ symbol }}{{ fmt(summary.today) }}</div>
        </div>
        <div class="cell">
          <div class="label">{{ t("month") }}</div>
          <div class="value">{{ symbol }}{{ fmt(summary.month) }}</div>
          <div v-if="budgetBar" class="budget-track">
            <div
              class="budget-fill"
              :style="{ width: budgetBar.pct + '%', background: budgetBar.color }"
            ></div>
          </div>
          <div v-if="budgetBar" class="sub">{{ budgetBar.label }} {{ t("budgetSuffix") }}</div>
        </div>
        <div class="cell">
          <div class="label">{{ t("forecast") }}</div>
          <div class="value">{{ symbol }}{{ fmt(summary.forecast.estimated) }}</div>
          <div class="sub">{{ confidenceText(summary.forecast.confidence) }} {{ t("confidence") }}</div>
        </div>
        <div class="cell" v-if="mode === 'platform'">
          <div class="label">{{ t("saved") }}</div>
          <div class="value saved">{{ symbol }}{{ fmt(summary.saved) }}</div>
        </div>
      </div>

      <div class="rate-row">
        <span class="rate-label">{{ t("rate") }}</span>
        <span class="rate-val">{{ symbol }}{{ fmt(summary.rate_per_min) }}/min</span>
      </div>

      <div class="models">
        <div class="section-title">{{ t("modelDist") }}</div>
        <div v-if="models.length === 0" class="empty">{{ t("noData") }}</div>
        <div v-for="m in models" :key="m.model" class="model-row">
          <div class="model-name" :title="m.model">{{ m.model }}</div>
          <div class="model-bar">
            <div
              class="model-fill"
              :style="{ width: (m.charged / maxCharged) * 100 + '%' }"
            ></div>
          </div>
          <div class="model-charged">{{ symbol }}{{ fmt(m.charged) }}</div>
          <div class="model-tokens">
            {{ (m.input_tokens + m.output_tokens).toLocaleString() }} tok
          </div>
        </div>
      </div>

      <div class="footer">
        <span>{{ t("updatedAt") }} {{ lastUpdate }}</span>
        <button class="settings-btn" :title="t('settings')" @click="openSettings">⚙</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.panel {
  width: 320px;
  height: 420px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(12px);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  padding: 14px;
  color: #1f2937;
  overflow: hidden;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.title {
  font-size: 14px;
  font-weight: 700;
}
.close {
  border: none;
  background: rgba(0, 0, 0, 0.06);
  color: #6b7280;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}
.close:hover {
  background: rgba(0, 0, 0, 0.12);
  color: #1f2937;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.cell {
  background: rgba(0, 0, 0, 0.04);
  border-radius: 10px;
  padding: 8px 10px;
}
.label {
  font-size: 10px;
  color: #6b7280;
  margin-bottom: 2px;
}
.value {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
}
.value.saved {
  color: #16a34a;
}
.sub {
  font-size: 9px;
  color: #9ca3af;
  margin-top: 1px;
}
.budget-track {
  height: 4px;
  background: rgba(0, 0, 0, 0.08);
  border-radius: 2px;
  margin-top: 4px;
  overflow: hidden;
}
.budget-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease, background 0.4s ease;
}
.rate-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 12px 0 8px;
  padding: 8px 10px;
  background: linear-gradient(135deg, #dbeafe, #ede9fe);
  border-radius: 10px;
}
.rate-label {
  font-size: 11px;
  color: #4b5563;
}
.rate-val {
  font-size: 14px;
  font-weight: 700;
  color: #4338ca;
}
.models {
  flex: 1;
  overflow-y: auto;
}
.section-title {
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 6px;
}
.empty {
  font-size: 11px;
  color: #9ca3af;
  text-align: center;
  padding: 16px 0;
}
.model-row {
  display: grid;
  grid-template-columns: 84px 1fr 52px 60px;
  gap: 6px;
  align-items: center;
  font-size: 10px;
  padding: 3px 0;
}
.model-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #374151;
}
.model-bar {
  height: 6px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 3px;
  overflow: hidden;
}
.model-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 3px;
}
.model-charged {
  text-align: right;
  color: #111827;
  font-weight: 600;
}
.model-tokens {
  text-align: right;
  color: #9ca3af;
}
.footer {
  font-size: 9px;
  color: #9ca3af;
  margin-top: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.settings-btn {
  background: transparent;
  border: none;
  color: #9ca3af;
  font-size: 14px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}
.settings-btn:hover {
  color: #818cf8;
}
.connecting {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  font-size: 13px;
}
.connecting .hint {
  font-size: 10px;
  color: #9ca3af;
  margin-top: 6px;
}
</style>

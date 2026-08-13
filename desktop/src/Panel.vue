<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import {
  fetchSummary,
  fetchModels,
  currencySymbol,
  fmt,
  type MeterSummary,
  type ModelBreakdown,
} from "./sidecar";

const summary = ref<MeterSummary | null>(null);
const models = ref<ModelBreakdown[]>([]);
const connected = ref(false);
const lastUpdate = ref("");

let timer: number | undefined;

const symbol = computed(() =>
  currencySymbol(summary.value?.currency ?? "USD")
);

async function refresh() {
  try {
    const [s, m] = await Promise.all([fetchSummary(), fetchModels()]);
    summary.value = s;
    models.value = m;
    connected.value = true;
    lastUpdate.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    connected.value = false;
  }
}

onMounted(() => {
  refresh();
  timer = window.setInterval(refresh, 1000);
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});

async function hidePanel() {
  await getCurrentWindow().hide();
}

/** 打开设置/onboarding 窗口 */
async function openSettings() {
  const settings = await WebviewWindow.getByLabel("settings");
  if (settings) {
    await settings.show();
    await settings.setFocus();
  }
}

/** 置信度 0~1 → 百分比文字 */
function confidenceText(c: number | undefined): string {
  if (c === undefined || !Number.isFinite(c)) return "—";
  return `${Math.round(c * 100)}%`;
}

/** 模型行最大花费，用于条形图宽度 */
const maxCharged = computed(() => {
  const m = Math.max(...models.value.map((x) => x.charged), 0);
  return m > 0 ? m : 1;
});
</script>

<template>
  <div class="panel">
    <div class="header" data-tauri-drag-region>
      <span class="title" data-tauri-drag-region>⚡ tokeneff 电表</span>
      <button class="close" title="收起" @click="hidePanel">×</button>
    </div>

    <div v-if="!connected" class="connecting">
      <p>⚡ 连接 sidecar 中…</p>
      <p class="hint">请确认 7861 端口的 sidecar 已运行</p>
    </div>

    <template v-else-if="summary">
      <div class="grid">
        <div class="cell">
          <div class="label">今日</div>
          <div class="value">{{ symbol }}{{ fmt(summary.today) }}</div>
        </div>
        <div class="cell">
          <div class="label">本月</div>
          <div class="value">{{ symbol }}{{ fmt(summary.month) }}</div>
        </div>
        <div class="cell">
          <div class="label">月终预测</div>
          <div class="value">{{ symbol }}{{ fmt(summary.forecast.estimated) }}</div>
          <div class="sub">{{ confidenceText(summary.forecast.confidence) }} 置信</div>
        </div>
        <div class="cell">
          <div class="label">累计节省</div>
          <div class="value saved">{{ symbol }}{{ fmt(summary.saved) }}</div>
        </div>
      </div>

      <div class="rate-row">
        <span class="rate-label">实时速率</span>
        <span class="rate-val">{{ symbol }}{{ fmt(summary.rate_per_min) }}/min</span>
      </div>

      <div class="models">
        <div class="section-title">今日模型分布</div>
        <div v-if="models.length === 0" class="empty">暂无数据</div>
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
        <span>更新于 {{ lastUpdate }}</span>
        <button class="settings-btn" title="设置" @click="openSettings">⚙</button>
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

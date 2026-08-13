<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import {
  fetchProviders,
  verifyKey,
  saveKey,
  type ProviderInfo,
} from "./sidecar";

const emit = defineEmits<{ done: [] }>();

const step = ref(1); // 1..4
const providers = ref<ProviderInfo[]>([]);
const selProvider = ref("");
const apiKey = ref("");
const loadErr = ref("");

// Verify state
const verifyState = ref<"idle" | "verifying" | "ok" | "fail">("idle");
const verifyMsg = ref("");

// Copy hint
const copied = ref(false);

// Test request state (conversion closed-loop)
const testState = ref<"idle" | "sending" | "ok" | "fail">("idle");
const testMsg = ref("");

const selectedInfo = computed(
  () => providers.value.find((p) => p.name === selProvider.value) ?? null
);

onMounted(async () => {
  try {
    providers.value = await fetchProviders();
  } catch (e) {
    loadErr.value = String(e);
  }
});

// ── Step 2: verify key ────────────────────────────────────────────────────────
async function doVerify() {
  if (!selProvider.value || !apiKey.value) return;
  verifyState.value = "verifying";
  verifyMsg.value = "";
  try {
    const r = await verifyKey(selProvider.value, apiKey.value);
    if (r.ok) {
      // Verify passed → store → go to Step 3
      const s = await saveKey(selProvider.value, apiKey.value);
      if (s.ok) {
        verifyState.value = "ok";
        verifyMsg.value = "Key 有效，已安全存储";
        step.value = 3;
      } else {
        verifyState.value = "fail";
        verifyMsg.value = s.error || "存储失败";
      }
    } else {
      verifyState.value = "fail";
      verifyMsg.value = r.message || "Key 无效";
    }
  } catch (e) {
    verifyState.value = "fail";
    verifyMsg.value = String(e);
  }
}

// ── Step 3: copy proxy address ────────────────────────────────────────────────────
async function copyProxy() {
  try {
    await navigator.clipboard.writeText("http://127.0.0.1:7860");
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    /* clipboard may fail in non-secure contexts, ignore */
  }
}

// ── Step 4: test request (conversion closed-loop validation) ──────────────────────────────────────────
async function sendTestRequest() {
  const model = selectedInfo.value?.models?.[0];
  if (!model) {
    testState.value = "fail";
    testMsg.value = "未找到可用模型";
    return;
  }
  testState.value = "sending";
  testMsg.value = "";
  try {
    // Sent directly to the proxy (7860); the proxy routes upstream, bills, and returns
    const resp = await fetch("http://127.0.0.1:7860/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "hi" }],
        max_tokens: 5,
      }),
    });
    if (resp.ok) {
      testState.value = "ok";
      testMsg.value = "请求成功！悬浮球将在 1-2 秒内显示花费";
    } else {
      const text = await resp.text().catch(() => "");
      testState.value = "fail";
      testMsg.value = `请求失败（${resp.status}）：${text.slice(0, 120)}`;
    }
  } catch (e) {
    testState.value = "fail";
    testMsg.value =
      "无法连接代理（127.0.0.1:7860）。请确认 tokeneff 计费代理已启动。" +
      String(e);
  }
}

function finish() {
  emit("done");
}
</script>

<template>
  <div class="onb-root">
    <!-- progress bar -->
    <div class="progress">
      <div
        v-for="n in 4"
        :key="n"
        class="dot"
        :class="{ active: step >= n, current: step === n }"
      >
        {{ n }}
      </div>
    </div>

    <div v-if="loadErr" class="err-banner">连接 sidecar 失败：{{ loadErr }}</div>

    <!-- Step 1: choose Provider -->
    <div v-if="step === 1" class="step">
      <h2>选择你的 AI Provider</h2>
      <p class="sub">tokeneff 会用你的 API Key 直连上游并计量花费</p>
      <div class="provider-grid">
        <button
          v-for="p in providers"
          :key="p.name"
          class="provider-card"
          :class="{ selected: selProvider === p.name }"
          @click="selProvider = p.name"
        >
          <div class="pc-label">{{ p.label }}</div>
          <div class="pc-model">{{ p.models[0] || p.name }}</div>
        </button>
      </div>
      <div class="step-actions">
        <button class="primary" :disabled="!selProvider" @click="step = 2">
          下一步
        </button>
      </div>
    </div>

    <!-- Step 2: paste Key + verify -->
    <div v-else-if="step === 2" class="step">
      <h2>粘贴 API Key</h2>
      <p class="sub">
        已选 <b>{{ selectedInfo?.label }}</b>。Key 会先验证再存入系统钥匙串（不落盘）。
      </p>
      <textarea
        v-model="apiKey"
        rows="3"
        class="key-input"
        :placeholder="'粘贴 ' + (selectedInfo?.label || '') + ' 的 API Key'"
      ></textarea>
      <p class="hint" v-if="selectedInfo?.name">
        还没有 Key？
        <a
          :href="'https://' + (selectedInfo.name === 'glm' ? 'open.bigmodel.cn/dev/apikeys' : 'platform.openai.com/api-keys')"
          target="_blank"
          >点此获取 →</a
        >
      </p>
      <div class="step-actions">
        <button class="ghost" @click="step = 1">上一步</button>
        <button
          class="primary"
          :disabled="!apiKey || verifyState === 'verifying'"
          @click="doVerify"
        >
          {{ verifyState === "verifying" ? "验证中…" : "验证 Key" }}
        </button>
      </div>
      <p v-if="verifyState === 'ok'" class="hint ok">✓ {{ verifyMsg }}</p>
      <p v-else-if="verifyState === 'fail'" class="hint err">
        ✗ {{ verifyMsg }}（请检查 Key 是否正确）
      </p>
    </div>

    <!-- Step 3: point to proxy -->
    <div v-else-if="step === 3" class="step">
      <h2>将客户端指向代理</h2>
      <p class="sub">
        让你的 LLM 请求经过 tokeneff 计费代理，才能统计花费
      </p>
      <div class="proxy-box">
        <code>http://127.0.0.1:7860</code>
        <button class="ghost small" @click="copyProxy">
          {{ copied ? "已复制 ✓" : "复制" }}
        </button>
      </div>

      <div class="example">
        <div class="ex-title">curl 示例</div>
        <pre>curl http://127.0.0.1:7860/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"{{ selectedInfo?.models[0] || 'gpt-4o-mini' }}","messages":[{"role":"user","content":"hi"}]}'</pre>
      </div>

      <div class="example">
        <div class="ex-title">Python (OpenAI SDK)</div>
        <pre>from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:7860/v1", api_key="any")
client.chat.completions.create(
    model="{{ selectedInfo?.models[0] || 'gpt-4o-mini' }}",
    messages=[{"role":"user","content":"hi"}])</pre>
      </div>

      <div class="step-actions">
        <button class="primary" @click="step = 4">下一步</button>
      </div>
    </div>

    <!-- Step 4: done + test request -->
    <div v-else-if="step === 4" class="step">
      <h2>🎉 配置完成</h2>
      <p class="sub">
        首次请求计费后，悬浮球会显示花费。现在发个测试请求验证一下：
      </p>

      <div class="test-box">
        <button
          class="primary"
          :disabled="testState === 'sending'"
          @click="sendTestRequest"
        >
          {{ testState === "sending" ? "发送中…" : "🚀 发送测试请求" }}
        </button>
        <p v-if="testState === 'ok'" class="hint ok">{{ testMsg }}</p>
        <p v-else-if="testState === 'fail'" class="hint err">{{ testMsg }}</p>
      </div>

      <div class="step-actions">
        <button class="primary" @click="finish">完成</button>
      </div>
      <p class="hint muted">
        日后可在「设置」中修改 Provider、预算等配置
      </p>
    </div>
  </div>
</template>

<style scoped>
.onb-root {
  width: 100%;
  height: 100vh;
  background: #1f2937;
  color: #e5e7eb;
  font-family: -apple-system, "Segoe UI", sans-serif;
  padding: 32px 40px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}
.progress {
  display: flex;
  gap: 8px;
  margin-bottom: 28px;
}
.dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #374151;
  color: #6b7280;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}
.dot.active {
  background: #6366f1;
  color: #fff;
}
.dot.current {
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.3);
}
.step {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.step h2 {
  font-size: 20px;
  color: #fff;
  margin: 0 0 8px;
}
.sub {
  font-size: 13px;
  color: #9ca3af;
  margin: 0 0 20px;
  line-height: 1.5;
}
.err-banner {
  background: #7f1d1d;
  color: #fecaca;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 16px;
}

/* provider cards */
.provider-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
  margin-bottom: 20px;
}
.provider-card {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  text-align: left;
  color: #e5e7eb;
  transition: border-color 0.15s;
}
.provider-card:hover {
  border-color: #6366f1;
}
.provider-card.selected {
  border-color: #6366f1;
  background: #312e81;
}
.pc-label {
  font-size: 14px;
  font-weight: 700;
  color: #fff;
}
.pc-model {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 4px;
}

/* key input */
.key-input {
  width: 100%;
  background: #111827;
  border: 1px solid #374151;
  color: #e5e7eb;
  border-radius: 6px;
  padding: 10px;
  font-size: 13px;
  font-family: monospace;
  box-sizing: border-box;
  resize: vertical;
}

/* proxy address */
.proxy-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #111827;
  border: 1px solid #374151;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 18px;
}
.proxy-box code {
  font-size: 14px;
  color: #818cf8;
  font-weight: 700;
}

/* sample code */
.example {
  margin-bottom: 14px;
}
.ex-title {
  font-size: 11px;
  color: #9ca3af;
  margin-bottom: 4px;
}
.example pre {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 11px;
  color: #a7f3d0;
  overflow-x: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

/* test request */
.test-box {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 16px;
}

/* buttons */
.step-actions {
  margin-top: auto;
  padding-top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
button.primary {
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 9px 22px;
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
button.ghost {
  background: transparent;
  color: #9ca3af;
  border: 1px solid #374151;
  border-radius: 6px;
  padding: 9px 16px;
  font-size: 13px;
  cursor: pointer;
}
button.ghost:hover {
  background: #111827;
  color: #e5e7eb;
}
button.small {
  padding: 5px 12px;
  font-size: 12px;
}
.hint {
  font-size: 12px;
  margin-top: 10px;
}
.hint a {
  color: #818cf8;
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
</style>

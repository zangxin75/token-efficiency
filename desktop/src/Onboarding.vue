<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  fetchProviders,
  verifyKey,
  saveKey,
  detectRegion,
  updateConfig,
  verifyPlatformKey,
  savePlatformKey,
  type ProviderInfo,
} from "./sidecar";
import { initLang, setRegion, useT, useTf } from "./i18n";

const emit = defineEmits<{ done: [] }>();

const t = useT();
const tf = useTf();

// step flow:
//  1  接入方式选择（G1）
//  2  网关注册引导（platform 路径）
//  11 选 provider / 12 贴 key（BYOK 路径，平移自旧 step 1/2）
//  3  指向代理（两条路径收敛）
//  4  测试 + 完成
const step = ref(1);

// access mode (★ G1): "platform" = tokeneff gateway, "byok" = own key
const mode = ref<"platform" | "byok">("platform");

// ★ R3 silent region detection result (no user prompt; program decides)
const detectedRegion = ref<"cn" | "global">("cn");

// providers (BYOK)
const providers = ref<ProviderInfo[]>([]);
const selProvider = ref("");
const apiKey = ref("");
const loadErr = ref("");

// Verify state (BYOK)
const verifyState = ref<"idle" | "verifying" | "ok" | "fail">("idle");
const verifyMsg = ref("");

// ★ G1 platform key state
const platformKey = ref("");
const platformState = ref<"idle" | "verifying" | "ok" | "fail">("idle");
const platformMsg = ref("");

// Copy hint
const copied = ref(false);

// Test request state (conversion closed-loop)
const testState = ref<"idle" | "sending" | "ok" | "fail">("idle");
const testMsg = ref("");

const selectedInfo = computed(
  () => providers.value.find((p) => p.name === selProvider.value) ?? null
);

// ★ G1 register URL by region (cn→tokeneff.com, global→global.tokeneff.com)
const registerUrl = computed(
  () =>
    detectedRegion.value === "cn"
      ? "https://tokeneff.com/register?source=tokeneff-cli"
      : "https://global.tokeneff.com/register?source=tokeneff-cli"
);

// progress dot index (1..4); BYOK sub-steps 11/12 map to dot 1/2
const progressIndex = computed(() =>
  step.value >= 11 ? step.value - 10 : step.value
);

onMounted(async () => {
  initLang();
  // ★ R3 silent region detection — program decides, never asks the user
  // (consistent with website geo.js / CLI wizard). Falls back to cn on failure.
  try {
    const sig = await detectRegion();
    detectedRegion.value =
      sig.recommended ?? (sig.locale.startsWith("zh") ? "cn" : "global");
  } catch {
    detectedRegion.value = "cn";
  }
  // 检测到 global 时本窗口立即切英文（settings 窗口其余部分由 initLang 的
  // fetchConfig 兜底；这里不等 fetchConfig 是为了探测完成后立刻切，不等第二次网络往返）
  setRegion(detectedRegion.value);
  // persist region OUTSIDE the detect try: even if detection timed out, the
  // backend region/platform_url must match what this UI shows, or the register
  // link and key verification would hit different gateways
  try {
    // region_manual:false — onboarding detection is automatic, must not
    // inherit/carry a manual-override lock from a previous session
    await updateConfig({ region: detectedRegion.value, region_manual: false });
  } catch {
    /* sidecar unreachable: nothing to sync, defaults already loaded */
  }

  try {
    providers.value = await fetchProviders();
  } catch (e) {
    loadErr.value = String(e);
  }
});

// ── Step 1: choose access mode (G1) ───────────────────────────────────────────
function choosePlatform() {
  mode.value = "platform";
  step.value = 2;
}
function chooseByok() {
  mode.value = "byok";
  step.value = 11;
}

// ── Step 2: platform gateway key verify + save (G1) ───────────────────────────
async function verifyAndSavePlatform() {
  if (!platformKey.value) return;
  platformState.value = "verifying";
  platformMsg.value = "";
  try {
    const v = await verifyPlatformKey(platformKey.value);
    if (!v.ok) {
      platformState.value = "fail";
      platformMsg.value = v.message || t.value("obKeyInvalid");
      return;
    }
    const s = await savePlatformKey(platformKey.value);
    if (!s.ok) {
      platformState.value = "fail";
      platformMsg.value = s.error || t.value("obStoreFail");
      return;
    }
    // switch to platform mode
    await updateConfig({ mode: "platform" });
    platformState.value = "ok";
    platformMsg.value = t.value("obPlatformOk");
    setTimeout(() => {
      // guard: user may have clicked "返回" during the 800ms window
      if (platformState.value === "ok") step.value = 3;
    }, 800);
  } catch (e) {
    platformState.value = "fail";
    platformMsg.value = t.value("obVerifyFail") + String(e);
  }
}

// ── Step 12: BYOK verify key ──────────────────────────────────────────────────
async function doVerify() {
  if (!selProvider.value || !apiKey.value) return;
  verifyState.value = "verifying";
  verifyMsg.value = "";
  try {
    const r = await verifyKey(selProvider.value, apiKey.value);
    if (r.ok) {
      const s = await saveKey(selProvider.value, apiKey.value);
      if (s.ok) {
        verifyState.value = "ok";
        verifyMsg.value = t.value("obKeyOkStored");
        await updateConfig({ mode: "byok" });
        step.value = 3;
      } else {
        verifyState.value = "fail";
        verifyMsg.value = s.error || t.value("obStoreFail");
      }
    } else {
      verifyState.value = "fail";
      verifyMsg.value = r.message || t.value("obKeyInvalid");
    }
  } catch (e) {
    verifyState.value = "fail";
    verifyMsg.value = String(e);
  }
}

// ── Step 3: copy proxy address ────────────────────────────────────────────────
async function copyProxy() {
  try {
    await navigator.clipboard.writeText("http://127.0.0.1:7860");
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    /* clipboard may fail in non-secure contexts, ignore */
  }
}

// ── Step 4: test request (conversion closed-loop validation) ──────────────────
async function sendTestRequest() {
  // platform mode has no selectedInfo; use a gateway model name
  const model =
    mode.value === "platform"
      ? "gpt-4o-mini"
      : selectedInfo.value?.models?.[0];
  if (!model) {
    testState.value = "fail";
    testMsg.value = t.value("obNoModel");
    return;
  }
  testState.value = "sending";
  testMsg.value = "";
  try {
    const resp = await fetch("http://127.0.0.1:7860/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // the proxy's upstream timeout is 300s — without a client-side cap the
      // button can sit on "sending" for minutes when the upstream hangs
      signal: AbortSignal.timeout(30000),
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "hi" }],
        max_tokens: 5,
      }),
    });
    if (resp.ok) {
      testState.value = "ok";
      testMsg.value = t.value("obTestOk");
    } else {
      const text = await resp.text().catch(() => "");
      testState.value = "fail";
      testMsg.value = tf.value("obTestFail", [resp.status, text.slice(0, 120)]);
    }
  } catch (e) {
    testState.value = "fail";
    testMsg.value = t.value("obTestConnFail") + String(e);
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
        :class="{ active: progressIndex >= n, current: progressIndex === n }"
      >
        {{ n }}
      </div>
    </div>

    <div v-if="loadErr" class="err-banner">{{ t("obConnFail") }}{{ loadErr }}</div>

    <!-- Step 1: choose access mode (G1) -->
    <div v-if="step === 1" class="step">
      <h2>{{ t("obQ") }}</h2>
      <p class="sub">
        {{ t("obRegionDetected") }}<b>{{ detectedRegion === "cn" ? t("obCn") : t("obOverseas") }}</b>
      </p>
      <div class="mode-cards">
        <div class="mode-card recommended" @click="choosePlatform">
          <span class="rec-badge">{{ t("obRecommended") }}</span>
          <div class="mode-icon">🚀</div>
          <div class="mode-title">{{ t("obMode1Title") }}</div>
          <div class="mode-tagline">{{ t("obMode1Tag") }}</div>
          <div class="mode-desc">
            {{ t("obMode1Desc") }}
          </div>
        </div>
        <div class="mode-card" @click="chooseByok">
          <div class="mode-icon">🔑</div>
          <div class="mode-title">{{ t("obMode2Title") }}</div>
          <div class="mode-desc">{{ t("obMode2Desc") }}</div>
        </div>
      </div>
    </div>

    <!-- Step 2: platform gateway registration guide (G1) -->
    <div v-else-if="step === 2" class="step">
      <h2>{{ t("obStep2Title") }}</h2>
      <p class="sub">{{ t("obStep2Sub") }}</p>
      <div class="selling-points">
        <div class="sp">
          <span class="sp-icon">👀</span>
          <div>
            <b>{{ t("obSp1B") }}</b> {{ t("obSp1") }}
          </div>
        </div>
        <div class="sp">
          <span class="sp-icon">💰</span>
          <div>
            <b>{{ t("obSp2B") }}</b> {{ t("obSp2") }}
          </div>
        </div>
        <div class="sp">
          <span class="sp-icon">⚡</span>
          <div>
            <b>{{ t("obSp3B") }}</b> {{ t("obSp3") }}
          </div>
        </div>
      </div>
      <ol class="reg-steps">
        <li>
          {{ t("obReg1Pre") }}{{
            detectedRegion === "cn" ? t("obCn") : t("obOverseas")
          }}{{ t("obReg1Suf") }}
          <a
            href="#"
            class="register-link"
            @click.prevent="openUrl(registerUrl)"
          >
            {{ t("obOpen") }}
            {{
              detectedRegion === "cn"
                ? "tokeneff.com/register"
                : "global.tokeneff.com/register"
            }}
          </a>
        </li>
        <li>{{ t("obReg2") }}</li>
        <li>{{ t("obReg3") }}</li>
      </ol>
      <input
        v-model="platformKey"
        class="key-input"
        placeholder="sk-tf-..."
        @keyup.enter="verifyAndSavePlatform"
      />
      <div class="step-actions">
        <button class="ghost" @click="step = 1">{{ t("obBack") }}</button>
        <button
          class="primary"
          :disabled="!platformKey || platformState === 'verifying'"
          @click="verifyAndSavePlatform"
        >
          {{ platformState === "verifying" ? t("obVerifying") : t("obFreeOpen") }}
        </button>
      </div>
      <p v-if="platformState === 'ok'" class="hint ok">✓ {{ platformMsg }}</p>
      <p v-else-if="platformState === 'fail'" class="hint err">
        ✗ {{ platformMsg }}
      </p>
      <p class="have-key">
        {{ t("obHaveAccountPre") }}
        <a href="#" @click.prevent="chooseByok">{{ t("obSwitchByok") }}</a>
      </p>
    </div>

    <!-- Step 11: BYOK choose Provider -->
    <div v-else-if="step === 11" class="step">
      <h2>{{ t("obStep11Title") }}</h2>
      <p class="sub">{{ t("obStep11Sub") }}</p>
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
        <button class="ghost" @click="step = 1">{{ t("obPrev") }}</button>
        <button class="primary" :disabled="!selProvider" @click="step = 12">
          {{ t("obNext") }}
        </button>
      </div>
    </div>

    <!-- Step 12: BYOK paste Key + verify -->
    <div v-else-if="step === 12" class="step">
      <h2>{{ t("obStep12Title") }}</h2>
      <p class="sub">
        {{ t("obStep12SubPre") }} <b>{{ selectedInfo?.label }}</b>{{ t("obStep12SubSuf") }}
      </p>
      <textarea
        v-model="apiKey"
        rows="3"
        class="key-input"
        :placeholder="t('obPastePre') + (selectedInfo?.label || '') + t('obPasteSuf')"
      ></textarea>
      <p class="hint" v-if="selectedInfo?.name">
        {{ t("obNoKey") }}
        <a
          href="#"
          @click.prevent="
            openUrl(
              selectedInfo.name === 'glm'
                ? 'https://open.bigmodel.cn/dev/apikeys'
                : 'https://platform.openai.com/api-keys'
            )
          "
          >{{ t("obGetKey") }}</a
        >
      </p>
      <div class="step-actions">
        <button class="ghost" @click="step = 11">{{ t("obPrev") }}</button>
        <button
          class="primary"
          :disabled="!apiKey || verifyState === 'verifying'"
          @click="doVerify"
        >
          {{ verifyState === "verifying" ? t("obVerifying") : t("obVerifyKey") }}
        </button>
      </div>
      <p v-if="verifyState === 'ok'" class="hint ok">✓ {{ verifyMsg }}</p>
      <p v-else-if="verifyState === 'fail'" class="hint err">
        ✗ {{ verifyMsg }}{{ t("obKeyCheckHint") }}
      </p>
    </div>

    <!-- Step 3: point to proxy -->
    <div v-else-if="step === 3" class="step">
      <h2>{{ t("obStep3Title") }}</h2>
      <p class="sub">{{ t("obStep3Sub") }}</p>
      <div class="proxy-box">
        <code>http://127.0.0.1:7860</code>
        <button class="ghost small" @click="copyProxy">
          {{ copied ? t("obCopied") : t("obCopy") }}
        </button>
      </div>

      <div class="example">
        <div class="ex-title">{{ t("obCurlEx") }}</div>
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
        <button class="ghost" @click="step = mode === 'platform' ? 2 : 12">
          {{ t("obPrev") }}
        </button>
        <button class="primary" @click="step = 4">{{ t("obNext") }}</button>
      </div>
    </div>

    <!-- Step 4: done + test request -->
    <div v-else-if="step === 4" class="step">
      <h2>{{ t("obStep4Title") }}</h2>
      <p class="sub">
        {{ mode === "platform" ? t("obStep4SubPlatform") : t("obStep4SubByok") }}
      </p>

      <div class="test-box">
        <button
          class="primary"
          :disabled="testState === 'sending'"
          @click="sendTestRequest"
        >
          {{ testState === "sending" ? t("obSending") : t("obSendTest") }}
        </button>
        <p v-if="testState === 'ok'" class="hint ok">{{ testMsg }}</p>
        <p v-else-if="testState === 'fail'" class="hint err">{{ testMsg }}</p>
      </div>

      <div class="step-actions">
        <button class="primary" @click="finish">{{ t("obDone") }}</button>
      </div>
      <p class="hint muted">{{ t("obLaterHint") }}</p>
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

/* access-mode cards (G1) */
.mode-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}
.mode-card {
  flex: 1;
  padding: 22px 18px;
  background: #111827;
  border: 2px solid #374151;
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
  text-align: center;
  position: relative;
}
.mode-card:hover {
  border-color: #6366f1;
  transform: translateY(-2px);
}
.mode-card.recommended {
  border-color: #6366f1;
  background: #312e81;
}
.mode-card.recommended::after {
  content: "";
}.rec-badge {
  position: absolute;
  top: -10px;
  right: 12px;
  background: #6366f1;
  color: #fff;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
}
.mode-icon {
  font-size: 2rem;
  margin-bottom: 8px;
}
.mode-title {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 4px;
}
.mode-tagline {
  font-size: 12px;
  color: #818cf8;
  font-weight: 600;
  margin-bottom: 6px;
}
.mode-desc {
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.5;
}

/* selling points (G1) */
.selling-points {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #111827;
  border: 1px solid #374151;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.sp {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12.5px;
  color: #cbd5e1;
  line-height: 1.5;
}
.sp-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.sp b {
  color: #fff;
  margin-right: 4px;
}

/* registration guide (G1) */
.reg-steps {
  margin: 0 0 16px;
  padding-left: 20px;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 2;
}
.register-link {
  display: inline-block;
  color: #818cf8;
  font-weight: 600;
  margin-left: 6px;
}
.register-link:hover {
  text-decoration: underline;
}
.have-key {
  margin-top: 14px;
  font-size: 12px;
  color: #9ca3af;
}
.have-key a {
  color: #818cf8;
}
</style>

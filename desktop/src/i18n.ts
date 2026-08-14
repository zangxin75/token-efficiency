import type { Ref } from "vue";
import { computed, ref } from "vue";
import { fetchConfig } from "./sidecar";
import { emit as tauriEmit, listen } from "@tauri-apps/api/event";

/**
 * 轻量区域双语：global 区域 → 全英文，cn 区域 → 中文。
 * 以 region（用户/自动判定结果）为准，而非系统 locale——
 * 海外华人系统是中文 locale 但走 global 站，应看到英文。
 * 不引 vue-i18n：文案量小（<40 条），一个字典 + computed 即够。
 *
 * 窗口同步：Tauri 各 webview 的模块状态独立（球/面板/设置不共享内存），
 * region 变化通过全局事件 "region-changed" 广播——设置窗口 emit，
 * initLang 的监听器收到后刷新本窗口语言，无需重启窗口。
 */

const region = ref<string>("cn");
let listening = false;

export function initLang(): void {
  fetchConfig()
    .then((c) => (region.value = c.region || "cn"))
    .catch(() => {});
  if (!listening) {
    listening = true;
    listen<string>("region-changed", (e) => {
      region.value = e.payload || "cn";
    }).catch(() => {});
  }
}

export function setRegion(r: string): void {
  region.value = r || "cn";
  tauriEmit("region-changed", region.value).catch(() => {});
}

export const isEn = computed(() => region.value === "global");

type Dict = Record<string, { zh: string; en: string }>;

const DICT: Dict = {
  // Panel（电表面板）
  panelTitle: { zh: "⚡ tokeneff 电表", en: "⚡ tokeneff Meter" },
  collapse: { zh: "收起", en: "Collapse" },
  connecting: { zh: "⚡ 连接 sidecar 中…", en: "⚡ Connecting to sidecar…" },
  connectingHint: {
    zh: "请确认 7861 端口的 sidecar 已运行",
    en: "Make sure the sidecar is running on port 7861",
  },
  today: { zh: "今日", en: "Today" },
  month: { zh: "本月", en: "This Month" },
  forecast: { zh: "月终预测", en: "Month Forecast" },
  saved: { zh: "累计节省", en: "Total Saved" },
  budgetSuffix: { zh: "预算", en: "budget" },
  confidence: { zh: "置信", en: "confidence" },
  rate: { zh: "实时速率", en: "Live Rate" },
  modelDist: { zh: "今日模型分布", en: "Today's Model Breakdown" },
  noData: { zh: "暂无数据", en: "No data yet" },
  updatedAt: { zh: "更新于", en: "Updated" },
  settings: { zh: "设置", en: "Settings" },
  // Ball（悬浮球）
  ballConnecting: { zh: "连接中", en: "Connecting" },
  watchdogGivenUp: { zh: "守护已停止", en: "Watchdog stopped" },

  // ── Onboarding（首次引导）─────────────────────────────────────────────
  obConnFail: { zh: "连接 sidecar 失败：", en: "Failed to connect to sidecar: " },
  obQ: { zh: "你想怎么用电表？", en: "How do you want to use the meter?" },
  obRegionDetected: { zh: "区域已自动识别：", en: "Region auto-detected: " },
  obCn: { zh: "中国大陆", en: "Mainland China" },
  obOverseas: { zh: "海外", en: "Overseas" },
  obMode1Title: {
    zh: "先看清花了多少，再便宜地花",
    en: "See your spend first, then spend less",
  },
  obMode1Tag: {
    zh: "tokeneff = AI 电表 + 批发网关",
    en: "tokeneff = AI meter + wholesale gateway",
  },
  obMode1Desc: {
    zh: "先让花费透明可见，再用批发价省下来",
    en: "Make every spend visible, then save at wholesale prices",
  },
  obMode2Title: { zh: "用我自己的 key（BYOK）", en: "Use my own key (BYOK)" },
  obMode2Desc: {
    zh: "免费直连，0 加价，key 不离开本机",
    en: "Free direct connection, zero markup, key never leaves your machine",
  },
  obRecommended: { zh: "推荐", en: "Recommended" },
  obStep2Title: { zh: "开通 tokeneff 网关", en: "Set up the tokeneff gateway" },
  obStep2Sub: {
    zh: "tokeneff = AI 电表 + 批发网关。先让花费透明可见，再用批发价省下来。",
    en: "tokeneff = AI meter + wholesale gateway. Make every spend visible, then save at wholesale prices.",
  },
  obSp1B: { zh: "看得见", en: "See it" },
  obSp1: {
    zh: "悬浮球实时计量每次调用，告别盲盒账单",
    en: "the ball meters every call in real time — no more mystery bills",
  },
  obSp2B: { zh: "便宜", en: "Cheaper" },
  obSp2: {
    zh: "网关批发价比官方省 33-88%，首月免费",
    en: "wholesale gateway prices save 33–88% vs official, first month free",
  },
  obSp3B: { zh: "省心", en: "Effortless" },
  obSp3: {
    zh: "一个 key 通吃 GPT / Claude / GLM，即开即用",
    en: "one key for GPT / Claude / GLM, works out of the box",
  },
  obReg1Pre: { zh: "点击打开注册页（", en: "Open the registration page (" },
  obReg1Suf: { zh: "）：", en: "):" },
  obOpen: { zh: "🌐 打开", en: "🌐 Open" },
  obReg2: {
    zh: "注册后在「API Keys」页创建一个 key",
    en: "After signing up, create a key on the \"API Keys\" page",
  },
  obReg3: { zh: "复制 key，粘贴到下面：", en: "Copy the key and paste it below:" },
  obBack: { zh: "返回", en: "Back" },
  obVerifying: { zh: "验证中…", en: "Verifying…" },
  obFreeOpen: { zh: "免费开通网关 →", en: "Open gateway free →" },
  obHaveAccountPre: {
    zh: "已有账号？直接粘贴 key 即可，或",
    en: "Already have an account? Just paste your key, or",
  },
  obSwitchByok: { zh: "改用 BYOK →", en: "switch to BYOK →" },
  obStep11Title: { zh: "选择你的 AI Provider", en: "Choose your AI provider" },
  obStep11Sub: {
    zh: "tokeneff 会用你的 API Key 直连上游并计量花费",
    en: "tokeneff connects straight to the upstream with your API key and meters the spend",
  },
  obPrev: { zh: "上一步", en: "Back" },
  obNext: { zh: "下一步", en: "Next" },
  obStep12Title: { zh: "粘贴 API Key", en: "Paste your API key" },
  obStep12SubPre: { zh: "已选", en: "Selected" },
  obStep12SubSuf: {
    zh: "。Key 会先验证再存入系统钥匙串（不落盘）。",
    en: ". The key is verified first, then stored in the system keychain (never written to disk).",
  },
  obPastePre: { zh: "粘贴 ", en: "Paste " },
  obPasteSuf: { zh: " 的 API Key", en: "'s API key" },
  obNoKey: { zh: "还没有 Key？", en: "No key yet?" },
  obGetKey: { zh: "点此获取 →", en: "Get one here →" },
  obVerifyKey: { zh: "验证 Key", en: "Verify key" },
  obKeyCheckHint: {
    zh: "（请检查 Key 是否正确）",
    en: " (check that the key is correct)",
  },
  obStep3Title: { zh: "将客户端指向代理", en: "Point your client at the proxy" },
  obStep3Sub: {
    zh: "让你的 LLM 请求经过 tokeneff 计费代理，才能统计花费",
    en: "Route your LLM requests through the tokeneff metering proxy to track spend",
  },
  obCopied: { zh: "已复制 ✓", en: "Copied ✓" },
  obCopy: { zh: "复制", en: "Copy" },
  obCurlEx: { zh: "curl 示例", en: "curl example" },
  obStep4Title: { zh: "🎉 配置完成", en: "🎉 All set" },
  obStep4SubPlatform: {
    zh: "已切换到网关模式。首次请求计费后，悬浮球会显示花费。发个测试请求验证一下：",
    en: "Switched to gateway mode. After your first metered request the ball shows the spend. Send a test request to verify:",
  },
  obStep4SubByok: {
    zh: "首次请求计费后，悬浮球会显示花费。现在发个测试请求验证一下：",
    en: "After your first metered request the ball shows the spend. Send a test request now to verify:",
  },
  obSending: { zh: "发送中…", en: "Sending…" },
  obSendTest: { zh: "🚀 发送测试请求", en: "🚀 Send test request" },
  obDone: { zh: "完成", en: "Done" },
  obLaterHint: {
    zh: "日后可在「设置」中修改 Provider、预算等配置",
    en: "You can change providers, budget and more later in Settings",
  },
  // Onboarding 脚本内状态消息
  obKeyInvalid: { zh: "key 无效", en: "key invalid" },
  obStoreFail: { zh: "存储失败", en: "failed to store" },
  obPlatformOk: {
    zh: "网关 key 有效，已切换到平台模式",
    en: "Gateway key valid, switched to platform mode",
  },
  obVerifyFail: { zh: "验证失败: ", en: "Verify failed: " },
  obKeyOkStored: { zh: "Key 有效，已安全存储", en: "Key valid, stored securely" },
  obNoModel: { zh: "未找到可用模型", en: "No usable model found" },
  obTestOk: {
    zh: "请求成功！悬浮球将在 1-2 秒内显示花费",
    en: "Request succeeded! The ball will show the spend within 1–2 seconds",
  },
  obTestFail: {
    zh: "请求失败（{0}）：{1}",
    en: "Request failed ({0}): {1}",
  },
  obTestConnFail: {
    zh: "无法连接代理（127.0.0.1:7860）。请确认 tokeneff 计费代理已启动。",
    en: "Cannot reach the proxy (127.0.0.1:7860). Make sure the tokeneff metering proxy is running. ",
  },

  // ── Settings（设置页）─────────────────────────────────────────────────
  stConnFail: { zh: "连接 sidecar 失败：", en: "Failed to connect to sidecar: " },
  stLoading: { zh: "⚡ 加载配置中…", en: "⚡ Loading config…" },
  stTabBudget: { zh: "预算", en: "Budget" },
  stTabRegion: { zh: "区域", en: "Region" },
  stTabStartup: { zh: "启动", en: "Startup" },
  stProviderTitle: { zh: "API Provider 管理", en: "API provider management" },
  stAccessMode: { zh: "接入模式", en: "Access mode" },
  stByokTitle: { zh: "自带 Key（BYOK）", en: "Bring your own key (BYOK)" },
  stByokDesc: {
    zh: "用你自己的 provider key（GLM/OpenAI 等），直连上游",
    en: "Use your own provider key (GLM/OpenAI etc.), direct upstream connection",
  },
  stPlatformTitle: { zh: "tokeneff 网关", en: "tokeneff gateway" },
  stPlatformDesc: {
    zh: "用一个网关 key 通吃多模型，按量计费享批发价",
    en: "One gateway key for all models, pay-as-you-go at wholesale prices",
  },
  stSelectProvider: { zh: "选择 Provider", en: "Select provider" },
  stSelectPh: { zh: "请选择…", en: "Select…" },
  stApiKeyLabel: { zh: "API Key", en: "API key" },
  stVerifySave: { zh: "验证并保存", en: "Verify & save" },
  stConfigured: { zh: "已配置", en: "Configured" },
  stGwIntro: { zh: "tokeneff = AI 电表 + 批发网关", en: "tokeneff = AI meter + wholesale gateway" },
  stGwTag: { zh: "看得见 · 省钱 · 省心", en: "See it · Save · Effortless" },
  stGw1: {
    zh: "👀 悬浮球实时计量，告别盲盒账单",
    en: "👀 Real-time metering on the ball — no more mystery bills",
  },
  stGw2: {
    zh: "💰 批发价比官方省 33-88%，首月免费",
    en: "💰 Wholesale prices save 33–88% vs official, first month free",
  },
  stGw3: {
    zh: "⚡ 一个 key 通吃 GPT / Claude / GLM",
    en: "⚡ One key for GPT / Claude / GLM",
  },
  stGwKeyLabel: { zh: "tokeneff 网关 API Key", en: "tokeneff gateway API key" },
  stGwKeyPh: {
    zh: "粘贴从 tokeneff 网关获取的 API Key",
    en: "Paste the API key from the tokeneff gateway",
  },
  stNoKey: { zh: "没有 key？", en: "No key?" },
  stRegisterPre: { zh: "🌐 点击注册（", en: "🌐 Register (" },
  stRegisterSuf: { zh: "）→", en: ") →" },
  stUrlLabel: { zh: "网关地址（可选）", en: "Gateway URL (optional)" },
  stUrlPh: {
    zh: "留空用默认（tokeneff.com / global.tokeneff.com）",
    en: "Leave empty for default (tokeneff.com / global.tokeneff.com)",
  },
  stGwConfigured: { zh: "✓ 已配置网关 key", en: "✓ Gateway key configured" },
  stBudgetTitle: { zh: "月度预算", en: "Monthly budget" },
  stBudgetLabel: { zh: "预算金额（USD）", en: "Budget amount (USD)" },
  stThreshold: { zh: "告警阈值", en: "Alert threshold" },
  stSave: { zh: "保存", en: "Save" },
  stSaved: { zh: "已保存 ✓", en: "Saved ✓" },
  stRegionTitle: { zh: "区域与币种", en: "Region & currency" },
  stBadgeCn: { zh: "中国大陆站（CNY ¥）", en: "China site (CNY ¥)" },
  stBadgeGlobal: { zh: "全球站（USD $）", en: "Global site (USD $)" },
  stDetecting: { zh: "检测中…", en: "Detecting…" },
  stRedetect: { zh: "重新检测", en: "Re-detect" },
  stLocked: {
    zh: "🔒 已手动锁定区域，自动检测不再改写。点\"重新检测\"可恢复自动跟随",
    en: "🔒 Region locked manually — auto-detection won't overwrite it. Click \"Re-detect\" to resume auto",
  },
  stRegionHint: {
    zh: "按地理位置自动选择站点（时区为主、IP 为辅，防 VPN 误判），区域影响计费币种与网关地址",
    en: "Site chosen by location (timezone first, IP second, VPN-resistant); region drives billing currency and gateway URL",
  },
  stManualToggle: {
    zh: "手动选择区域（出差或需要覆盖自动判定时）",
    en: "Choose region manually (traveling or overriding auto-detection)",
  },
  stRadioCn: { zh: "中国大陆（CNY ¥）", en: "Mainland China (CNY ¥)" },
  stRadioGlobal: { zh: "全球（USD $）", en: "Global (USD $)" },
  stSaveManual: { zh: "保存手动选择", en: "Save manual choice" },
  stStartupTitle: { zh: "开机自启", en: "Start on login" },
  stAutoStartLabel: {
    zh: "登录时自动启动 tokeneff",
    en: "Launch tokeneff automatically on login",
  },
  stAutoStartErr: {
    zh: "（无法访问自启动注册表，请检查系统权限）",
    en: "(Cannot access the autostart registry — check system permissions)",
  },
  stSetFail: { zh: "设置失败：", en: "Failed to set: " },
  // Settings 脚本内状态消息
  stGwKeyValid: { zh: "网关 key 有效", en: "Gateway key valid" },
  stVerifiedStored: { zh: "已验证并存储", en: "verified & stored" },
  stStoreFail: { zh: "存储失败", en: "Failed to store" },
  stVerifyFail: { zh: "验证失败", en: "Verify failed" },
  stKeyValid: { zh: "Key 有效", en: "Key valid" },
};

export function useT(): Ref<(key: keyof typeof DICT) => string> {
  return computed(() => (key: keyof typeof DICT) =>
    isEn.value ? DICT[key].en : DICT[key].zh
  ) as Ref<(key: keyof typeof DICT) => string>;
}

/** 带参数文案：t("obTestFail", [status, text]) 依次替换 {0} {1} */
export function useTf(): Ref<
  (key: keyof typeof DICT, args?: (string | number)[]) => string
> {
  return computed(() => (key: keyof typeof DICT, args?: (string | number)[]) => {
    let s = isEn.value ? DICT[key].en : DICT[key].zh;
    args?.forEach((a, i) => {
      s = s.replace(`{${i}}`, String(a));
    });
    return s;
  }) as Ref<(key: keyof typeof DICT, args?: (string | number)[]) => string>;
}

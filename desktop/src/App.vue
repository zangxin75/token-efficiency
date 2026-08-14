<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { getCurrentWindow, currentMonitor } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { LogicalPosition } from "@tauri-apps/api/dpi";
// outerPosition / currentMonitor return physical pixels; use PhysicalPosition to avoid scaling miscalculation
import { PhysicalPosition } from "@tauri-apps/api/dpi";
import {
  fetchSummary,
  fetchConfig,
  currencySymbol,
  fmt,
  discoverSidecarPort,
  installSidecarRecovery,
  type MeterSummary,
} from "./sidecar";
import { detectForm } from "./platform";
import { initLang, useT } from "./i18n";

const today = ref(0);
const rate = ref(0);
const budgetPct = ref<number | null>(null);
const threshold = ref(80);
const currency = ref("USD");
const connected = ref(false);

let timer: number | undefined;
// Drag vs click discrimination: mousedown only records coordinates; mousemove beyond threshold starts system drag.
// Otherwise startDragging enters a modal drag loop that swallows click, preventing the panel from expanding.
let downX = 0;
let downY = 0;
let dragStarted = false;
// First-launch onboarding check guard, prevents repeated popups
let onboardingChecked = false;

const symbol = computed(() => currencySymbol(currency.value));

const t = useT();

/** Color logic follows the user's alert threshold (Settings): yellow from 3/4 of
 * the threshold, red at/above it; no budget set or below → green; offline → gray */
function ballColor(): string {
  if (!connected.value) return "#9ca3af";
  if (budgetPct.value === null) return "#22c55e";
  if (budgetPct.value >= threshold.value) return "#ef4444";
  if (budgetPct.value >= threshold.value * 0.75) return "#eab308";
  return "#22c55e";
}

async function refresh() {
  try {
    const d: MeterSummary = await fetchSummary();
    today.value = d.today;
    rate.value = d.rate_per_min;
    budgetPct.value = d.budget_pct;
    threshold.value = d.alert_threshold || 80;
    currency.value = d.currency;
    connected.value = true;
  } catch {
    connected.value = false;
  }
}

// B4: platform interaction form (ball/tray). Windows is always ball; in tray form (Linux Wayland)
// the floating ball should theoretically be hidden in favor of the tray, but the primary scenario here is ball — this is recorded for a future Linux branch.
const form = ref<"ball" | "tray">("ball");
// B4: sidecar crash-watchdog event listener (Rust watchdog emits "sidecar-status")
// "down" = transient (watchdog restarting sidecar); "given-up" = terminal (restart budget exhausted)
const givenUp = ref(false);
let statusUnlisten: (() => void) | undefined;

onMounted(() => {
  // ★ port-drift fix: learn the sidecar's actual port before first poll
  discoverSidecarPort().then(() => refresh());
  installSidecarRecovery();
  timer = window.setInterval(refresh, 1000);
  initLang();
  checkOnboarding();
  // Platform detection
  detectForm().then((f) => {
    form.value = f;
    // tray form (Linux Wayland) hides the floating ball, deferring to the system tray
    if (f === "tray") {
      getCurrentWindow().hide().catch(() => {});
    }
  });
  // Listen for Rust crash-watchdog events: down → gray ball connecting, up → refresh immediately to recover
  getCurrentWindow()
    .listen<string>("sidecar-status", (event) => {
      const status = event.payload;
      if (status === "down") {
        connected.value = false;
      } else if (status === "given-up") {
        // watchdog exhausted its restart budget — self-healing stopped;
        // a later "up" (e.g. user restarted the app) still clears this
        connected.value = false;
        givenUp.value = true;
      } else if (status === "up") {
        connected.value = true;
        givenUp.value = false;
        refresh();
      }
    })
    .then((un) => {
      statusUnlisten = un;
    })
    .catch(() => {});
});

/** First-launch check: mode-aware onboarding trigger (mirrors Settings.vue logic).
 * BYOK with no provider key, or platform with no gateway key → open settings. */
async function checkOnboarding() {
  if (onboardingChecked) return;
  onboardingChecked = true;
  try {
    const cfg = await fetchConfig();
    // ★ contract fix: the old check only looked at providers_configured, so
    // platform-mode users (gateway key, no BYOK keys) were re-onboarded every launch
    const byokEmpty = (cfg.providers_configured?.length ?? 0) === 0;
    const platformEmpty = !cfg.has_platform_key;
    const needs =
      (cfg.mode === "platform" && platformEmpty) ||
      (cfg.mode !== "platform" && byokEmpty);
    if (needs) {
      const settings = await WebviewWindow.getByLabel("settings");
      if (settings) {
        await settings.show();
        await settings.setFocus();
      }
    }
  } catch {
    // Do not pop up when sidecar is not ready, to avoid interrupting; re-check on restart once connected
    onboardingChecked = false;
  }
}
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
  if (statusUnlisten) statusUnlisten();
});

function onMouseDown(e: MouseEvent) {
  downX = e.screenX;
  downY = e.screenY;
  dragStarted = false;
}

function onMouseMove(e: MouseEvent) {
  // While pressed, only start drag when movement exceeds threshold (start once)
  if (e.buttons === 0 || dragStarted) return;
  if (Math.abs(e.screenX - downX) > 4 || Math.abs(e.screenY - downY) > 4) {
    dragStarted = true;
    // Handed off to system drag loop; user canceling the drag is normal, swallow the reject
    getCurrentWindow().startDragging().catch(() => {});
  }
}

function onClick() {
  // If drag already started, do not expand (kept as a fallback discriminator)
  if (dragStarted) return;
  togglePanel();
}

async function togglePanel() {
  const panel = await WebviewWindow.getByLabel("panel");
  if (!panel) return;
  // Panel positioning: default to the right of the ball; flip to the left when no room on the right; clamp vertically so it doesn't exceed the screen bottom
  try {
    const win = getCurrentWindow();
    const pos = await win.outerPosition(); // physical pixels
    // Panel size in physical pixels (logical 320x420 × scale factor)
    const panelW = 320;
    const panelH = 420;
    const ballW = 90;
    let px = pos.x + ballW + 6; // right of the ball
    // Use current monitor size to check boundaries
    const monitor = await currentMonitor();
    if (monitor) {
      const screenW = monitor.size.width;
      const scale = monitor.scaleFactor || 1;
      const panelPhysW = panelW * scale;
      const panelPhysH = panelH * scale;
      // Doesn't fit on the right → flip to the left of the ball
      if (px + panelPhysW > screenW) {
        px = pos.x - panelPhysW - 6;
        if (px < 0) px = Math.max(0, screenW - panelPhysW);
      }
      // Vertical: ball too low, shift panel up to avoid exceeding the bottom
      let py = pos.y;
      const screenH = monitor.size.height;
      if (py + panelPhysH > screenH) {
        py = Math.max(0, screenH - panelPhysH - 10);
      }
      await panel.setPosition(new PhysicalPosition(px, py));
    } else {
      // No monitor info, fall back to a simple right-side positioning in logical coordinates
      await panel.setPosition(new LogicalPosition(pos.x + ballW + 6, pos.y));
    }
  } catch {
    /* Show even if positioning failed */
  }
  await panel.show();
  await panel.setFocus();
}
</script>

<template>
  <div
    class="ball"
    :style="{ background: ballColor() }"
    @mousedown="onMouseDown"
    @mousemove="onMouseMove"
    @click="onClick"
  >
    <div v-if="!connected" class="connecting">
      <template v-if="givenUp">⚠<br /><span>{{ t("watchdogGivenUp") }}</span></template>
      <template v-else>⚡<br /><span>{{ t("ballConnecting") }}</span></template>
    </div>
    <template v-else>
      <div class="today">{{ symbol }}{{ fmt(today) }}</div>
      <div class="rate">{{ symbol }}{{ fmt(rate) }}/min</div>
    </template>
  </div>
</template>

<style scoped>
.ball {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #fff;
  cursor: grab;
  user-select: none;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
  transition: background 0.3s ease;
}
.ball:active {
  cursor: grabbing;
}
.today {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.3px;
}
.rate {
  font-size: 9px;
  opacity: 0.85;
  margin-top: 2px;
}
.connecting {
  font-size: 16px;
  text-align: center;
  line-height: 1.2;
}
.connecting span {
  font-size: 9px;
  opacity: 0.85;
}
</style>

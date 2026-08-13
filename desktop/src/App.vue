<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { getCurrentWindow, currentMonitor } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { LogicalPosition } from "@tauri-apps/api/dpi";
// outerPosition / currentMonitor 返回物理像素，用 PhysicalPosition 避免缩放换算错位
import { PhysicalPosition } from "@tauri-apps/api/dpi";
import {
  fetchSummary,
  currencySymbol,
  fmt,
  type MeterSummary,
} from "./sidecar";

const today = ref(0);
const rate = ref(0);
const budgetPct = ref<number | null>(null);
const currency = ref("USD");
const connected = ref(false);

let timer: number | undefined;
// 拖拽 vs 点击判别：mousedown 只记录坐标；mousemove 超阈值才启动系统拖拽，
// 否则 startDragging 会进入模态拖动循环、吞掉 click，导致点击无法展开面板
let downX = 0;
let downY = 0;
let dragStarted = false;

const symbol = computed(() => currencySymbol(currency.value));

/** 颜色逻辑：未设预算(null)或 <60 → 绿；60-80 → 黄；≥80 → 红；离线 → 灰 */
function ballColor(): string {
  if (!connected.value) return "#9ca3af";
  if (budgetPct.value === null) return "#22c55e";
  if (budgetPct.value >= 80) return "#ef4444";
  if (budgetPct.value >= 60) return "#eab308";
  return "#22c55e";
}

async function refresh() {
  try {
    const d: MeterSummary = await fetchSummary();
    today.value = d.today;
    rate.value = d.rate_per_min;
    budgetPct.value = d.budget_pct;
    currency.value = d.currency;
    connected.value = true;
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

function onMouseDown(e: MouseEvent) {
  downX = e.screenX;
  downY = e.screenY;
  dragStarted = false;
}

function onMouseMove(e: MouseEvent) {
  // 按住状态下，移动超阈值才启动拖拽（只启动一次）
  if (e.buttons === 0 || dragStarted) return;
  if (Math.abs(e.screenX - downX) > 4 || Math.abs(e.screenY - downY) > 4) {
    dragStarted = true;
    // 交给系统拖动循环；用户取消拖动是正常行为，吞掉 reject
    getCurrentWindow().startDragging().catch(() => {});
  }
}

function onClick() {
  // 拖拽已启动则不展开（保留之前的判别作为兜底）
  if (dragStarted) return;
  togglePanel();
}

async function togglePanel() {
  const panel = await WebviewWindow.getByLabel("panel");
  if (!panel) return;
  // 面板定位：默认球右侧；右侧空间不足则翻到左侧；纵向 clamp 防超出屏幕底部
  try {
    const win = getCurrentWindow();
    const pos = await win.outerPosition(); // 物理像素
    // 物理像素下的面板尺寸（logical 320x420 × 缩放比）
    const panelW = 320;
    const panelH = 420;
    const ballW = 90;
    let px = pos.x + ballW + 6; // 球右侧
    // 拿当前显示器尺寸判断边界
    const monitor = await currentMonitor();
    if (monitor) {
      const screenW = monitor.size.width;
      const scale = monitor.scaleFactor || 1;
      const panelPhysW = panelW * scale;
      const panelPhysH = panelH * scale;
      // 右侧放不下 → 翻到球左侧
      if (px + panelPhysW > screenW) {
        px = pos.x - panelPhysW - 6;
        if (px < 0) px = Math.max(0, screenW - panelPhysW);
      }
      // 纵向：球太靠下，面板上移避免超出底部
      let py = pos.y;
      const screenH = monitor.size.height;
      if (py + panelPhysH > screenH) {
        py = Math.max(0, screenH - panelPhysH - 10);
      }
      await panel.setPosition(new PhysicalPosition(px, py));
    } else {
      // 无显示器信息，退回逻辑坐标的简单右侧定位
      await panel.setPosition(new LogicalPosition(pos.x + ballW + 6, pos.y));
    }
  } catch {
    /* 定位失败也照常 show */
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
      ⚡<br /><span>连接中</span>
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

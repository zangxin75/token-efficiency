import { createApp } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import App from "./App.vue";
import Panel from "./Panel.vue";
import Settings from "./Settings.vue";
import "./styles.css";

/**
 * Tauri 多窗口共享同一前端入口：根据当前窗口 label 决定挂载哪个组件。
 * - label "ball"     → 悬浮球 App.vue
 * - label "panel"    → 展开面板 Panel.vue
 * - label "settings" → 设置/Onboarding Settings.vue（内部按是否首次启动切换）
 */
async function bootstrap() {
  const root = document.getElementById("app");
  if (!root) return;

  let label = "ball";
  try {
    // 浏览器环境（Playwright 调试）无 __TAURI_INTERNALS__，降级为 ball
    label = getCurrentWindow().label;
  } catch {
    label = "ball";
  }

  if (label === "panel") {
    createApp(Panel).mount(root);
  } else if (label === "settings") {
    createApp(Settings).mount(root);
  } else {
    createApp(App).mount(root);
  }
}

bootstrap();

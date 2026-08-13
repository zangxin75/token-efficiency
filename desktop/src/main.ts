import { createApp } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import App from "./App.vue";
import Panel from "./Panel.vue";
import Settings from "./Settings.vue";
import "./styles.css";

/**
 * Tauri multi-window shares a single frontend entry: the mounted component is decided by the current window label.
 * - label "ball"     → floating ball App.vue
 * - label "panel"    → expanded panel Panel.vue
 * - label "settings" → settings/Onboarding Settings.vue (internally switches based on whether it's first launch)
 */
async function bootstrap() {
  const root = document.getElementById("app");
  if (!root) return;

  let label = "ball";
  try {
    // Browser environment (Playwright debugging) has no __TAURI_INTERNALS__, fall back to ball
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

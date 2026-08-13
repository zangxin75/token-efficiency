// B4 platform detection: calls the Rust detect_form command to decide the interaction form (ball floating ball / tray system tray).
// Decided on the Rust side rather than JS (env is unreliable inside the AppImage sandbox, see B4 docs M2).
// On invoke failure (non-Tauri environment / command not registered) defaults to ball (Windows primary scenario).

import { invoke } from "@tauri-apps/api/core";

export type Form = "ball" | "tray";

export async function detectForm(): Promise<Form> {
  try {
    const form = await invoke<string>("detect_form");
    return form === "tray" ? "tray" : "ball";
  } catch {
    return "ball";
  }
}

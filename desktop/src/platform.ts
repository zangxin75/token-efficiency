// B4 平台检测：调用 Rust detect_form 命令，决定交互形态（ball 悬浮球 / tray 托盘）。
// 在 Rust 侧判定而非 JS（AppImage 沙箱内 env 不可靠，见 B4 文档 M2）。
// invoke 失败（非 Tauri 环境 / 命令未注册）时默认 ball（Windows 主场景）。

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

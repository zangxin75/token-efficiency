<div align="center">

# tokeneff ⚡

**LLM API cost meter — local BYOK proxy + real-time dashboard**

See every token, every cent, in real time. Like an electricity meter for your AI apps.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![Tests: 33 passed](https://img.shields.io/badge/tests-33%20passed-brightgreen)](#development)
[![Download Windows Installer](https://img.shields.io/badge/Windows-NSIS%20Setup-blueviolet)](https://github.com/zangxin75/token-efficiency/releases/latest)

**English** · [简体中文](README.zh-CN.md)

</div>

---

`tokeneff` is an open-source local proxy that meters your LLM API calls — in
real time, with official-price comparison and month-end forecasting. It sits
between your AI client (Claude Code, Codex, Cursor, …) and the upstream, and
**works as a transparent protocol-aware meter**: your client speaks its native
protocol, tokeneff forwards to the matching gateway endpoint, and bills every
token. **Your API keys never leave your machine.**

## Why?

Most LLM dashboards show you the bill **after** the damage is done. tokeneff
shows you the meter **while it's running**:

- 📊 **Watch costs live** — `$/min`, cumulative spend, month-end projection
- 🔮 **Month-end forecast** — based on your usage trend, with confidence
- 💰 **Transparent billing** — official price vs what you actually pay, no middleman markup
- 🔑 **BYOK** — your keys stay local, requests go direct to upstream
- 🇨🇳 **Dual-region / dual-currency** — CNY ¥ and USD $ tracked separately
- 🔒 **100% local** — no cloud, no account, no prompt content stored

## Quick start (3 steps)

```bash
# 1. Install
pip install tokeneff

# 2. Configure (interactive: pick provider + paste key)
tokeneff setup

# 3. Start the local proxy
tokeneff start
# → listening on http://localhost:7860/v1
```

Point your LLM client at the proxy:

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="any",  # tokeneff injects the key you configured
)
resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "hi"}],
)
```

Check the meter:

```bash
tokeneff stats
```

```
⚡ tokeneff 电表  (CNY)

  今日花费       ¥0.0284
  本月累计       ¥0.2524
  近 7 天日均    ¥0.0361
  月终预测       ~¥0.93 (100% 置信)
  累计节省       ¥0.0421

  今日模型花费分布
  deepseek-v4-flash  ¥0.0192   15,797 tok
  glm-4-flash        ¥0.0092    8,273 tok
```

Live TUI dashboard (refreshes every 0.5s, Ctrl+C to exit):

```bash
tokeneff dashboard
```

```
╭────────────────────────── ⚡ TokenEff 电表 ──────────────────────────╮
│   今日 Today        ¥0.0284           ▁                              │
│   本月 Month        ¥0.2524                                          │
│   月终预测 Est.     ~¥0.93            100% 置信                      │
╰──────────────────────────────────────────────────────────────────────╯
╭────────────────────────── 今日模型分布 ──────────────────────────────╮
│  deepseek-v4-flash   ¥0.0192   15,797   ██████████████████          │
│  glm-4-flash         ¥0.0092    8,273   ████████░░░░░░░░░░          │
╰──────────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────────────────────╮
│ 💰 vs 官方定价累计节省  ¥0.0421                                      │
╰──────────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────────────────────╮
│ ⚡ ¥0.0361/min  ·  更新于 21:41:04                                   │
╰──────────────────────────────────────────────────────────────────────╯
```

## Commands

| Command | Description |
|---------|-------------|
| `tokeneff setup` | Interactive config (provider key + budget) |
| `tokeneff start` | Start the local BYOK proxy |
| `tokeneff stats` | Meter stats (today / forecast / budget / savings) |
| `tokeneff dashboard` | Live TUI dashboard (0.5s refresh) |
| `tokeneff config` | Show current config |

---

## Windows 桌面端（推荐普通用户）

不想用命令行？下载 Windows 安装包，开箱即用，带悬浮球 / 系统托盘 / 设置向导。

**下载**：前往 [Releases](https://github.com/zangxin75/token-efficiency/releases/latest)，
下载 `tokeneff_0.1.0_x64-setup.exe`（约 48 MB），双击安装。

安装后：
- **悬浮球**：桌面右下角悬浮球实时显示今日花费，悬停看详情
- **系统托盘**：右键托盘图标可启停电表、打开设置、退出
- **设置向导**：首次启动引导你选择计费模式（自带 Key 直连 / 平台网关）并配置 Key
- **崩溃自愈**：电表 sidecar 意外退出会自动重启，无需手动干预

> ⚠️ 安装器不含 Python 运行时。电表 sidecar 需要本机预装 **Python 3.10+**（加到 PATH）。
> 开发者可参考下文 [Development](#development) 从源码构建。

---

## 接入你的 AI 客户端（Claude Code / Codex / Cursor / …）

tokeneff 是**协议感知的透明电表**：你的客户端用什么协议（Anthropic / OpenAI /
Responses），它就转发到网关的同名端点并计费。接入只需把客户端的 API 地址指向电表。

电表默认监听 `http://localhost:7860`。下面按客户端分别说明。

### Claude Code（Anthropic 协议）

Claude Code 走 `/v1/messages` 端点（Anthropic 格式）。有两种配置方式：

**方式 A：环境变量**

```bash
# Linux / macOS
export ANTHROPIC_BASE_URL=http://localhost:7860
export ANTHROPIC_AUTH_TOKEN=<你的平台 key 或任意占位符>
claude
```

```powershell
# Windows PowerShell
$env:ANTHROPIC_BASE_URL="http://localhost:7860"
$env:ANTHROPIC_AUTH_TOKEN="<你的 key>"
claude
```

**方式 B：独立 settings 文件（推荐，与默认 Claude Code 隔离）**

创建 `~/.claude/tokeneff-claude.json`：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:7860",
    "ANTHROPIC_AUTH_TOKEN": "<你的 key>",
    "ANTHROPIC_MODEL": "claude-sonnet-4-6"
  }
}
```

在 PowerShell profile 里加一个快捷命令：

```powershell
function claude-tokeneff {
  claude --settings "$env:USERPROFILE\.claude\tokeneff-claude.json" @args
}
```

之后运行 `claude-tokeneff` 即可走电表计费，普通 `claude` 不受影响。

> 💡 **模型别名**：若你的全局 settings 里配了模型别名映射（如
> `claude-sonnet-4-6 → glm-5.1`），Claude Code 会把别名后的模型名发给电表。
> 电表按**端点**（`/v1/messages`）判定协议格式，不依赖模型名，所以别名不影响计费。

### Codex（OpenAI Responses 协议）

Codex 走 `/v1/responses` 端点。把 base URL 指向电表：

```bash
# Codex 配置
OPENAI_BASE_URL=http://localhost:7860/v1
OPENAI_API_KEY=<你的 key>
```

电表会把 `/v1/responses` 透传到网关同名端点并计费。

### Cursor / Cline / 其他 OpenAI 兼容客户端

走 `/v1/chat/completions` 端点（OpenAI 格式）。在客户端设置里：

- **Base URL**: `http://localhost:7860/v1`
- **API Key**: `<你的 key>`

### Python / OpenAI SDK

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="<你的 key>",  # BYOK 模式下电表会注入你配置的 key
)
resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "hi"}],
)
```

### 计费模式说明

| 模式 | 适用 | Key 来自 | 电表行为 |
|------|------|----------|----------|
| **BYOK**（自带 Key） | 有上游厂商 Key | 系统钥匙串 | 用你的 Key 直连上游，按官方价计费 |
| **platform**（平台网关） | 用 tokeneff 平台 | 平台 Key | 转发到 tokeneff 网关，按平台价计费 |

用 `tokeneff setup` 切换模式。两种模式下，所有客户端协议（Anthropic / OpenAI /
Responses）都自动适配。

---

## How it works

```
your client (Claude Code / Codex / Cursor / SDK)
    │  Anthropic (/v1/messages) · OpenAI (/v1/chat/completions) · Responses (/v1/responses)
    ▼
tokeneff local proxy (localhost:7860)
    ├─ endpoint routing: 按客户端端点透传到网关同名端点
    ├─ protocol-aware: 网关侧处理 OpenAI ↔ Anthropic 格式转换
    ├─ BYOK / platform: 按 mode 注入 key（BYOK 直连上游 / platform 转发网关）
    ├─ billing: 解析 usage（input/output tokens）→ 本地定价 → 官方对比
    └─ storage: SQLite 历史（只存 token 计数，不存 prompt 内容）
    ▼
LLM upstream / TokenEff gateway (OpenAI / DeepSeek / GLM / Claude / ...)
```

**Privacy**: tokeneff only parses token-usage counts from responses. It never
stores your prompts or completions.

## Supported providers

| Provider | Example models | Protocol |
|----------|---------------|----------|
| OpenAI | gpt-4o, gpt-4o-mini | OpenAI |
| DeepSeek | deepseek-v4-flash/pro | OpenAI-compatible |
| GLM (Zhipu) | glm-4-flash, glm-4.5, glm-5 | OpenAI-compatible |
| Kimi Coding | kimi-k2.6 | Anthropic-compatible |
| MiniMax | minimax-m3 | OpenAI-compatible |
| Anthropic | claude-sonnet-4-6, claude-3-5-haiku | Anthropic native |

## Install requirements

- **Python ≥ 3.10**
- **setuptools ≥ 61** (PEP 621 `[project]` table support)

> ⚠️ Ubuntu 22.04 ships setuptools 59.6.0, which is too old and causes the
> package to install as `UNKNOWN-0.0.0`. Fix:
> ```bash
> pip install --user --upgrade "setuptools>=70" wheel
> pip install tokeneff --no-build-isolation
> ```

## How it compares

| Feature | tokeneff | toktrack | tokencost | LLM-Cost-Guardian |
|---------|:--------:|:--------:|:---------:|:-----------------:|
| Capture method | **local proxy** | reads CLI logs | manual / proxy | local proxy |
| Real-time token count | ✅ | ❌ | ✅ | ✅ |
| Month-end forecast | ✅ | ❌ | ❌ | ❌ |
| Dual region / currency | ✅ | ❌ | ❌ | ❌ |
| BYOK + platform dual-mode | ✅ | ❌ | ❌ | ❌ |
| Budget alerts | ✅ | ❌ | ✅ | ✅ |

## Data storage

| Location | Content |
|----------|---------|
| `~/.tokeneff/config.toml` | Non-sensitive config (mode / region / budget / port) |
| System keyring | API keys (never plaintext on disk) |
| `~/.tokeneff/meter.db` | Usage history (SQLite, WAL mode, token counts only) |

## Development

```bash
git clone https://github.com/zangxin75/token-efficiency.git && cd token-efficiency
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v          # 33 tests
```

## License

MIT

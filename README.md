<div align="center">

# tokeneff ⚡

**LLM API cost meter — local BYOK proxy + real-time dashboard**

See every token, every cent, in real time. Like an electricity meter for your AI apps.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![Tests: 78 passed](https://img.shields.io/badge/tests-78%20passed-brightgreen)](#development)
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
⚡ tokeneff meter  (CNY)

  Today           ¥0.0284
  This month      ¥0.2524
  7-day avg       ¥0.0361
  Month forecast  ~¥0.93 (100% conf.)
  Total saved     ¥0.0421

  Today's model breakdown
  deepseek-v4-flash  ¥0.0192   15,797 tok
  glm-4-flash        ¥0.0092    8,273 tok
```

Live TUI dashboard (refreshes every 0.5s, Ctrl+C to exit):

```bash
tokeneff dashboard
```

```
╭────────────────────────── ⚡ TokenEff Meter ────────────────────────╮
│   Today             ¥0.0284           ▁                            │
│   This month        ¥0.2524                                          │
│   Forecast          ~¥0.93            100% conf.                    │
╰──────────────────────────────────────────────────────────────────────╯
╭────────────────────────── Today's Models ───────────────────────────╮
│  deepseek-v4-flash   ¥0.0192   15,797   ██████████████████          │
│  glm-4-flash         ¥0.0092    8,273   ████████░░░░░░░░░░          │
╰──────────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────────────────────╮
│ 💰 Saved vs official pricing  ¥0.0421                               │
╰──────────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────────────────────╮
│ ⚡ ¥0.0361/min  ·  updated 21:41:04                                  │
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

## Windows desktop (recommended for end users)

Prefer not to use the CLI? Download the Windows installer — it ships with a
floating cost widget, system tray, and a setup wizard.

**Download**: Go to [Releases](https://github.com/zangxin75/token-efficiency/releases/latest)
and grab `tokeneff_0.1.1_x64-setup.exe` (~49 MB). Double-click to install.

After installing:
- **Floating widget**: a small ball in the corner shows today's spend in real time; hover for details.
- **System tray**: right-click the tray icon to start/stop the meter, open settings, or quit.
- **Setup wizard**: on first launch it guides you through picking a billing mode (BYOK direct / platform gateway) and configuring your key.
- **Auto language**: the UI follows your region — English worldwide, Chinese for the CN site.
- **Start on login**: optional autostart, toggleable in Settings.
- **Crash self-healing**: if the meter sidecar dies, it restarts automatically — no manual intervention. If its port is taken, it drifts and the app follows.

> ✅ The installer bundles everything including the meter sidecar (PyInstaller-packaged) — no Python installation required.

---

## Connect your AI client (Claude Code / Codex / Cursor / …)

tokeneff is a **protocol-aware transparent meter**: whichever protocol your
client speaks (Anthropic / OpenAI / Responses), it forwards to the matching
gateway endpoint and bills every token. Connecting is just pointing your
client's API URL at the meter.

The meter listens on `http://localhost:7860` by default. Per-client instructions below.

### Claude Code (Anthropic protocol)

Claude Code hits the `/v1/messages` endpoint (Anthropic format). Two ways to configure:

**Option A: environment variables**

```bash
# Linux / macOS
export ANTHROPIC_BASE_URL=http://localhost:7860
export ANTHROPIC_AUTH_TOKEN=<your platform key, or any placeholder>
claude
```

```powershell
# Windows PowerShell
$env:ANTHROPIC_BASE_URL="http://localhost:7860"
$env:ANTHROPIC_AUTH_TOKEN="<your key>"
claude
```

**Option B: separate settings file (recommended — keeps it isolated from your default Claude Code)**

Create `~/.claude/tokeneff-claude.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:7860",
    "ANTHROPIC_AUTH_TOKEN": "<your key>",
    "ANTHROPIC_MODEL": "claude-sonnet-4-6"
  }
}
```

Add a shortcut command in your PowerShell profile:

```powershell
function claude-tokeneff {
  claude --settings "$env:USERPROFILE\.claude\tokeneff-claude.json" @args
}
```

Now `claude-tokeneff` routes through the meter; plain `claude` is unaffected.

> 💡 **Model aliases**: if your global settings map model aliases (e.g.
> `claude-sonnet-4-6 → glm-5.1`), Claude Code sends the aliased name to the meter.
> The meter decides protocol by **endpoint** (`/v1/messages`), not model name — so
> aliases don't affect billing.

### Codex (OpenAI Responses protocol)

Codex hits `/v1/responses`. Point its base URL at the meter:

```bash
# Codex config
OPENAI_BASE_URL=http://localhost:7860/v1
OPENAI_API_KEY=<your key>
```

The meter forwards `/v1/responses` to the gateway's same-named endpoint and bills it.

### Cursor / Cline / other OpenAI-compatible clients

These hit `/v1/chat/completions` (OpenAI format). In the client settings:

- **Base URL**: `http://localhost:7860/v1`
- **API Key**: `<your key>`

### Python / OpenAI SDK

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="<your key>",  # in BYOK mode the meter injects your configured key
)
resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "hi"}],
)
```

### Billing modes

| Mode | Best for | Key source | Meter behavior |
|------|----------|------------|----------------|
| **BYOK** (bring your own key) | You have an upstream vendor key | System keyring | Dials upstream directly with your key, bills at official price |
| **platform** (platform gateway) | You use the tokeneff platform | Platform key | Forwards to the tokeneff gateway, bills at platform price |

Switch modes with `tokeneff setup`. Under either mode, all client protocols
(Anthropic / OpenAI / Responses) adapt automatically.

---

## How it works

```
your client (Claude Code / Codex / Cursor / SDK)
    │  Anthropic (/v1/messages) · OpenAI (/v1/chat/completions) · Responses (/v1/responses)
    ▼
tokeneff local proxy (localhost:7860)
    ├─ endpoint routing: forwards to the gateway's same-named endpoint by client path
    ├─ protocol-aware: the gateway handles OpenAI ↔ Anthropic format conversion
    ├─ BYOK / platform: injects key by mode (BYOK dials upstream / platform forwards to gateway)
    ├─ billing: parses usage (input/output tokens) → local pricing → official-price compare
    └─ storage: SQLite history (token counts only, no prompt content)
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

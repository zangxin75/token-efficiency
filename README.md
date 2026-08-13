<div align="center">

# tokeneff ⚡

**LLM API cost meter — local BYOK proxy + real-time dashboard**

See every token, every cent, in real time. Like an electricity meter for your AI apps.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![Tests: 33 passed](https://img.shields.io/badge/tests-33%20passed-brightgreen)](#development)

**English** · [简体中文](README.zh-CN.md)

</div>

---

`tokeneff` is an open-source CLI that proxies your LLM API calls locally and
meters what you actually spend — in real time, with official-price comparison
and month-end forecasting. **Your API keys never leave your machine.**

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

## How it works

```
your client → tokeneff local proxy (localhost:7860)
                 ├─ BYOK routing: your key → direct to upstream
                 ├─ platform routing: forward to TokenEff gateway (optional)
                 ├─ format adapter: OpenAI ↔ Anthropic auto-convert
                 ├─ billing: local pricing → official vs charged
                 └─ storage: SQLite history (no prompt content)
                       ↓
                  LLM upstream (OpenAI / DeepSeek / GLM / ...)
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

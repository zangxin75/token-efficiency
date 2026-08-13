<div align="center">

# tokeneff ⚡

**LLM API 词源电表 — 本地 BYOK 代理 + 实时电表**

看清每一个词源、每一分钱，实时呈现。就像给你的 AI 应用装了个电表。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![Tests: 33 passed](https://img.shields.io/badge/tests-33%20passed-brightgreen)](#开发)
[![下载 Windows 安装包](https://img.shields.io/badge/Windows-NSIS%20安装包-blueviolet)](https://github.com/zangxin75/token-efficiency/releases/latest)

[English](README.md) · **简体中文**

</div>

---

`tokeneff` 是一个开源的本地代理电表，实时计量你的 LLM API 调用——官方原价对比、月终预测，一目了然。它介于你的 AI 客户端（Claude Code、Codex、Cursor、…）和上游之间，**作为协议感知的透明电表工作**：客户端用什么协议，tokeneff 就转发到网关对应的同名端点并计费。**你的 API key 不离开你的机器。**

## 为什么用

大多数 LLM 仪表盘是**事后**给你看账单。tokeneff 让你**边跑边看**电表：

- 📊 **实时看花费** — `¥/min`、累计、月终预测
- 🔮 **月终预测** — 基于用量趋势预测月底花费，附置信度
- 💰 **透明计费** — 官方原价 vs 实际付费，不被中间商加价
- 🔑 **BYOK** — key 留在本地，请求直达上游
- 🇨🇳 **双区域 / 双币种** — CNY ¥ 和 USD $ 各自独立统计
- 🔒 **100% 本地** — 无云、无账号、不存 prompt 内容

## 快速上手（3 步）

```bash
# 1. 安装
pip install tokeneff

# 2. 配置（交互式：选 provider + 粘贴 key）
tokeneff setup

# 3. 启动本地代理
tokeneff start
# → 监听 http://localhost:7860/v1
```

把 LLM 客户端指向代理：

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="any",  # tokeneff 用你 setup 时配的 key 注入
)
resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "你好"}],
)
```

看电表：

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

实时 TUI 电表（每 0.5s 刷新，Ctrl+C 退出）：

```bash
tokeneff dashboard
```

## 命令

| 命令 | 说明 |
|------|------|
| `tokeneff setup` | 交互式配置（provider key + 预算） |
| `tokeneff start` | 启动本地 BYOK 代理 |
| `tokeneff stats` | 电表统计（今日 / 月终预测 / 预算 / 省钱） |
| `tokeneff dashboard` | 实时 Live TUI 电表（0.5s 刷新） |
| `tokeneff config` | 查看当前配置 |

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
> 开发者可参考下文 [开发](#开发) 从源码构建。

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

## 工作原理

```
你的客户端 (Claude Code / Codex / Cursor / SDK)
    │  Anthropic (/v1/messages) · OpenAI (/v1/chat/completions) · Responses (/v1/responses)
    ▼
tokeneff 本地代理 (localhost:7860)
    ├─ 端点路由：按客户端端点透传到网关同名端点
    ├─ 协议感知：网关侧处理 OpenAI ↔ Anthropic 格式转换
    ├─ BYOK / platform：按模式注入 key（BYOK 直连上游 / platform 转发网关）
    ├─ 计费：解析 usage（input/output tokens）→ 本地定价 → 官方对比
    └─ 存储：SQLite 历史（只存 token 计数，不存 prompt 内容）
    ▼
LLM 上游 / TokenEff 网关 (OpenAI / DeepSeek / GLM / Claude / ...)
```

**隐私保证**：tokeneff 只解析响应里的 token 用量计数，绝不存储你的 prompt 和响应内容。

## 支持的 Provider

| Provider | 模型示例 | 协议 |
|----------|---------|------|
| OpenAI | gpt-4o, gpt-4o-mini | OpenAI |
| DeepSeek | deepseek-v4-flash/pro | OpenAI 兼容 |
| GLM (智谱) | glm-4-flash, glm-4.5, glm-5 | OpenAI 兼容 |
| Kimi Coding | kimi-k2.6 | Anthropic 兼容 |
| MiniMax | minimax-m3 | OpenAI 兼容 |
| Anthropic | claude-sonnet-4-6, claude-3-5-haiku | Anthropic 原生 |

## 安装要求

- **Python ≥ 3.10**
- **setuptools ≥ 61**（PEP 621 `[project]` 表支持）

> ⚠️ Ubuntu 22.04 默认 setuptools 59.6.0 太老，会导致安装成 `UNKNOWN-0.0.0`。修复：
> ```bash
> pip install --user --upgrade "setuptools>=70" wheel
> pip install tokeneff --no-build-isolation
> ```

## 竞品对比

| 特性 | tokeneff | toktrack | tokencost | LLM-Cost-Guardian |
|------|:--------:|:--------:|:---------:|:-----------------:|
| 采集方式 | **本地代理** | 读 CLI 日志 | 手动 / 代理 | 本地代理 |
| 实时 token 计数 | ✅ | ❌ | ✅ | ✅ |
| 月终预测 | ✅ | ❌ | ❌ | ❌ |
| 双区域 / 双币种 | ✅ | ❌ | ❌ | ❌ |
| BYOK + 平台双模式 | ✅ | ❌ | ❌ | ❌ |
| 预算告警 | ✅ | ❌ | ✅ | ✅ |

## 数据存储

| 位置 | 内容 |
|------|------|
| `~/.tokeneff/config.toml` | 非敏感配置（模式 / 地域 / 预算 / 端口） |
| 系统 keyring | API key（明文不落盘） |
| `~/.tokeneff/meter.db` | 用量历史（SQLite，WAL 模式，仅 token 计数） |

## 开发

```bash
git clone https://github.com/zangxin75/token-efficiency.git && cd token-efficiency
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v          # 33 个测试
```

## License

MIT

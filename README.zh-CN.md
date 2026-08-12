<div align="center">

# tokeneff ⚡

**LLM API 词源电表 — 本地 BYOK 代理 + 实时电表**

看清每一个词源、每一分钱，实时呈现。就像给你的 AI 应用装了个电表。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![Tests: 33 passed](https://img.shields.io/badge/tests-33%20passed-brightgreen)](#开发)

[English](README.md) · **简体中文**

</div>

---

`tokeneff` 是一个开源 CLI 工具，在本地代理你的 LLM API 调用并实时计量花费——官方原价对比、月终预测，一目了然。**你的 API key 不离开你的机器。**

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

## 工作原理

```
你的客户端 → tokeneff 本地代理 (localhost:7860)
                 ├─ BYOK 路由：你的 key → 直连上游
                 ├─ 平台路由：转发到 TokenEff 网关（可选）
                 ├─ 格式适配：OpenAI ↔ Anthropic 自动转换
                 ├─ 计费：本地定价 → 官方价 vs 实付价
                 └─ 存储：SQLite 历史（不含 prompt 内容）
                       ↓
                  LLM 上游 (OpenAI / DeepSeek / GLM / ...)
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

# Contributing to Token Efficiency

Thanks for your interest in contributing! 🎉

## Ways to Contribute

- 🐛 **Report bugs** — Open an issue with reproduction steps
- 💡 **Suggest features** — Open an issue with your use case
- 🔧 **Submit PRs** — Fix bugs or add features
- 📖 **Improve docs** — Typos, clarifications, translations
- 🌟 **Star & share** — Help others discover the project

## Development Setup

```bash
git clone https://github.com/zangxin75/token-efficiency.git
cd token-efficiency
cp .env.example .env  # Add your API keys
docker compose up -d
```

## Pull Request Process

1. **Fork** the repo and create a branch: `git checkout -b feat/my-feature`
2. **Write tests** for new functionality
3. **Ensure tests pass**: `python -m pytest tests/ -v`
4. **Keep PRs focused** — one feature/fix per PR
5. **Use clear commit messages** — follow conventional commits

## Code Style

- **Python**: Follow existing patterns. We use `async/await` throughout.
- **Frontend**: Vue 3 Composition API with `<script setup>`.
- **SQL**: Lowercase keywords, snake_case identifiers.
- **Tests**: Every new feature should include test coverage.

## Reporting Security Issues

**Do not open a public issue for security vulnerabilities.**

Instead, email: security@tokeneff.com

We will acknowledge receipt within 48 hours and provide a fix timeline.

## Questions?

Open a [Discussion](https://github.com/zangxin75/token-efficiency/discussions) — we're happy to help!

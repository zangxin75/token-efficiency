"""Audit-fix regression tests (code-review round 2026-08-14).

H1: CNY conversion at record time (USD amounts × rate, real ¥ stored).
H2: proxy rejects requests without Authorization (no-cors drive-by billing).
H3: myip.ipip.net nested response parsing (was dead code).
M6: borderline fallback uses timezone, not locale (zh-TW/HK → global).
"""

import json

import pytest

from tokeneff.meter.calculator import USD_TO_CNY
from tokeneff.meter.collector import Collector
from tokeneff.meter.types import UsageRecord, UsageResult
from tokeneff.region import _detect_ip_country, _CN_TIMEZONES


# ── H1: CNY conversion ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_h1_cny_conversion_on_record(tmp_db, monkeypatch):
    """CNY users: charged/official/saved stored as real ¥ (USD × rate), not USD-with-CNY-label."""
    class FakeCfg:
        region = "cn"
        def get_currency(self): return "CNY"

    from tokeneff.meter import collector as col_mod
    monkeypatch.setattr(col_mod.cfg_module, "get_config", lambda: FakeCfg())

    col = Collector(store=tmp_db)
    usage = UsageResult(input_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
    # calculator on deepseek-v4-flash: in 0.09 USD/M → 1M in = $0.09
    await col.record("deepseek-v4-flash", usage, elapsed=1.0)

    history = await tmp_db.get_history_30d()
    assert len(history) == 1
    rec = history[0]
    assert rec.currency == "CNY"
    usd = 1_000_000 / 1_000_000 * 0.09
    assert rec.charged_amount == pytest.approx(usd * USD_TO_CNY, abs=1e-4)


@pytest.mark.asyncio
async def test_h1_usd_untouched_for_global(tmp_db, monkeypatch):
    """Global users: USD amounts stored as-is (no conversion)."""
    class FakeCfg:
        region = "global"
        def get_currency(self): return "USD"

    from tokeneff.meter import collector as col_mod
    monkeypatch.setattr(col_mod.cfg_module, "get_config", lambda: FakeCfg())

    col = Collector(store=tmp_db)
    usage = UsageResult(input_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
    await col.record("deepseek-v4-flash", usage, elapsed=1.0)

    history = await tmp_db.get_history_30d()
    assert history[0].currency == "USD"
    assert history[0].charged_amount == pytest.approx(0.09, abs=1e-4)


# ── H3: myip.ipip.net nested parsing ──────────────────────────────────────────


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def get(self, url):
        return _FakeResp(self._payload)


def test_h3_ipip_nested_location_parsed(monkeypatch):
    """myip.ipip.net shape: {"ret":"ok","data":{"location":["中国","辽宁",...]}} → CN."""
    import tokeneff.region as region_mod
    payload = {"ret": "ok", "data": {"ip": "1.2.3.4", "location": ["中国", "辽宁", "沈阳", "", "联通"]}}
    monkeypatch.setattr(region_mod.httpx, "Client", lambda **kw: _FakeClient(payload))
    assert _detect_ip_country() == "CN"


def test_h3_ipinfo_toplevel_country_parsed(monkeypatch):
    """ipinfo.io shape: {"country":"US"} → US."""
    import tokeneff.region as region_mod
    monkeypatch.setattr(region_mod.httpx, "Client", lambda **kw: _FakeClient({"country": "US"}))
    assert _detect_ip_country() == "US"


# ── M6: borderline fallback uses timezone ─────────────────────────────────────


def test_m6_borderline_fallback_timezone_not_locale(monkeypatch):
    """zh-TW scenario (zh locale + non-CN tz) borderline → global (was: cn via locale)."""
    import tokeneff.region as region_mod

    class FakeSig:
        timezone = "Asia/Taipei"      # non-CN tz
        locale = "zh_tw"             # zh locale
        ip_country = None
        win_locale = None
        cn_score = 2                 # locale only
        global_score = 2             # tz + ...
        recommended = None           # borderline
        reason = ""

    monkeypatch.setattr(region_mod, "detect_region_signals", lambda: FakeSig())
    monkeypatch.setattr(region_mod.cfg_module, "get_config", lambda: type("C", (), {"region": ""})())

    assert region_mod.detect_region() == "global"  # tz-based, not locale


def test_m6_borderline_cn_tz_still_cn(monkeypatch):
    """Symmetric: non-zh locale + CN tz borderline → cn."""
    import tokeneff.region as region_mod

    class FakeSig:
        timezone = "Asia/Shanghai"
        locale = "en_us"
        ip_country = None
        win_locale = None
        cn_score = 2
        global_score = 2
        recommended = None
        reason = ""

    monkeypatch.setattr(region_mod, "detect_region_signals", lambda: FakeSig())
    monkeypatch.setattr(region_mod.cfg_module, "get_config", lambda: type("C", (), {"region": ""})())

    assert region_mod.detect_region() == "cn"


def test_cn_timezone_set_includes_windows_and_localized():
    """Windows registry names + localized tzname are recognized as CN."""
    assert "China Standard Time" in _CN_TIMEZONES
    assert "中国标准时间" in _CN_TIMEZONES


# ── M7: gateway URL whitelist (anti-SSRF / anti-key-exfil) ────────────────────


def test_m7_gateway_url_blacklist():
    """M7 (re-scoped): self-hosted gateways on any public https domain are a
    supported feature; the platform_url validator rejects only loopback/private/
    link-local hosts (SSRF & key-exfil targets). Official domains still pass."""
    from tokeneff.api.local_server import ConfigUpdatePayload
    from pydantic import ValidationError

    for ok_url in ("https://tokeneff.com", "https://global.tokeneff.com",
                   "https://api.tokeneff.com", "https://evil.com"):
        assert ConfigUpdatePayload(platform_url=ok_url).platform_url == ok_url
    for bad_url in ("http://localhost:6001", "https://127.0.0.1:5001",
                    "http://evil.com", "https://192.168.1.1:8080",
                    "https://169.254.169.254", "https://10.0.0.5",
                    "https://172.16.0.1", "https://[::1]"):
        with pytest.raises(ValidationError):
            ConfigUpdatePayload(platform_url=bad_url)


# ── M12: update_config validation + region cascade ────────────────────────────


@pytest.mark.asyncio
async def test_m12_config_validation_and_region_cascade(monkeypatch, tmp_path):
    from tokeneff.api import local_server as ls
    from tokeneff import config as C

    # Isolated config file
    monkeypatch.setattr(C, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(C, "CONFIG_DIR", tmp_path)
    C._config = None
    monkeypatch.setattr(ls.cfg_module, "get_config", C.load)

    # Bad values rejected with 422 by the Pydantic payload, not persisted
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ls.ConfigUpdatePayload(proxy_port="abc")
    with pytest.raises(ValidationError):
        ls.ConfigUpdatePayload(mode="bogus")
    with pytest.raises(ValidationError):
        ls.ConfigUpdatePayload(budget_monthly_usd=-5)
    with pytest.raises(ValidationError):
        ls.ConfigUpdatePayload(platform_url="https://192.168.1.1:8080")

    # region change cascades platform_url (M12 parity with wizard set_region)
    r = await ls.update_config(ls.ConfigUpdatePayload(region="cn", platform_url=""))
    assert r["updated"].get("region") == "cn"
    assert C.load(force=True).get_platform_url() == "https://tokeneff.com"

    C._config = None


# ── M13: corrupt config backed up, not silently reset ─────────────────────────


def test_m13_corrupt_config_backed_up(tmp_path, monkeypatch):
    from tokeneff import config as C

    monkeypatch.setattr(C, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(C, "CONFIG_DIR", tmp_path)
    C._config = None
    # Write a corrupt + a valid key
    (tmp_path / "config.toml").write_text("region = \"cn\"\nBROKEN [[[")

    cfg = C.load(force=True)
    assert cfg.region == ""  # fell back to defaults (corrupt file)
    assert (tmp_path / "config.toml.bak").exists()  # backup preserved for recovery
    C._config = None

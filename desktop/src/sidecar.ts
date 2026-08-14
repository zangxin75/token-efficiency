import axios from "axios";

/** Default sidecar port (sidecar drifts upward when occupied) */
export const SIDECAR_DEFAULT_PORT = 7861;

/**
 * Port-drift discovery (★ audit HIGH fix): when 7861 is occupied the sidecar
 * silently drifts to 7862+; this module previously hardcoded 7861 and every
 * window stayed permanently disconnected. The sidecar publishes its actual
 * port to ~/.tokeneff/sidecar.port at startup — read it via the fs plugin,
 * verify with /api/health, fall back to the default when stale.
 */
let discoveredPort = SIDECAR_DEFAULT_PORT;

export function currentSidecarBase(): string {
  return `http://127.0.0.1:${discoveredPort}`;
}

export const sidecar = axios.create({
  baseURL: currentSidecarBase(),
  timeout: 3000,
});

/** Re-point the axios instance at a new port (used by discoverSidecarPort). */
function setSidecarPort(port: number): void {
  if (port !== discoveredPort) {
    discoveredPort = port;
    sidecar.defaults.baseURL = currentSidecarBase();
  }
}

async function probeHealth(port: number): Promise<boolean> {
  try {
    const resp = await axios.get(`http://127.0.0.1:${port}/api/health`, {
      timeout: 1500,
    });
    return resp.status === 200;
  } catch {
    return false;
  }
}

/**
 * Discover the sidecar's actual port. The port file is read via a Rust invoke
 * (`get_sidecar_port`, reads ~/.tokeneff/sidecar.port written by the sidecar at
 * startup) — avoids adding plugin-fs just for one file. Probes candidates for
 * liveness and falls back to the default when the file is missing or stale.
 *
 * Called once per window on mount, and again on demand when requests fail in a
 * way consistent with a wrong port (network error) so a mid-session restart
 * onto a different port heals itself.
 */
export async function discoverSidecarPort(): Promise<number> {
  const candidates: number[] = [];
  try {
    // lazy import: keep pure-JS environments (unit tests) importable
    const { invoke } = await import("@tauri-apps/api/core");
    const fromFile = await invoke<number | null>("get_sidecar_port");
    if (typeof fromFile === "number" && fromFile > 0 && fromFile < 65536) {
      candidates.push(fromFile);
    }
  } catch {
    // invoke unavailable or command failed — fall through to default probing
  }
  if (discoveredPort !== SIDECAR_DEFAULT_PORT) {
    candidates.push(discoveredPort); // re-verify a previously drifted port
  }
  if (!candidates.includes(SIDECAR_DEFAULT_PORT)) {
    candidates.push(SIDECAR_DEFAULT_PORT);
  }
  for (const port of candidates) {
    if (await probeHealth(port)) {
      setSidecarPort(port);
      return port;
    }
  }
  // Nothing answered (sidecar starting up?) — stay on the first candidate so
  // the normal "connecting…" UI shows, not a wrong-port silent failure.
  setSidecarPort(candidates[0]);
  return candidates[0];
}

/** Attach a response interceptor that re-discovers the port on network errors. */
let interceptorInstalled = false;
export function installSidecarRecovery(): void {
  if (interceptorInstalled) return;
  interceptorInstalled = true;
  sidecar.interceptors.response.use(
    (resp) => resp,
    async (error) => {
      // ECONNREFUSED / timeout on the current port → maybe the sidecar restarted
      // onto a different port; re-discover once, then replay the request.
      if (!error.response && error.config && !error.config.__portRetried) {
        error.config.__portRetried = true;
        const port = await discoverSidecarPort();
        if (port !== discoveredPort || !error.response) {
          error.config.baseURL = currentSidecarBase();
          return sidecar.request(error.config);
        }
      }
      return Promise.reject(error);
    }
  );
}

/** /api/meter/summary response structure (fields aligned with tokeneff/api/local_server.py) */
export interface MeterSummary {
  currency: string;
  today: number;
  month: number;
  rate_per_min: number;
  saved: number;
  budget: number;
  budget_pct: number | null;
  /** user-configured alert threshold in percent (drives ball/panel coloring) */
  alert_threshold: number;
  forecast: {
    estimated: number;
    current_spend: number;
    daily_avg: number;
    confidence: number;
  };
}

/** A single model distribution entry returned by /api/meter/models
 * (fields must match store.get_model_breakdown_today — a mismatch renders NaN
 * across the whole model-distribution section, see review fix) */
export interface ModelBreakdown {
  model: string;
  charged: number;
  input_tokens: number;
  output_tokens: number;
}

export interface MeterModels {
  models: ModelBreakdown[];
}

export interface HealthInfo {
  status: string;
  version: string;
  proxy_port: number;
  mode: string;
  region: string;
  currency: string;
}

export async function fetchSummary(): Promise<MeterSummary> {
  const { data } = await sidecar.get<MeterSummary>("/api/meter/summary");
  return data;
}

export async function fetchModels(): Promise<ModelBreakdown[]> {
  const { data } = await sidecar.get<MeterModels>("/api/meter/models");
  return data.models ?? [];
}

export async function fetchHealth(): Promise<HealthInfo> {
  const { data } = await sidecar.get<HealthInfo>("/api/health");
  return data;
}

// ── B3: provider / key / config endpoints ─────────────────────────────────────────

/** /api/providers single entry structure (aligned with local_server.py list_providers) */
export interface ProviderInfo {
  name: string;
  label: string;
  models: string[];
  auth_header: string;
  configured: boolean;
}

/** /api/config response structure */
export interface AppConfig {
  mode: string;
  region: string;
  /** manual-override lock: true = auto-detect must not rewrite region */
  region_manual: boolean;
  currency: string;
  proxy_port: number;
  budget_monthly_usd: number;
  alert_threshold: number;
  providers_configured: string[];
  has_platform_key: boolean;
  platform_url?: string;
}

export interface VerifyResult {
  ok: boolean;
  message: string;
}

export interface SaveKeyResult {
  ok: boolean;
  provider?: string;
  error?: string;
}

/** GET /api/providers — available provider list (including whether configured) */
export async function fetchProviders(): Promise<ProviderInfo[]> {
  const { data } = await sidecar.get<{ providers: ProviderInfo[] }>(
    "/api/providers"
  );
  return data.providers ?? [];
}

/** POST /api/config/verify — verify whether the key is valid (not stored) */
export async function verifyKey(
  provider: string,
  key: string
): Promise<VerifyResult> {
  // per-request timeout: backend probes with a 15s httpx budget — the frontend
  // must stay strictly longer or an edge-case timeout surfaces as a raw
  // AxiosError instead of the backend's friendly message
  const { data } = await sidecar.post<VerifyResult>(
    "/api/config/verify",
    { provider, key },
    { timeout: 20000 }
  );
  return data;
}

/** POST /api/config/key — store provider key into keyring */
export async function saveKey(
  provider: string,
  key: string
): Promise<SaveKeyResult> {
  const { data } = await sidecar.post<SaveKeyResult>("/api/config/key", {
    provider,
    key,
  });
  return data;
}

// ── B3.1: tokeneff gateway platform key endpoints ───────────────────────────────────────

export interface PlatformKeyResult {
  ok: boolean;
  has_platform_key?: boolean;
  error?: string;
}

/** POST /api/config/platform-verify — verify the tokeneff gateway key (probes the gateway) */
export async function verifyPlatformKey(
  key: string,
  platformUrl?: string
): Promise<VerifyResult> {
  // per-request timeout: backend probes the gateway with a 10s httpx budget;
  // the frontend must not give up earlier or valid keys read as invalid
  const { data } = await sidecar.post<VerifyResult>(
    "/api/config/platform-verify",
    { key, platform_url: platformUrl },
    { timeout: 15000 }
  );
  return data;
}

/** POST /api/config/platform-key — store the gateway platform key into keyring */
export async function savePlatformKey(key: string): Promise<PlatformKeyResult> {
  const { data } = await sidecar.post<PlatformKeyResult>(
    "/api/config/platform-key",
    { key }
  );
  return data;
}

/** GET /api/config — read the current config */
export async function fetchConfig(): Promise<AppConfig> {
  const { data } = await sidecar.get<AppConfig>("/api/config");
  return data;
}

/** GET /api/region/detect — multi-signal region detection (★ R1, VPN-proof).
 * Returns raw signals + scores + recommended region + human-readable reason. */
export interface RegionSignals {
  timezone: string;
  locale: string;
  ip_country: string | null;
  win_locale: string | null;
  cn_score: number;
  global_score: number;
  recommended: "cn" | "global" | null;
  reason: string;
}

export async function detectRegion(): Promise<RegionSignals> {
  // per-request timeout override: backend IP probing can take up to ~6s,
  // longer than the global 3s default — a premature abort would misroute
  // overseas users to the CN gateway
  const { data } = await sidecar.get<RegionSignals>("/api/region/detect", {
    timeout: 8000,
  });
  return data;
}

/** POST /api/config — update non-sensitive config fields */
export async function updateConfig(
  patch: Partial<AppConfig> & { region_manual?: boolean }
): Promise<{ updated: Record<string, unknown> }> {
  const { data } = await sidecar.post<{ updated: Record<string, unknown> }>(
    "/api/config",
    patch
  );
  return data;
}

/** Currency symbol */
export function currencySymbol(currency: string): string {
  return currency === "CNY" ? "¥" : "$";
}

/** Compact number formatting: 0.0284 → "0.0284", 0 → "0.0000" */
export function fmt(n: number, digits = 4): string {
  if (!Number.isFinite(n)) return "—";
  // Small spend (< 1 cent) shows higher precision, otherwise $0.000027 rounds to $0.0000 hiding the billing
  if (n > 0 && n < 0.01) return n.toFixed(6);
  return n.toFixed(digits);
}

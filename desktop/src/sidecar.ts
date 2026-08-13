import axios from "axios";

/** sidecar 只读 API 基址（B0 已验证 7861 端口可监听、keyring 可存取） */
export const SIDECAR_BASE = "http://127.0.0.1:7861";

export const sidecar = axios.create({
  baseURL: SIDECAR_BASE,
  timeout: 3000,
});

/** /api/meter/summary 返回结构（字段对齐 tokeneff/api/local_server.py） */
export interface MeterSummary {
  currency: string;
  today: number;
  month: number;
  rate_per_min: number;
  saved: number;
  budget: number;
  budget_pct: number | null;
  forecast: {
    estimated: number;
    current_spend: number;
    daily_avg: number;
    confidence: number;
  };
}

/** /api/meter/models 返回的单条模型分布 */
export interface ModelBreakdown {
  model: string;
  charged: number;
  saved: number;
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

// ── B3: provider / key / config 端点 ─────────────────────────────────────────

/** /api/providers 单条结构（对齐 local_server.py list_providers） */
export interface ProviderInfo {
  name: string;
  label: string;
  models: string[];
  auth_header: string;
  configured: boolean;
}

/** /api/config 返回结构 */
export interface AppConfig {
  mode: string;
  region: string;
  currency: string;
  proxy_port: number;
  budget_monthly_usd: number;
  alert_threshold: number;
  providers_configured: string[];
  has_platform_key: boolean;
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

/** GET /api/providers — 可用 provider 列表（含是否已配置） */
export async function fetchProviders(): Promise<ProviderInfo[]> {
  const { data } = await sidecar.get<{ providers: ProviderInfo[] }>(
    "/api/providers"
  );
  return data.providers ?? [];
}

/** POST /api/config/verify — 验证 key 是否有效（不存储） */
export async function verifyKey(
  provider: string,
  key: string
): Promise<VerifyResult> {
  const { data } = await sidecar.post<VerifyResult>("/api/config/verify", {
    provider,
    key,
  });
  return data;
}

/** POST /api/config/key — 存储 provider key 到 keyring */
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

/** GET /api/config — 读取当前配置 */
export async function fetchConfig(): Promise<AppConfig> {
  const { data } = await sidecar.get<AppConfig>("/api/config");
  return data;
}

/** POST /api/config — 更新非敏感配置字段 */
export async function updateConfig(
  patch: Partial<AppConfig>
): Promise<{ updated: Record<string, unknown> }> {
  const { data } = await sidecar.post<{ updated: Record<string, unknown> }>(
    "/api/config",
    patch
  );
  return data;
}

/** 货币符号 */
export function currencySymbol(currency: string): string {
  return currency === "CNY" ? "¥" : "$";
}

/** 紧凑数字格式化：0.0284 → "0.0284"，0 → "0.0000" */
export function fmt(n: number, digits = 4): string {
  if (!Number.isFinite(n)) return "—";
  // 小额消费（< 1 分）显示更高精度，否则 $0.000027 会被舍入成 $0.0000 看不出计费
  if (n > 0 && n < 0.01) return n.toFixed(6);
  return n.toFixed(digits);
}

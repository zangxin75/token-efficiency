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

/** 货币符号 */
export function currencySymbol(currency: string): string {
  return currency === "CNY" ? "¥" : "$";
}

/** 紧凑数字格式化：0.0284 → "0.0284"，0 → "0.0000" */
export function fmt(n: number, digits = 4): string {
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

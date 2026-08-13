/**
 * Backend client.
 *
 * Every call can fail with the API down; callers get a typed `ApiResult` rather
 * than an exception or a fabricated empty list, so the UI can say "backend
 * unreachable" instead of silently rendering "no instruments".
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  asset_class: string;
  base_currency: string | null;
  quote_currency: string | null;
  exchange: string | null;
  timezone: string;
  is_active: boolean;
}

export interface DatasetQuality {
  timeframe: string;
  provider_id: string;
  score: number;
  coverage_start: string | null;
  coverage_end: string | null;
  expected_bars: number;
  actual_bars: number;
  open_findings: number;
  is_training_eligible: boolean;
  evaluated_at: string | null;
}

export interface Finding {
  id: string;
  issue: string;
  severity: "info" | "warning" | "error" | "critical";
  timeframe: string;
  window_start: string;
  window_end: string;
  detected_at: string;
  affected_rows: number;
  expected: string | null;
  observed: string | null;
}

export interface DataQuality {
  instrument_id: string;
  symbol: string;
  datasets: DatasetQuality[];
  findings: Finding[];
}

export interface DependencyHealth {
  name: string;
  healthy: boolean;
  detail: string | null;
  latency_ms: number | null;
}

export interface Health {
  status: string;
  version: string;
  environment: string;
  safe_mode: boolean;
  safe_mode_reasons: string[];
  dependencies: DependencyHealth[];
}

async function request<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return { ok: false, error: body.message ?? `HTTP ${response.status}` };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "network error" };
  }
}

export interface SessionStatus {
  instrument_id: string;
  symbol: string;
  at: string;
  is_open: boolean;
  timezone: string;
  market_code: string;
  active_sessions: string[];
  holiday: string | null;
  next_open: string | null;
  next_close: string | null;
}

export interface Holiday {
  market_code: string;
  holiday_date: string;
  kind: string;
  name: string;
  opens_at: string | null;
  closes_at: string | null;
}

export interface Bar {
  event_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  tick_volume: number | null;
  spread: number | null;
  revision: number;
  quality_score: number;
}

export interface BarsResponse {
  instrument_id: string;
  symbol: string;
  timeframe: string;
  as_of: string;
  count: number;
  training_eligible: boolean;
  bars: Bar[];
}

export interface FeatureSpec {
  name: string;
  version: number;
  lookback: number;
  description: string;
  tags: string[];
}

export interface FeatureRow {
  event_time: string;
  source_revision: number;
  values: Record<string, number | null>;
}

export interface FeaturesResponse {
  instrument_id: string;
  symbol: string;
  timeframe: string;
  as_of: string;
  count: number;
  materialized_values: number;
  materialized_features: number;
  rows: FeatureRow[];
}

export interface SymbolProfile {
  kind: string;
  profile_version: number;
  as_of: string;
  computed_at: string;
  sample_size: number;
  coverage_start: string | null;
  coverage_end: string | null;
  data: Record<string, unknown>;
  warnings: string[];
}

export interface SymbolDna {
  instrument_id: string;
  symbol: string;
  timeframe: string;
  as_of: string;
  profiles: SymbolProfile[];
  unavailable: Record<string, string>;
}

/**
 * One horizon of market memory. Fields beyond `horizon`/`available` are absent
 * when the horizon could not be computed, which is why they are optional —
 * an unavailable horizon is a real answer, not a hole to fill with zeros.
 */
export interface MemoryHorizon {
  horizon: string;
  available: boolean;
  reason?: string;
  bars?: number;
  return_pct?: number;
  realized_vol?: number;
  position_in_range?: number | null;
  max_drawdown_pct?: number;
  max_runup_pct?: number;
  trend?: string | null;
  trend_strength?: number | null;
  window_start?: string;
  window_end?: string;
}

/**
 * `as_of` is always sent explicitly. The backend refuses an implicit "now" on
 * historical reads, and mirroring that here keeps the client honest: the UI
 * states the knowledge cutoff it asked for rather than letting one be assumed.
 */
function nowIso(): string {
  return new Date().toISOString();
}

/** One analyst's reading, from `/brain/think`. */
export interface Opinion {
  analyst: string;
  decision: string;
  conviction: number;
  reason: string;
  abstained?: boolean;
}

/** The reasoning chain behind one proposal. */
export interface Proposal {
  symbol: string;
  timeframe: string;
  as_of: string;
  decision: string;
  conviction: number;
  brain_version: number;
  authorises_execution: boolean;
  regime: Record<string, unknown>;
  council: Opinion[];
  meta: Record<string, unknown>;
  adversarial: Record<string, unknown>;
  scenarios: { name: string; description: string; preferred: boolean; rationale: string }[];
  invalidation: string | null;
  uncertainty: Record<string, unknown>;
  wait_reasons: string[];
  stages: string[];
}

/** Each block reports its own availability, so one gap never sinks the rest. */
export interface WorldStateBlock {
  available: boolean;
  reason?: string;
  [key: string]: unknown;
}

export interface WorldState {
  symbol: string;
  timeframe: string;
  as_of: string;
  price: WorldStateBlock;
  session: WorldStateBlock;
  freshness: WorldStateBlock;
  features: WorldStateBlock;
  memory: WorldStateBlock;
  dna: WorldStateBlock;
  quality: WorldStateBlock;
}

/** Measured cross-instrument correlation, from stored DNA snapshots. */
export interface MarketMap {
  timeframe: string;
  as_of: string;
  instruments_considered: number;
  snapshots_used: number;
  oldest_snapshot: string | null;
  measured_pairs: number;
  pairs: {
    a: string;
    b: string;
    correlation: number;
    aligned_bars: number | null;
    clustered: boolean;
  }[];
  clustered_pairs: number;
  cluster_threshold: number;
  unmeasured: string[];
  note: string;
  freshness: string;
}

export interface Scanner {
  timeframe: string;
  as_of: string;
  instruments: {
    instrument_id: string;
    symbol: string;
    asset_class: string;
    data_age_seconds: number | null;
    volatility_snapshot: string | null;
    tendency: string | null;
    autocorrelation: number | null;
    profiles_available: string[];
  }[];
  without_profiles: string[];
  not_a_signal_list: boolean;
  note: string;
}

/** The redacted deployment configuration from `/system/settings`. */
export interface SystemSettings {
  app: Record<string, string | number | boolean>;
  collector: {
    provider: string;
    interval_seconds: number;
    watchlist_size: number;
    symbols: string[];
  };
  ingestion: {
    max_retries: number;
    backoff_base_seconds: number;
    chunk_days: number;
    min_quality_score: number;
  };
  execution: {
    enabled: boolean;
    dry_run: boolean;
    require_auth: boolean;
    max_risk_r_per_order: number;
  };
  retention: {
    table: string;
    keep_days: number;
    reason: string;
    protected: string | null;
    protect_reason: string | null;
  }[];
  read_only: boolean;
  note: string;
}

/** What `/decisions/posture` answers: can this deployment trade right now? */
export interface Posture {
  can_trade: boolean;
  blockers: string[];
  policy: {
    execution_enabled: boolean;
    dry_run: boolean;
    require_auth: boolean;
    max_risk_r_per_order: number;
  };
  routes: { mutating: string[]; ungated: string[] };
  operational_rows: Record<string, number>;
  note: string;
}

export interface ReadinessCheck {
  name: string;
  grade: "blocking" | "important" | "advisory";
  passed: boolean;
  detail: string;
  rationale: string;
}

export interface Readiness {
  checked_at: string;
  safe_to_trade: boolean;
  blocking_failures: string[];
  important_failures: string[];
  passed: number;
  total: number;
  checks: ReadinessCheck[];
  note: string;
}

export const api = {
  health: () => request<Health>("/health/ready"),
  systemSettings: () => request<SystemSettings>("/api/v1/system/settings"),
  marketMap: (limit = 25) =>
    request<MarketMap>(`/api/v1/market-map?limit=${limit}`),
  scanner: (limit = 40) =>
    request<Scanner>(`/api/v1/market-map/scanner?limit=${limit}`),
  posture: () => request<Posture>("/api/v1/decisions/posture"),
  proposal: (instrumentId: string, timeframe = "H1") =>
    request<Proposal>(`/api/v1/brain/think/${instrumentId}?timeframe=${timeframe}`),
  worldState: (instrumentId: string, timeframe = "H1") =>
    request<WorldState>(`/api/v1/world-state/${instrumentId}?timeframe=${timeframe}`),
  readiness: () => request<Readiness>("/api/v1/decisions/readiness"),
  instruments: () => request<Instrument[]>("/api/v1/instruments"),
  dataQuality: (instrumentId: string) =>
    request<DataQuality>(`/api/v1/data-quality/${instrumentId}`),
  sessionStatus: (instrumentId: string) =>
    request<SessionStatus>(`/api/v1/sessions/${instrumentId}`),
  holidays: (marketCode?: string) =>
    request<Holiday[]>(
      `/api/v1/sessions${marketCode ? `?market_code=${encodeURIComponent(marketCode)}` : ""}`,
    ),
  bars: (instrumentId: string, timeframe = "H1", lookback = 400, asOf = nowIso()) =>
    request<BarsResponse>(
      `/api/v1/bars?instrument_id=${instrumentId}&timeframe=${timeframe}` +
        `&lookback=${lookback}&as_of=${encodeURIComponent(asOf)}`,
    ),
  featureCatalog: () => request<FeatureSpec[]>("/api/v1/features/catalog"),
  memory: (instrumentId: string, timeframe = "H1") =>
    request<{ horizons: MemoryHorizon[]; agreement: Record<string, unknown> }>(
      `/api/v1/memory/${instrumentId}?timeframe=${timeframe}`,
    ),
  episodes: (instrumentId: string, timeframe = "H1", limit = 200) =>
    request<{
      stored: number;
      matured: number;
      count: number;
      distribution: Record<string, unknown>;
      episodes: {
        event_time: string;
        outcome_ready_at: string;
        entry_price: number;
        max_up_pct: number | null;
        max_down_pct: number | null;
        forward_return_pct: number | null;
      }[];
    }>(`/api/v1/episodes/${instrumentId}?timeframe=${timeframe}&limit=${limit}`),
  symbolDna: (instrumentId: string, timeframe = "H1") =>
    request<SymbolDna>(`/api/v1/symbol-dna/${instrumentId}?timeframe=${timeframe}`),
  features: (instrumentId: string, timeframe = "H1", lookback = 200, asOf = nowIso()) =>
    request<FeaturesResponse>(
      `/api/v1/features/${instrumentId}?timeframe=${timeframe}` +
        `&lookback=${lookback}&as_of=${encodeURIComponent(asOf)}`,
    ),
};

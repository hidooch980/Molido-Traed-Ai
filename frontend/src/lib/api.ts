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

/**
 * The key this container uses to call the API, server-side only.
 *
 * Deliberately not NEXT_PUBLIC_: anything with that prefix is inlined into the
 * browser bundle, and a credential shipped to every visitor is not a
 * credential. Every page here is a server component with `force-dynamic`, so
 * the fetch happens in this container and the header never reaches a browser.
 *
 * Absent means no header, which is correct while the API allows anonymous
 * reads. The moment MOLIDO_REQUIRE_AUTH is turned on without this being set,
 * every page returns an error - which is why the two have to move together.
 */
const INTERNAL_KEY = process.env.MOLIDO_INTERNAL_API_KEY ?? "";

/**
 * The signed-in visitor's session, forwarded to the API.
 *
 * Without this the API sees an anonymous caller on every request, and an
 * anonymous caller holds `READ` - so every instrument, bar, journal entry,
 * risk limit and account figure on this deployment was readable by anybody who
 * knew the path. The pages were gated by the middleware and the data
 * underneath them was not, which is the more expensive half of the pair.
 *
 * Forwarded rather than replaced by a service key. A single privileged
 * identity for every visitor would work and would quietly hand a viewer
 * whatever an owner can read; passing the cookie keeps the permission the API
 * applies the permission the person actually has.
 *
 * `cookies()` only exists inside a request, and every page here is
 * `force-dynamic` so there always is one - but a build-time call would throw
 * rather than return nothing, and a thrown error in a data reader is a page
 * that says "backend unreachable" about a backend that is fine.
 */
async function sessionHeader(): Promise<Record<string, string>> {
  try {
    const { cookies } = await import("next/headers");
    const jar = await cookies();
    const session = jar.get("molido_session")?.value;
    return session ? { cookie: `molido_session=${session}` } : {};
  } catch {
    return {};
  }
}

async function request<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      cache: "no-store",
      headers: {
        accept: "application/json",
        ...(INTERNAL_KEY ? { "X-API-Key": INTERNAL_KEY } : {}),
        ...(await sessionHeader()),
      },
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

/** One account that can sign in, from `/users`. */
export interface UserRow {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  /** Stated rather than inferred: an account nobody has ever signed in to and
   *  one that was switched off look identical from the outside otherwise. */
  can_sign_in: boolean;
  last_login_at: string | null;
}

export interface UsersView {
  count: number;
  users: UserRow[];
  assignable_roles: string[];
}

/** One recorded account, from `/risk/challenge-accounts`.
 *
 *  Three kinds share the shape. A challenge and a funded account are measured
 *  against a rulebook somebody else wrote; a live account is the holder's own
 *  money and carries no rulebook at all, which is why every rulebook field
 *  here is nullable.
 */
export interface ChallengeAccountView {
  id: string;
  label: string;
  kind: "challenge" | "funded" | "live";
  provider: string | null;
  program: string | null;
  phase: string | null;
  starting_balance: string | null;
  currency: string | null;
  currency_per_r: string | null;
  rulebook_key: string | null;
  rulebook_available: boolean;
  /** Whether the holder has checked the transcribed rules against their own
   *  contract. Until they have, tracking stays shut - a confident verdict
   *  about the wrong document is worse than no verdict.
   *
   *  **Named for the field the API actually sends.** It was declared as
   *  `confirmed` here while the server sent `rules_confirmed`, so the value
   *  read `undefined` on every account and the status pill said "unconfirmed"
   *  for all of them - including the ones somebody had confirmed. TypeScript
   *  could not catch it: the type was a claim about a payload it never saw. */
  rules_confirmed: boolean;
  /** False on a live account for a reason that is not a missing step, so
   *  `why_not` carries the sentence rather than the page guessing. */
  tracking_available: boolean;
  why_not: string | null;
  /** Switched off rather than deleted. An account out of measurement keeps
   *  every fact it holds; deleting the row would take the history with it. */
  is_active: boolean;
}

export interface ChallengeAccountsView {
  accounts: ChallengeAccountView[];
  total: number;
  /** Counts per kind. Live accounts are in the total and out of the
   *  confirmation figures below - there is nothing about them to confirm. */
  by_kind: Record<string, number>;
  /** How many are switched on. */
  active: number;
  confirmed: number;
  unconfirmed: number;
  trackable: number;
  note: string;
}

/** One connection, from `/brokers`. */
export interface Connection {
  name: string;
  connected?: boolean;
  simulated?: boolean;
  role: string;
  note?: string;
}

/** The third brain's verdict, from `/brain/context/{id}`. */
export interface BrainContextView {
  symbol: string;
  timeframe: string;
  as_of: string;
  proposal: { decision: string; conviction: number };
  verdict: {
    stance: "clear" | "caution" | "stand_aside";
    scale: number;
    reasons: string[];
    abstained: string[];
    method: string;
    version: number;
  };
  signals: {
    crowd_tilt: number | null;
    rate_differential: number | null;
    seconds_to_close: number | null;
    gap_seconds: number | null;
  };
  signal_errors: Record<string, string>;
  binding_at: string;
}

export interface BrokerView {
  market_data: Connection;
  execution: Connection;
  metatrader: {
    name: string;
    installed_on_host: boolean;
    reachable_from_application: boolean;
    terminal_path: string;
    role: string;
    blocked_by: string[];
    /** One row per terminal, straight from what each expert publishes.
     *  `available: false` rows carry a `reason` instead of figures. */
    terminals: Record<
      string,
      {
        available: boolean;
        reason?: string;
        login?: number;
        server?: string | null;
        currency?: string | null;
        balance?: number;
        equity?: number;
        state?: { connected?: boolean };
      }
    >;
    connected_terminals: number;
  };
  challenge_providers: string[];
  no_broker_catalogue_here: boolean;
  why: string;
}

export interface RulebookEntry {
  key: string;
  provider: string;
  program: string;
  phase: string;
  source: string;
  retrieved: string;
  confirmed_by_holder: boolean;
  profit_target_pct: number | string;
  max_daily_drawdown_pct: number | string;
  max_total_drawdown_pct: number | string;
  total_drawdown_trailing: boolean | null;
  min_trading_days: number | string;
  max_trading_days: number | string;
  allowance_basis: string | null;
  notes: string[];
}

export interface RulebookView {
  rulebooks: RulebookEntry[];
  providers: string[];
  none_are_confirmed: boolean;
  note: string;
}

/** Hard and soft limits, from `/risk/limits`. */
export interface RiskLimits {
  hard: Record<string, number>;
  soft: Record<string, number>;
  portfolio: Record<string, number>;
  hard_limits_are_frozen: boolean;
  note: string;
}

export interface ExecutionPolicyView {
  execution_enabled: boolean;
  dry_run: boolean;
  require_auth: boolean;
  max_risk_r_per_order: number;
  kill_switch_default_engaged: boolean;
  kill_switch_reason: string;
  required_approvals: string[];
  max_authorisation_age_seconds: number;
  broker: { name: string; simulated: boolean; slippage: number; orders: number };
  api_can_place_orders: boolean;
  api_can_disengage_kill_switch: boolean;
  note: string;
}

export interface LearningThresholds {
  scorecard: { min_trials: number; confidence_z: number; why: string };
  registry: {
    min_evaluation_sample: number;
    min_overlap: number;
    promotion_sigma: number;
    why: string;
  };
  drift: { psi_shifted: number; psi_broken: number; min_sample: number; why: string };
  note: string;
}

export interface DriftView {
  feature_drift: { available: boolean; reason?: string | null };
  concept_drift: { available: boolean; reason?: string | null };
  note: string;
}

export interface RegistryView {
  versions: unknown[];
  champion: null;
  reason: string;
  promotion_requires: Record<string, unknown>;
}

export interface SecurityPosture {
  require_auth: boolean;
  auth_model: string;
  roles: Record<string, string[]>;
  anonymous_holds: string[];
  routes: { mutating: string[]; ungated: string[] };
  gate: Record<string, string>;
  non_read_permissions_require_authentication: boolean;
  note: string;
}

export interface CommandsView {
  allowed: string[];
  allowlist_not_blocklist: boolean;
  why: string;
  trading_requires: string;
  note: string;
}

export interface AccountsView {
  global_kill_switch: { engaged: boolean; reason: string };
  accounts: unknown[];
  tradeable: string[];
  reason: string;
  note: string;
  /**
   * The account the terminal is actually signed into, read from the bridge
   * rather than from a registry somebody has to remember to update.
   * `is_demo` is true only when trade_mode reads exactly 0 - everywhere else
   * in this system an absent trade_mode is treated as real money.
   */
  live_account: {
    login: string | null;
    server: string | null;
    trade_mode: number | null;
    is_demo: boolean;
    balance: number | null;
    equity: number | null;
    currency: string | null;
  };
  /** One row per configured terminal, read from each terminal's own bridge. */
  fleet?: Array<{
    terminal: string;
    connected: boolean;
    reason?: string | null;
    login?: string | null;
    server?: string | null;
    is_demo?: boolean;
    balance?: number | null;
    equity?: number | null;
    floating_pl?: number | null;
    margin?: number | null;
    currency?: string | null;
  }>;
}

export interface ChallengeVerdictView {
  status: string;
  allowed: boolean;
  verdict: string;
  max_additional_risk_r: number | null;
  risk_cap_measurable: boolean;
  headroom: {
    daily: Record<string, unknown>;
    total: Record<string, unknown>;
  };
  breaches: string[];
  warnings: string[];
  unverified: string[];
  rulebook_source: string;
  authorises_execution?: boolean;
}

/** One leak-free fold, from `/learning/walk-forward`. */
export interface WalkForwardFold {
  index: number;
  train_size: number;
  test_size: number;
  purged: number;
  embargoed: number;
}

export interface WalkForwardPlan {
  available: boolean;
  reason?: string;
  folds: WalkForwardFold[];
  embargo_seconds?: number;
  leakage_verified?: boolean;
}

export interface Scorecard {
  strategy: string;
  verdict: string;
  reason: string;
  trials: number;
  wins: number;
  hit_rate: number;
  hit_rate_95ci: [number, number];
  realised_reward_risk: number;
  required_hit_rate: number;
  expectancy_r: number;
  comparisons: number;
}

export interface Breakeven {
  reward_risk: number;
  required_hit_rate: number;
}

/** Inbound webhook posture, from `/integrations/webhooks`. */
export interface WebhookPosture {
  signature: string;
  why_constant_time: string;
  max_age_seconds: number;
  why_max_age: string;
  secret_configured: boolean;
  unset_secret_means: string;
  verified_webhooks_may: string[];
  environment: string;
}

/** Roles and what each carries, from `/access/roles`. */
export interface RoleRow {
  role: string;
  permissions: string[];
  can_execute: boolean;
}

export interface RolesView {
  roles: RoleRow[];
  permissions: string[];
  anonymous_holds: string[];
  note: string;
}

export interface PlanFeature {
  feature: string;
  plan: string;
  why: string;
  condition: string | null;
}

export interface PlansView {
  plans: string[];
  conditions: string[];
  features: PlanFeature[];
  by_plan: Record<
    string,
    { included: string[]; awaiting_condition: string[]; beyond_plan: string[] }
  >;
  billing: string;
  note: string;
}

export interface MatrixRow {
  role: string;
  plan: string;
  holds_execute_permission: boolean;
  plan_includes_live_execution: boolean;
  could_place_an_order: boolean;
}

export interface MatrixView {
  matrix: MatrixRow[];
  roles: string[];
  plans: string[];
  note: string;
  still_refused_here: string;
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

/** One gate in the decision chain, from `/decisions/{id}`. */
export interface DecisionStage {
  stage: string;
  passed: boolean;
  detail: string;
  payload: Record<string, unknown> | null;
}

export interface DecisionTrace {
  symbol: string;
  timeframe: string;
  as_of: string;
  reached_intent: boolean;
  stopped_at: string | null;
  permitted_risk_r: number | null;
  stages: DecisionStage[];
  intent: Record<string, unknown> | null;
  policy: { stop_atr_multiple: number; target_reward_risk: number };
  authorises_execution: boolean;
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

/** One terminal's own account, book and history - never the fleet's. */
export interface TerminalDetail {
  terminal: string;
  state: { usable?: boolean; reason?: string | null };
  account: {
    available?: boolean;
    login?: number | string;
    server?: string;
    balance?: number;
    equity?: number;
    currency?: string;
    reason?: string;
  } | null;
  positions: Array<{
    ticket: number | string;
    symbol: string;
    side: string;
    volume: number;
    price_open: number;
    stop: number | null;
    target: number | null;
    profit: number;
  }>;
  decisions: Array<{
    id: string;
    symbol: string;
    decision: string;
    strategy: string | null;
    timeframe: string | null;
    opened_at: string | null;
    closed_at: string | null;
    outcome: string | null;
    r_multiple: number | null;
    price_source: string | null;
  }>;
  summary: {
    days: number;
    decisions: number;
    resolved: number;
    open: number;
    wins: number;
    hit_rate: number | null;
    total_r: number;
    average_r: number | null;
  };
  note: string;
}

export interface ReadinessCheck {
  name: string;
  grade: "blocking" | "important" | "advisory";
  passed: boolean;
  detail: string;
  rationale: string;
}

/**
 * The three states the backend refuses to conflate. An engine that is running
 * is not an order that is authorised, and a page that shows one and implies
 * the other is what this shape exists to prevent.
 */
export interface OrderAuthorization {
  engine_state: "running" | "stopped";
  kill_switch_state: "engaged" | "released";
  order_authorization_state: "authorized" | "blocked";
  engine_running: boolean;
  kill_switch_released: boolean;
  order_authorized: boolean;
  operational_ready: boolean | null;
  data_fresh: boolean | null;
  account_ready: boolean | null;
  proven_edge: boolean | null;
  risk_approved: boolean | null;
  blocking_reasons: string[];
  advisories: string[];
  note: string;
}

export interface Readiness {
  checked_at: string;
  safe_to_trade: boolean;
  blocking_failures: string[];
  important_failures: string[];
  passed: number;
  total: number;
  checks: ReadinessCheck[];
  /** Absent on a deployment older than the authorization decision. */
  authorization?: OrderAuthorization;
  note: string;
}

export interface PolicyRateRow {
  currency: string;
  area: string;
  bank: string;
  /** Per cent per year, as published. 3.625 means 3.625%. */
  rate: number;
  observed: string;
}

export interface RateDifferential {
  pair: string;
  base: string;
  quote: string;
  /** Base rate minus quote rate. Positive means the base pays more. */
  differential: number;
}

export interface PolicyRatesView {
  /** False when the upstream feed could not be read. Distinct from an empty
   *  table: one means "we do not know", the other means "there is nothing",
   *  and on a screen a stale rate looks exactly like a live one. */
  available: boolean;
  reason?: string;
  rates: PolicyRateRow[];
  differentials: RateDifferential[];
  note?: string;
}

export interface PositioningRow {
  key: string;
  contract: string;
  /** The Tuesday the positions were held. */
  report_date: string;
  /** The Friday it became public. Three days later, and the whole reason
   *  both dates are carried rather than one. */
  published_at: string;
  long: number;
  short: number;
  net: number;
  open_interest: number;
  traders_long: number;
  traders_short: number;
}

export interface PositioningView {
  available: boolean;
  key: string;
  reason?: string;
  known?: string[];
  latest?: PositioningRow;
  net_share?: number | null;
  history?: PositioningRow[];
  note?: string;
}

export interface TerminalRow {
  id: string;
  key: string;
  label: string;
  broker: string;
  kind: string;
  is_active: boolean;
  created_at: string | null;
  /** Whether a heartbeat is arriving. A registration is a claim; this is the
   *  evidence, and the two are different questions on one screen. */
  publishing: boolean;
  usable?: boolean;
  login: number;
  age_seconds?: number | null;
  reason?: string | null;
}

export interface TerminalsView {
  terminals: TerminalRow[];
  total: number;
  publishing: number;
  note: string;
}

export interface SetupView {
  claimed: boolean;
  password_min_length: number;
  self_registration_role: string;
  note: string;
}

export interface AutopilotGate {
  open: boolean;
  detail: string;
}

export interface AutopilotView {
  mode: string;
  reason: string;
  would_send_live_orders: boolean;
  gates: Record<string, AutopilotGate>;
  edge_override_in_use: boolean;
  context: { equity?: number; balance?: number; unmeasured: string[]; complete: boolean } | null;
  rejected_claims: Array<{
    key: string;
    description: string;
    evidence: Record<string, unknown>;
    verdict: { proven: boolean; failures: string[]; passes: string[] };
  }>;
  note: string;
}

export interface ResearchView {
  live_trading_allowed: boolean;
  reason: string;
  proven: Array<{ key: string; description: string; verdict: { proven: boolean } }>;
  rejected: Array<{
    key: string;
    description: string;
    evidence: Record<string, number | string | boolean>;
    verdict: { proven: boolean; failures: string[]; passes: string[] };
  }>;
  requirements: string[];
  sample_needed: Record<string, number | string>;
  note: string;
}

export interface PositionsView {
  available: boolean;
  reason?: string;
  positions: Array<Record<string, unknown>>;
  account: { login?: number; server?: string; equity?: number; balance?: number } | null;
  note: string;
}

export interface OrderStatesView {
  states: string[];
  terminal: string[];
  transitions: Record<string, string[]>;
}

export interface JournalArm {
  recorded: number;
  resolved: number;
  still_open: number;
  first_at: string | null;
  last_at: string | null;
}

export interface JournalComparison {
  /**
   * The reading with its sign. `significant` is `abs(z)` and so is true for a
   * rule losing to its own coin flip as loudly as for one beating it - which
   * painted a z of -2.57 green. Read this instead.
   */
  verdict?: string;
  rule: { trials: number; wins: number; hit_rate: number | null };
  control: { trials: number; wins: number; hit_rate: number | null };
  edge_over_control: number | null;
  z_score: number | null;
  significant: boolean;
  trials_needed_for_2pp: number;
  note: string;
}

export interface JournalView {
  /**
   * Nested by price series, then by arm. The rule runs on the public feed and
   * on the broker's own prices at once, and the two quote the same instrument
   * 33-39% of a stop distance apart — so one count covering both would be one
   * number reporting two different measurements.
   */
  arms: Record<string, Record<string, JournalArm>>;
  /** The public series, kept at the top level so older readers still work. */
  comparison: JournalComparison;
  by_source: Record<string, JournalComparison>;
  /**
   * The same rows read the way the registered claim was measured: rule minus
   * control on the bar they share, averaged per instant. `by_source` counts
   * each arm on its own and so carries the market's move as noise; this
   * subtracts it. Both are published because showing only the stronger would
   * flatter the rule.
   */
  paired_by_source: Record<string, JournalPaired>;
  /**
   * Every timeframe read on its own, each with the threshold its own question
   * earned. The worker records on five and reading them together hid a
   * negative H1 behind three positive fast series, so the split is published
   * rather than left to whoever remembers the constant.
   */
  paired_by_timeframe: Record<string, JournalPaired>;
  /** Resolved instants per timeframe per series. */
  by_timeframe: Record<string, Record<string, number>>;
  why_one_timeframe: string;
  why_a_wider_bar: string;
  why_paired: string;
  /** Broker result minus public result. Null until both have resolved. */
  edge_lost_to_real_prices: number | null;
  why_two_series: string;
  note: string;
}

export interface JournalPaired {
  /**
   * True for the timeframe the live rule decides on, which was named before
   * this data existed. False for a look taken because the data was there -
   * and those carry a threshold widened for how many were taken.
   */
  pre_registered?: boolean;

  /** The sample the t rests on: one per bar, however many symbols ranked. */
  instants: number;
  /** How many decisions went into those instants. Always >= instants. */
  pairs: number;
  mean_difference_r: number | null;
  t_statistic: number | null;
  required_t: number;
  /** "not measured" | "not distinguishable..." | "distinguishable..." */
  verdict: string;
}

export interface EvidenceSeries {
  instants_resolved: number;
  instants_needed: number | null;
  fraction: number | null;
  /** The flattering count. Shown labelled, never as the progress figure. */
  decisions_resolved: number;
  instants_per_week: number | null;
  answerable_on: string | null;
  open_requirements: string[];
  met_requirements: string[];
  what_the_date_means: string;
  why_instants: string;
  the_assumption: string;
  /**
   * The per-instant spread the sample size was computed from, and whether it
   * came from this series or from the historical claim. The date is the
   * headline here, and it moves with the square of this number - so which of
   * the two it rests on belongs beside it, not only inside a paragraph.
   */
  spread_r: number;
  spread_is_measured: boolean;
}

export interface EvidenceView {
  by_source: Record<string, EvidenceSeries>;
  and_then_what: string;
}

export interface CalendarRelease {
  at: string | null;
  title: string;
  currency: string;
  impact: string;
  forecast: string | null;
  previous: string | null;
  url: string | null;
  all_day: boolean;
}

export interface CalendarView {
  as_of: string;
  timezone: string;
  count: number;
  releases: CalendarRelease[];
  next: CalendarRelease | null;
  hours_to_next: number | null;
  /** Non-null when the feed's clock appears to have moved under the parser. */
  clock_warning: string | null;
  note: string;
}

export interface TimezoneView {
  utc: string;
  places: { name: string; offset: number; local: string }[];
  broker_offset_known: boolean;
  note: string;
  /** The four liquidity sessions, hours shown on Iran's fixed clock -
   *  computed server-side against each session's real timezone so DST in
   *  Sydney or London cannot quietly shift the numbers half the year. */
  sessions?: {
    session: string;
    timezone: string;
    is_open: boolean;
    opens_local: string;
    closes_local: string;
    opens_iran: string;
    closes_iran: string;
  }[];
}

export interface EquityPoint {
  at: string;
  equity: number;
  balance: number;
  /** equity - balance: open positions carrying their entry spread. */
  floating: number;
}

export interface EquityView {
  available: boolean;
  account?: string;
  points: EquityPoint[];
  summary?: {
    samples: number;
    first_at: string | null;
    last_at: string | null;
    peak_equity: number | null;
    peak_day_open_balance: number | null;
    note: string;
  };
  reason?: string | null;
  note?: string;
}

export interface RealisedView {
  available: boolean;
  reason?: string | null;
  net: number | null;
  trades?: number;
  gross?: number;
  swap?: number;
  commission?: number;
  by_symbol: Array<{
    symbol: string;
    net: number;
    trades: number;
    wins: number;
    /** null until there are enough trades to divide by. */
    hit_rate: number | null;
  }>;
  window_days?: number;
  note?: string;
}

export const api = {
  realised: (days = 30) =>
    request<RealisedView>(`/api/v1/execution/realised?days=${days}`),
  equity: (limit = 500) =>
    request<EquityView>(`/api/v1/execution/equity?limit=${limit}`),
  calendar: () => request<CalendarView>("/api/v1/instruments/tools/calendar"),
  timezones: () => request<TimezoneView>("/api/v1/instruments/tools/timezones"),
  journal: () => request<JournalView>("/api/v1/learning/journal"),
  evidence: () => request<EvidenceView>("/api/v1/learning/readiness"),
  orderStates: () => request<OrderStatesView>("/api/v1/execution/order-states"),
  research: () => request<ResearchView>("/api/v1/learning/research"),
  positions: () => request<PositionsView>("/api/v1/execution/positions"),
  accountStates: () =>
    request<{ accounts: Array<{ account: string; active: boolean; reason: string }> }>(
      "/api/v1/execution/accounts/state",
    ),
  autopilot: () => request<AutopilotView>("/api/v1/execution/autopilot"),
  setup: () => request<SetupView>("/api/v1/users/setup"),
  /** Every registered MetaTrader terminal, with whether it is actually
   *  publishing. Eleven rows that all look configured and none of which
   *  are alive is the state this call exists to make visible. */
  terminals: () => request<TerminalsView>("/api/v1/terminals"),
  /** What the world's central banks charge, and the gap between any two of
   *  them. The only reading in this client that is not derived from a price. */
  policyRates: () => request<PolicyRatesView>("/api/v1/fundamentals/policy-rates"),
  /** Where the large speculators sit in one futures market, as of what had
   *  actually been published - not as of the Tuesday the report describes. */
  positioning: (key: string) =>
    request<PositioningView>(
      `/api/v1/fundamentals/positioning?key=${encodeURIComponent(key)}`,
    ),
  /** Everybody who exists. Behind `users.manage`, so an unauthorised caller
   *  gets a refusal rather than an empty list - a page that renders "no users"
   *  when it was actually refused is a page that lies quietly. */
  users: () => request<UsersView>("/api/v1/users"),
  health: () => request<Health>("/health/ready"),
  telegram: () =>
    request<{
      configured: boolean;
      enabled: boolean;
      masked_token: string | null;
      chat_ids: string[];
      recipients: number;
      source: string;
      ready: boolean;
      reachable?: boolean;
      detail?: string;
      reason?: string;
      allowed_commands?: string[];
      why_read_only?: string;
    }>("/api/v1/integrations/telegram"),
  systemSettings: () => request<SystemSettings>("/api/v1/system/settings"),
  riskLimits: () => request<RiskLimits>("/api/v1/risk/limits"),
  challenge: (params: Record<string, string | number>) =>
    request<ChallengeVerdictView>(
      `/api/v1/risk/challenge?${new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()}`,
    ),
  brokers: () => request<BrokerView>("/api/v1/brokers"),
  terminalDetail: (terminal: string) =>
    request<TerminalDetail>(
      `/api/v1/brokers/terminals/${encodeURIComponent(terminal)}`,
    ),
  rulebooks: () => request<RulebookView>("/api/v1/risk/rulebooks"),
  executionPolicy: () => request<ExecutionPolicyView>("/api/v1/execution/policy"),
  accounts: () => request<AccountsView>("/api/v1/execution/accounts"),
  /** Prop-firm challenge accounts. A different kind of account from the broker
   *  connection above and deliberately a separate call: one is "which terminal
   *  is logged in", the other is "which sets of somebody else's rules are we
   *  being measured against". Merging them would make a page that cannot say
   *  which of the two is missing. */
  challengeAccounts: () =>
    request<ChallengeAccountsView>("/api/v1/risk/challenge-accounts"),
  learningThresholds: () =>
    request<LearningThresholds>("/api/v1/learning/thresholds"),
  drift: () => request<DriftView>("/api/v1/learning/drift"),
  walkForward: (params: Record<string, number>) =>
    request<WalkForwardPlan>(
      `/api/v1/learning/walk-forward?${new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()}`,
    ),
  scorecard: (params: Record<string, number>) =>
    request<Scorecard>(
      `/api/v1/learning/scorecard?${new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()}`,
    ),
  breakeven: (rewardRisk: number) =>
    request<Breakeven>(`/api/v1/learning/breakeven?reward_risk=${rewardRisk}`),
  modelRegistry: () => request<RegistryView>("/api/v1/learning/registry"),
  security: () => request<SecurityPosture>("/api/v1/integrations/security"),
  roles: () => request<RolesView>("/api/v1/access/roles"),
  plans: () => request<PlansView>("/api/v1/access/plans"),
  accessMatrix: () => request<MatrixView>("/api/v1/access/matrix"),
  commands: () => request<CommandsView>("/api/v1/integrations/commands"),
  webhooks: () => request<WebhookPosture>("/api/v1/integrations/webhooks"),
  marketMap: (limit = 25) =>
    request<MarketMap>(`/api/v1/market-map?limit=${limit}`),
  scanner: (limit = 40) =>
    request<Scanner>(`/api/v1/market-map/scanner?limit=${limit}`),
  posture: () => request<Posture>("/api/v1/decisions/posture"),
  /** The third brain: slow context, and the right to say "not now". */
  brainContext: (instrumentId: string, timeframe = "H1") =>
    request<BrainContextView>(
      `/api/v1/brain/context/${instrumentId}?timeframe=${timeframe}`,
    ),
  proposal: (instrumentId: string, timeframe = "H1") =>
    request<Proposal>(`/api/v1/brain/think/${instrumentId}?timeframe=${timeframe}`),
  worldState: (instrumentId: string, timeframe = "H1") =>
    request<WorldState>(`/api/v1/world-state/${instrumentId}?timeframe=${timeframe}`),
  readiness: () => request<Readiness>("/api/v1/decisions/readiness"),
  decisionChain: (instrumentId: string, timeframe = "H1") =>
    request<DecisionTrace>(
      `/api/v1/decisions/${instrumentId}?timeframe=${timeframe}`,
    ),
  instruments: () => request<Instrument[]>("/api/v1/instruments"),
  /** Every active instrument's market state in one call. The per-instrument
   *  version below is still right for a detail page; using it for a list meant
   *  one round trip per row, which is why that list used to be truncated. */
  allSessionStatus: () => request<SessionStatus[]>("/api/v1/sessions/status"),
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

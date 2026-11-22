"""Rule catalogs for the V2 engines. Each rule has exactly one status."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.status import RuleStatus


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    status: RuleStatus
    source: str
    notes: str = ""


def _counts(rules: tuple[Rule, ...]) -> dict[str, int]:
    counts = {s.value: 0 for s in RuleStatus}
    for rule in rules:
        counts[rule.status.value] += 1
    return counts


# --- Key Levels ---
_NY = "FX daily close at 17:00 America/New_York (DST-aware); see docs/v2-engines-fa.md"
_MISSING = "no verified canonical formula found; not replaced with a pivot or midpoint"

KEY_LEVEL_RULES: tuple[Rule, ...] = (
    Rule("PREV_NY_CLOSE", "Previous New York close, TZ/DST trading day",
         RuleStatus.TESTED, _NY),
    Rule("DAILY_HL_COMPLETED", "Completed trading-day high and low are frozen",
         RuleStatus.TESTED, _NY),
    Rule("DAILY_HL_DEVELOPING", "In-progress day H/L marked incomplete, never as final",
         RuleStatus.TESTED, _NY),
    Rule("DAILY_SWEEP", "Wick beyond a completed H/L with close back inside",
         RuleStatus.TESTED, "V2 spec; exact wick rule is the documented default"),
    Rule("DAILY_BREAKOUT", "Close beyond a completed daily high or low",
         RuleStatus.TESTED, "V2 spec"),
    Rule("DAILY_REVERSAL", "Sweep of a completed H/L then close back through the level",
         RuleStatus.TESTED, "V2 spec"),
    Rule("ROUND_TICK_ALIGNED", "Round numbers snapped to the symbol tick size",
         RuleStatus.TESTED, "V2 spec"),
    Rule("ROUND_MAJOR_MINOR", "Major vs minor steps are classified separately",
         RuleStatus.TESTED, "V2 spec; default step sizes are RESEARCH"),
    Rule("NO_LOOKAHEAD_LEVELS", "Completed levels ignore unclosed and future bars",
         RuleStatus.TESTED, "V2 data rules"),
    Rule("WEEKLY_MAP_DEFINITION", "Canonical Weekly MAP formula",
         RuleStatus.RESEARCH, _MISSING,
         "Sources checked: CME pages, TradingView 'Weekly Map' scripts, public outlook writeups. "
         "No single official formula. Not implemented as weekly mid or classic pivots."),
    Rule("VALID_BREAK_EVEN_DEFINITION", "Canonical Valid Break-Even as a key level",
         RuleStatus.RESEARCH, _MISSING,
         "Distinct from a trade's P&L break-even. No standalone published formula found. "
         "Pro BTB models four BE zones separately and is not reused as a substitute here."),
    Rule("ROUND_DEFAULT_STEPS", "Default major/minor step sizes per symbol class",
         RuleStatus.RESEARCH, "not universally standardised; caller should pass steps"),
)

# --- SP2L (Poursamadi Spike–2Leg) ---
_SP = "https://poursamadi.com/sp2l-strategy/"
_SP_TF = "third-party encodings disagree; prices not emitted"

SP2L_RULES: tuple[Rule, ...] = (
    Rule("SP2L_SPIKE", "Detect a sharp directional spike", RuleStatus.TESTED, _SP),
    Rule("SP2L_PGAP_REQUIRED", "A spike without a price gap is not valid",
         RuleStatus.TESTED, _SP),
    Rule("SP2L_LEG1", "The spike itself is the first leg", RuleStatus.TESTED, _SP),
    Rule("SP2L_LEG2", "Second-leg correction: bull takes prior low, bear takes prior high",
         RuleStatus.TESTED, _SP),
    Rule("SP2L_HL_LH", "Track higher lows (bull) or lower highs (bear)",
         RuleStatus.TESTED, "V2 spec + TradingFinder description of HL/LH retests"),
    Rule("SP2L_LEG_RATIO", "Record the second-leg to first-leg length ratio",
         RuleStatus.TESTED, "V2 spec; no official ratio cutoff is claimed"),
    Rule("SP2L_BREAKOUT", "Spike breaks a prior swing extreme",
         RuleStatus.TESTED, "V2 spec"),
    Rule("SP2L_FALSE_BREAKOUT", "Close back through the broken extreme after a breakout",
         RuleStatus.TESTED, "V2 spec"),
    Rule("SP2L_RETEST", "Price returns to an HL/LH or the broken level",
         RuleStatus.TESTED, "V2 spec + TradingFinder"),
    Rule("SP2L_INVALIDATION", "Opposite close through the spike origin invalidates",
         RuleStatus.TESTED, "V2 spec; origin is the documented spike start"),
    Rule("SP2L_ENTRY_WAIT", "Entry/SL/TP stay WAIT unless placement rules are SPECIFIED",
         RuleStatus.TESTED, _SP_TF,
         "Official page names SL behind the spike-start candle and TP 1:1, but "
         "TradingFinder encodings differ on the fill. Prices are not emitted."),
    Rule("SP2L_BULL_AND_BEAR", "Bull and bear fixtures are both supported",
         RuleStatus.TESTED, _SP),
    Rule("SP2L_PGAP_EXACT", "Exact P-Gap measurement (open vs prior extreme)",
         RuleStatus.RESEARCH, _SP,
         "Default: bull open above prior high; bear open below prior low."),
    Rule("SP2L_SPIKE_THRESHOLDS", "Min bars, ATR multiple, body ratio for a spike",
         RuleStatus.RESEARCH, "not pinned on the official page"),
    Rule("SP2L_ENTRY_PRICE", "Exact entry price", RuleStatus.RESEARCH, _SP_TF),
    Rule("SP2L_STOP_LOSS", "Exact stop-loss tick", RuleStatus.RESEARCH, _SP_TF),
    Rule("SP2L_TAKE_PROFIT", "Exact take-profit tick", RuleStatus.RESEARCH, _SP_TF),
    Rule("SP2L_ABCD", "AB=CD projection as a target",
         RuleStatus.RESEARCH, "mentioned by TradingFinder, not required on the official page"),
)

# --- Spike & Imbalance ---
_SI = "reuses app.agents.analyzers.smc.fair_value_gaps; no copied detector"

SPIKE_IMBALANCE_RULES: tuple[Rule, ...] = (
    Rule("SI_ATR_SPIKE", "Flag a bar or short run whose range is a multiple of ATR",
         RuleStatus.TESTED, "V2 spec; multiple is RESEARCH"),
    Rule("SI_FVG_ADAPTER", "Detect FVGs by calling the existing SMC helper",
         RuleStatus.TESTED, _SI),
    Rule("SI_FVG_MITIGATION", "A gap is mitigated when later price trades through it",
         RuleStatus.TESTED, "matches SM04 fill rule; verified by agreement test"),
    Rule("SI_IMBALANCE_AS_FVG", "Imbalance/inefficiency reported as the FVG itself",
         RuleStatus.TESTED, "Poursamadi/TradingFinder: FVG is the consequence of a spike"),
    Rule("SI_NO_PROBABILITY_CLAIM", "No continuation or reversal probability is invented",
         RuleStatus.TESTED, "V2: no guessed rule as final"),
    Rule("SI_ATR_MULTIPLE", "ATR multiple that defines a spike",
         RuleStatus.RESEARCH, "default 2.5, not a source-locked constant"),
    Rule("SI_VOLUME_THRESHOLD", "Volume confirmation cutoff",
         RuleStatus.RESEARCH, "used only when tick volume is present"),
    Rule("SI_CONTINUATION_PROBABILITY", "Numeric continuation probability",
         RuleStatus.RESEARCH, "not estimated"),
)

# --- Combined scoring adapter ---
SCORING_RULES: tuple[Rule, ...] = (
    Rule("V2_ADAPTER_OFF_DEFAULT", "Combined adapter is off until an env flag is set",
         RuleStatus.TESTED, "V2 integration policy"),
    Rule("V2_NO_RISK_OVERRIDE", "Adapter never overrides Risk Brain",
         RuleStatus.TESTED, "V2 risk policy"),
    Rule("V2_FOUR_ENGINES", "Score consumes Key Levels, SP2L, Spike/Imbalance, and Pro BTB",
         RuleStatus.TESTED, "V2 Phase 5"),
    Rule("V2_NO_DOUBLE_COUNT", "Shared feature families contribute once, with sources listed",
         RuleStatus.TESTED, "V2 scoring: no double counting"),
    Rule("V2_FEATURE_WEIGHTS", "Numeric weights across families",
         RuleStatus.RESEARCH, "equal weight is a placeholder, not a scientific ranking"),
)


KEY_LEVEL_BY_ID = {r.id: r for r in KEY_LEVEL_RULES}
SP2L_BY_ID = {r.id: r for r in SP2L_RULES}
SPIKE_IMBALANCE_BY_ID = {r.id: r for r in SPIKE_IMBALANCE_RULES}
SCORING_BY_ID = {r.id: r for r in SCORING_RULES}


def key_level_counts() -> dict[str, int]:
    return _counts(KEY_LEVEL_RULES)


def sp2l_counts() -> dict[str, int]:
    return _counts(SP2L_RULES)


def spike_imbalance_counts() -> dict[str, int]:
    return _counts(SPIKE_IMBALANCE_RULES)


def scoring_counts() -> dict[str, int]:
    return _counts(SCORING_RULES)

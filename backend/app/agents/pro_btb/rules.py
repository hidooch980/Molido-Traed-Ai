"""Official rule catalog. Each rule has exactly one status.

RESEARCH entries are thresholds or definitions the Drtv_fx video did not pin
down; they stay RESEARCH even though the detector accepts them as parameters.
TESTED entries are process requirements stated in the specification, then
implemented and covered by independent tests. None are VERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.status import RuleStatus


@dataclass(frozen=True)
class Rule:
    id: str
    title_fa: str
    title_en: str
    status: RuleStatus
    source: str
    notes: str


# Process rules taken from the written specification (Drtv_fx video structure
# as recorded in the user's brief). Engineering maturity: TESTED.
_SPEC = "user-spec / Drtv_fx video structure"
_RESEARCH = "not named precisely in the reviewed video; configurable only"

RULES: tuple[Rule, ...] = (
    Rule("STRONG_LEG_ASSESS", "بررسی لگ قدرتمند، ساختار، ریسک و توقف در شرایط نامعتبر",
         "Assess strong-leg power and structure; flag high risk; stop when invalid",
         RuleStatus.TESTED, _SPEC, 
         "Process is specified; numeric cutoffs are separate RESEARCH rules."),
    Rule("BO_CHECK_GAP", "بررسی شکاف (Gap) در کندل BO",
         "Validate the BO candle for a gap",
         RuleStatus.TESTED, _SPEC, "The check is required; the exact gap definition is RESEARCH."),
    Rule("BO_CHECK_FT", "بررسی Follow Through پس از کندل BO",
         "Validate follow-through after the BO candle",
         RuleStatus.TESTED, _SPEC, "The check is required; the exact FT definition is RESEARCH."),
    Rule("BO_CHECK_CLOSE_EXTREME", "بررسی کلوز در انتهای کندل BO",
         "Check that the BO candle closes near its extreme",
         RuleStatus.TESTED, _SPEC, "The check is required; the extreme fraction is RESEARCH."),
    Rule("BO_MISSING_GAP_FT_RAISES_RISK", "نبود Gap یا FT باید ریسک را بالا ببرد",
         "Missing gap or follow-through raises risk",
         RuleStatus.TESTED, _SPEC, 
         "Does not automatically invalidate the BO; it raises a risk flag."),
    Rule("BE_ZONE_LEG1_START", "مدل مستقل منطقه سربه‌سر در ابتدای Leg 1",
         "Independently model the break-even zone at the start of leg 1",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("BE_ZONE_LEG2_START", "مدل مستقل منطقه سربه‌سر در ابتدای Leg 2",
         "Independently model the break-even zone at the start of leg 2",
         RuleStatus.TESTED, _SPEC, "May be absent when a second leg is not found."),
    Rule("BE_ZONE_SPIKE_TOP", "مدل مستقل منطقه سربه‌سر در رأس اسپایک سیکل",
         "Independently model the break-even zone at the cycle spike extreme",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("BE_ZONE_CHANNEL_TOP", "مدل مستقل منطقه سربه‌سر در رأس کانال",
         "Independently model the break-even zone at the channel extreme",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("BE_ZONES_COMPARABLE", "چهار منطقه سربه‌سر باید قابل‌مقایسه باشند",
         "The four break-even zones share one shape and can be compared",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("BTB_ZONE_IS_PRICE_RANGE", "ناحیه BTB به‌صورت محدوده قیمتی ذخیره می‌شود",
         "The BTB area is stored as a price range",
         RuleStatus.TESTED, _SPEC, "How the range is built from the BO is RESEARCH."),
    Rule("RETEST_WAIT_FOR_RETURN", "انتظار برای بازگشت قیمت به ناحیه BTB",
         "Wait for price to return to the BTB range",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("RETEST_MICROCHANNEL", "شناسایی میکروکانال",
         "Detect a microchannel",
         RuleStatus.TESTED, _SPEC, 
         "Detection exists; exact bar-count and strictness are RESEARCH."),
    Rule("RETEST_SP_CH_TR", "تفکیک و شناسایی چرخه SP / CH / TR",
         "Classify spike, channel, and trading-range structure",
         RuleStatus.TESTED, _SPEC, "Labels are emitted; classification thresholds are RESEARCH."),
    Rule("CONFIRM_OR_WAIT", "بدون تأیید وارد نشو؛ علت پذیرش یا رد را ثبت کن",
         "No entry without confirmation; log the accept or reject reason",
         RuleStatus.TESTED, _SPEC, 
         "The process is specified; the exact confirm checklist is RESEARCH."),
    Rule("ENTRY_BULL_AND_BEAR", "پشتیبانی از مثال‌های صعودی و نزولی",
         "Support bullish and bearish examples",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("ENTRY_SL_TP_ONLY_SPECIFIED",
         "ورود، حد ضرر و حد سود فقط از قوانین SPECIFIED یا بالاتر",
         "Entry, stop and target only from rules marked SPECIFIED or better",
         RuleStatus.TESTED, _SPEC, "Otherwise the entry stage emits WAIT."),
    Rule("ENTRY_LOG_RR_INVALIDATION", "ثبت نسبت ریسک به بازده و شرایط ابطال",
         "Log risk-reward and invalidation when they exist",
         RuleStatus.TESTED, _SPEC, "Both are null while placement rules remain RESEARCH."),
    Rule("NO_GUESSED_RULE_AS_FINAL", "هیچ قاعده حدسی به‌عنوان قانون قطعی معرفی نشود",
         "No guessed rule may be presented as definitive",
         RuleStatus.TESTED, _SPEC, ""),
    Rule("ADAPTER_OFF_BY_DEFAULT", "آداپتور خواندنی و به‌صورت پیش‌فرض خاموش",
         "The consumer adapter is read-only and off by default",
         RuleStatus.TESTED, _SPEC, "Enabled only by MOLIDO_PRO_BTB_ENABLED."),
    Rule("ADAPTER_NO_RISK_OVERRIDE", "آداپتور هیچ‌گاه Risk Brain را Override نمی‌کند",
         "The adapter must never override Risk Brain",
         RuleStatus.TESTED, _SPEC, ""),
    # --- RESEARCH: definitions and thresholds the video did not pin down ---
    Rule("DEF_BO_CANDLE", "تعریف دقیق کندل BO",
         "Exact definition of the BO candle",
         RuleStatus.RESEARCH, _RESEARCH, 
         "Detector uses the first close beyond the prior swing extreme."),
    Rule("DEF_GAP", "تعریف دقیق Gap",
         "Exact gap definition",
         RuleStatus.RESEARCH, _RESEARCH, 
         "Detector treats a bull gap as open above the prior high (bear: below prior low)."),
    Rule("DEF_FOLLOW_THROUGH", "تعریف دقیق Follow Through",
         "Exact follow-through definition",
         RuleStatus.RESEARCH, _RESEARCH, 
         "Detector uses the next bar closing beyond the BO extreme."),
    Rule("DEF_BTB_ZONE_CONSTRUCTION", "روش ساخت محدوده BTB",
         "How the BTB price range is constructed",
         RuleStatus.RESEARCH, _RESEARCH, 
         "Detector spans the breakout reference and the BO candle range."),
    Rule("DEF_ENTRY_PRICE", "قانون دقیق قیمت ورود",
         "Exact entry price rule",
         RuleStatus.RESEARCH, _RESEARCH, 
         "No entry price is emitted until this rule is SPECIFIED or better."),
    Rule("DEF_STOP_LOSS", "قانون دقیق حد ضرر",
         "Exact stop-loss rule",
         RuleStatus.RESEARCH, _RESEARCH, 
         "No stop is emitted until this rule is SPECIFIED or better."),
    Rule("DEF_TAKE_PROFIT", "قانون دقیق حد سود",
         "Exact take-profit rule",
         RuleStatus.RESEARCH, _RESEARCH, 
         "No target is emitted until this rule is SPECIFIED or better."),
    Rule("DEF_INVALIDATION", "شرایط دقیق ابطال معامله",
         "Exact trade-invalidation rule",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("DEF_CONFIRMATION_CHECKLIST", "جزئیات تأیید ورود",
         "Exact confirmation checklist",
         RuleStatus.RESEARCH, _RESEARCH, 
         "Default checklist is structural (valid leg, BO found, retest)."),
    Rule("DEF_MICROCHANNEL", "تعریف دقیق میکروکانال",
         "Exact microchannel definition",
         RuleStatus.RESEARCH, _RESEARCH, 
         "Default: N consecutive rising lows (bull) or falling highs (bear)."),
    Rule("DEF_SP_CH_TR_THRESHOLDS", "آستانه‌های تفکیک SP / CH / TR",
         "Numeric thresholds for SP / CH / TR classification",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("DEF_LEG2_IDENTIFICATION", "روش شناسایی Leg 2",
         "How a second leg is identified",
         RuleStatus.RESEARCH, _RESEARCH, "Default: pullback after leg 1, then a new impulse."),
    Rule("PARAM_ATR_PERIOD", "دوره ATR",
         "ATR period",
         RuleStatus.RESEARCH, _RESEARCH, "Default 14."),
    Rule("PARAM_SWING_K", "عرض تأیید سوئینگ",
         "Swing confirmation width",
         RuleStatus.RESEARCH, _RESEARCH, "Default 2 closed bars each side."),
    Rule("PARAM_MIN_LEG_ATR", "حداقل جابه‌جایی لگ نسبت به ATR",
         "Minimum leg displacement in ATR",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_MIN_LEG_BARS", "حداقل تعداد کندل لگ",
         "Minimum bar count in a leg",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_MIN_BODY_RATIO", "حداقل نسبت بدنه به دامنه در لگ",
         "Minimum directional body-to-range ratio",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_MAX_OVERLAP", "حداکثر همپوشانی مجاز لگ",
         "Maximum bar-overlap ratio for a strong leg",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_EXTENDED_ATR", "آستانه لگ بیش‌ازحد کشیده (ریسک بالا)",
         "Extended-leg ATR threshold (high risk)",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_MAX_SINGLE_BAR_SHARE", "سهم یک کندل از کل جابه‌جایی",
         "Maximum share of the leg that a single bar may contribute",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_CLOSE_EXTREME_FRAC", "سهم انتهایی کندل برای کلوز",
         "Fraction of the BO range counted as 'close at the extreme'",
         RuleStatus.RESEARCH, _RESEARCH, "Default 0.25."),
    Rule("PARAM_MIN_BARS_AFTER_BO", "حداقل فاصله تا بررسی بازگشت BTB",
         "Minimum bars after the BO before a retest counts",
         RuleStatus.RESEARCH, _RESEARCH, ""),
    Rule("PARAM_MICROCHANNEL_BARS", "تعداد کندل میکروکانال",
         "Microchannel bar count",
         RuleStatus.RESEARCH, _RESEARCH, "Default 3."),
)


RULE_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}


def status_counts() -> dict[str, int]:
    counts = {s.value: 0 for s in RuleStatus}
    for rule in RULES:
        counts[rule.status.value] += 1
    return counts


def rules_at(status: RuleStatus) -> tuple[Rule, ...]:
    return tuple(r for r in RULES if r.status is status)


def placement_rules_ready(catalog: dict[str, Rule] | None = None) -> bool:
    """True only when entry, stop and target rules are all SPECIFIED or better."""
    source = catalog if catalog is not None else RULE_BY_ID
    ready = {RuleStatus.SPECIFIED, RuleStatus.IMPLEMENTED, RuleStatus.TESTED, RuleStatus.VERIFIED}
    needed = ("DEF_ENTRY_PRICE", "DEF_STOP_LOSS", "DEF_TAKE_PROFIT")
    return all(source[rid].status in ready for rid in needed)

# Pro BTB — موتور مستقل تشخیص (سایه)

منبع بررسی‌شده: ویدئوی آموزشی Drtv_fx، به‌همراه مشخصات مکتوب کاربر. این زیرمجموعه به معماری موجود *اضافه* می‌شود و هیچ قابلیت قبلی را حذف یا بازنویسی نمی‌کند.

وضعیت پیش‌فرض: Research / Paper / shadow. معاملهٔ زنده انجام نمی‌دهد و Risk Brain را Override نمی‌کند. آداپتور مصرف برای اجزای موجود خاموش است مگر `MOLIDO_PRO_BTB_ENABLED` روشن شود.

نقطهٔ بازگشت قبل از این کار: تگ `checkpoint/v2-audit-20261122`.

## مراحل

1. **بررسی لگ قدرتمند:** قدرت و ساختار حرکت، علامت‌گذاری موقعیت پرریسک، توقف در شرایط نامعتبر.
2. **اعتبارسنجی کندل BO:** Gap، Follow Through، کلوز نزدیک انتهای کندل. نبود Gap یا FT ریسک را بالا می‌برد، به‌خودیِ‌خود ابطال نیست.
3. **چهار منطقهٔ سربه‌سر (مستقل و قابل‌مقایسه):** ابتدای Leg 1، ابتدای Leg 2، رأس Spike در سیکل، رأس Channel.
4. **بازگشت BTB:** ناحیه به‌صورت محدودهٔ قیمتی ذخیره می‌شود؛ انتظار برای بازگشت پس از خروج قیمت از محدوده؛ شناسایی میکروکانال و طبقه‌بندی SP / CH / TR.
5. **تأیید:** بدون تأیید وارد نمی‌شود و منتظر می‌ماند؛ علت پذیرش یا رد ثبت می‌شود.
6. **ورود BTB:** مثال صعودی و نزولی. Entry / Stop / Take Profit فقط از قوانینی با وضعیت `SPECIFIED` یا بالاتر؛ در غیر این صورت خروجی `WAIT` است. نسبت ریسک به بازده و ابطال فقط وقتی ثبت می‌شوند که قیمت‌ها مجاز باشند.

تعریف دقیق BO، Gap، FT، روش ساخت ناحیهٔ BTB، و قوانین ورود/خروج در ویدئوی بررسی‌شده به‌صورت عددی قفل نشده‌اند. آستانه‌های قابل‌تنظیم با وضعیت `RESEARCH` هستند و قانون قطعی معرفی نمی‌شوند.

## جدول وضعیت قوانین

هر قانون دقیقاً یک وضعیت دارد: `RESEARCH` / `SPECIFIED` / `IMPLEMENTED` / `TESTED` / `VERIFIED`. هیچ قانونی در این نسخه `VERIFIED` نیست. قوانین فرآیندی مشخص‌شده در مشخصات، پیاده و تست شده‌اند و وضعیت `TESTED` دارند. تعاریف و آستانه‌های نامشخص در ویدئو در `RESEARCH` می‌مانند حتی اگر پارامترشان در کد وجود داشته باشد.

| شناسه | عنوان | وضعیت | منبع |
|---|---|---|---|
| STRONG_LEG_ASSESS | بررسی لگ قدرتمند، ساختار، ریسک و توقف در شرایط نامعتبر | TESTED | مشخصات / ساختار ویدئو |
| BO_CHECK_GAP | بررسی Gap در کندل BO | TESTED | مشخصات / ساختار ویدئو |
| BO_CHECK_FT | بررسی Follow Through | TESTED | مشخصات / ساختار ویدئو |
| BO_CHECK_CLOSE_EXTREME | بررسی کلوز در انتهای کندل | TESTED | مشخصات / ساختار ویدئو |
| BO_MISSING_GAP_FT_RAISES_RISK | نبود Gap یا FT ریسک را بالا می‌برد | TESTED | مشخصات / ساختار ویدئو |
| BE_ZONE_LEG1_START | مدل مستقل سربه‌سر در ابتدای Leg 1 | TESTED | مشخصات / ساختار ویدئو |
| BE_ZONE_LEG2_START | مدل مستقل سربه‌سر در ابتدای Leg 2 | TESTED | مشخصات / ساختار ویدئو |
| BE_ZONE_SPIKE_TOP | مدل مستقل سربه‌سر در رأس اسپایک | TESTED | مشخصات / ساختار ویدئو |
| BE_ZONE_CHANNEL_TOP | مدل مستقل سربه‌سر در رأس کانال | TESTED | مشخصات / ساختار ویدئو |
| BE_ZONES_COMPARABLE | چهار منطقه باید قابل‌مقایسه باشند | TESTED | مشخصات / ساختار ویدئو |
| BTB_ZONE_IS_PRICE_RANGE | ناحیهٔ BTB به‌صورت محدودهٔ قیمتی ذخیره می‌شود | TESTED | مشخصات / ساختار ویدئو |
| RETEST_WAIT_FOR_RETURN | انتظار برای بازگشت قیمت به ناحیهٔ BTB | TESTED | مشخصات / ساختار ویدئو |
| RETEST_MICROCHANNEL | شناسایی میکروکانال | TESTED | مشخصات / ساختار ویدئو |
| RETEST_SP_CH_TR | تفکیک چرخهٔ SP / CH / TR | TESTED | مشخصات / ساختار ویدئو |
| CONFIRM_OR_WAIT | بدون تأیید وارد نشو؛ علت را ثبت کن | TESTED | مشخصات / ساختار ویدئو |
| ENTRY_BULL_AND_BEAR | پشتیبانی از مثال صعودی و نزولی | TESTED | مشخصات / ساختار ویدئو |
| ENTRY_SL_TP_ONLY_SPECIFIED | ورود و حدها فقط از قوانین SPECIFIED یا بالاتر | TESTED | مشخصات / ساختار ویدئو |
| ENTRY_LOG_RR_INVALIDATION | ثبت نسبت ریسک به بازده و شرایط ابطال | TESTED | مشخصات / ساختار ویدئو |
| NO_GUESSED_RULE_AS_FINAL | هیچ قاعدهٔ حدسی قانون قطعی نیست | TESTED | مشخصات / ساختار ویدئو |
| ADAPTER_OFF_BY_DEFAULT | آداپتور خواندنی و پیش‌فرض خاموش | TESTED | مشخصات معماری |
| ADAPTER_NO_RISK_OVERRIDE | آداپتور Risk Brain را Override نمی‌کند | TESTED | مشخصات معماری |
| DEF_BO_CANDLE | تعریف دقیق کندل BO | RESEARCH | در ویدئو قفل نشده |
| DEF_GAP | تعریف دقیق Gap | RESEARCH | در ویدئو قفل نشده |
| DEF_FOLLOW_THROUGH | تعریف دقیق Follow Through | RESEARCH | در ویدئو قفل نشده |
| DEF_BTB_ZONE_CONSTRUCTION | روش ساخت محدودهٔ BTB | RESEARCH | در ویدئو قفل نشده |
| DEF_ENTRY_PRICE | قانون دقیق قیمت ورود | RESEARCH | در ویدئو قفل نشده |
| DEF_STOP_LOSS | قانون دقیق حد ضرر | RESEARCH | در ویدئو قفل نشده |
| DEF_TAKE_PROFIT | قانون دقیق حد سود | RESEARCH | در ویدئو قفل نشده |
| DEF_INVALIDATION | شرایط دقیق ابطال معامله | RESEARCH | در ویدئو قفل نشده |
| DEF_CONFIRMATION_CHECKLIST | جزئیات تأیید ورود | RESEARCH | در ویدئو قفل نشده |
| DEF_MICROCHANNEL | تعریف دقیق میکروکانال | RESEARCH | در ویدئو قفل نشده |
| DEF_SP_CH_TR_THRESHOLDS | آستانه‌های SP / CH / TR | RESEARCH | در ویدئو قفل نشده |
| DEF_LEG2_IDENTIFICATION | روش شناسایی Leg 2 | RESEARCH | در ویدئو قفل نشده |
| PARAM_ATR_PERIOD | دورهٔ ATR | RESEARCH | پیش‌فرض ۱۴ |
| PARAM_SWING_K | عرض تأیید سوئینگ | RESEARCH | پیش‌فرض ۲ |
| PARAM_MIN_LEG_ATR | حداقل جابه‌جایی لگ نسبت به ATR | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_MIN_LEG_BARS | حداقل تعداد کندل لگ | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_MIN_BODY_RATIO | حداقل نسبت بدنه به دامنه | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_MAX_OVERLAP | حداکثر همپوشانی مجاز لگ | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_EXTENDED_ATR | آستانهٔ لگ بیش‌ازحد کشیده | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_MAX_SINGLE_BAR_SHARE | سهم یک کندل از جابه‌جایی | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_CLOSE_EXTREME_FRAC | سهم انتهایی کندل برای کلوز | RESEARCH | پیش‌فرض ۰٫۲۵ |
| PARAM_MIN_BARS_AFTER_BO | حداقل فاصله تا بررسی بازگشت | RESEARCH | پارامتر قابل‌تنظیم |
| PARAM_MICROCHANNEL_BARS | تعداد کندل میکروکانال | RESEARCH | پیش‌فرض ۳ |

شمارش را از `status_counts()` در `backend/app/agents/pro_btb/rules.py` بخوانید؛ این جدول باید با کاتالوگ یکی باشد.

## قالب ردپای تصمیم (Decision Trace)

خروجی `ProBtbEngine.run(...).as_dict()` یک شیء JSON-پذیر با این شکل است:

```json
{
  "symbol": "XAUUSD",
  "timeframe": "H1",
  "as_of": "2026-11-04T00:00:00+00:00",
  "direction": "bull",
  "decision": "WAIT",
  "stages": [
    {
      "stage": "strong_leg",
      "valid": true,
      "decision": "CONTINUE",
      "reasons": ["..."],
      "details": {}
    }
  ],
  "btb_zone": {
    "low": 2020.0,
    "high": 2034.0,
    "rule_id": "BTB_ZONE_IS_PRICE_RANGE",
    "rule_status": "TESTED"
  },
  "break_even_zones": [
    {
      "kind": "leg1_start",
      "present": true,
      "price": 1980.0,
      "bar_index": 22,
      "reasons": ["..."],
      "rule_id": "BE_ZONE_LEG1_START",
      "rule_status": "TESTED"
    }
  ],
  "zone_comparisons": [{"left": "leg1_start", "right": "spike_top", "delta": 54.0}],
  "confirmation_accepted": true,
  "confirmation_reason": "accepted: ...",
  "entry_action": "WAIT",
  "entry_reason": "WAIT: exact entry, stop-loss and take-profit rules are not SPECIFIED ...",
  "risk_reward": null,
  "invalidation": null,
  "risk_flags": ["HIGH_RISK_LEG"],
  "rule_statuses": {"DEF_ENTRY_PRICE": "RESEARCH"}
}
```

مراحل به‌ترتیب: `strong_leg`، `bo_candle`، `break_even`، `btb_retest`، `confirmation`، `btb_entry`. اگر لگ نامعتبر باشد، `decision` برابر `STOP` است و ورود انجام نمی‌شود.

## اتصال خواندنی به اجزای موجود

تابع `read_only_input(consumer, bars, as_of=...)` برای این مصرف‌کننده‌ها در دسترس است: Rocket Trade Hunter، Hybrid AI Brain، Market Key Levels، SP2L، Spike & Imbalance، Multi-Timeframe، AI Validation & Scoring، Adaptive Risk. خروجی یک ورودی اضافی است، نه دستور اجرا. پیش‌فرض خاموش است و فیلد `may_override_risk_brain` همیشه `false` می‌ماند. به دوندهٔ ۵۱ ایجنت وصل نشده تا رفتار قبلی تغییر نکند.

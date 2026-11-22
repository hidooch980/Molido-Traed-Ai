# موتورهای V2 — فاز ۳ و ۵ (سطوح کلیدی، SP2L، اسپایک و ایمبالانس)

افزایشی است؛ هیچ ماژول قبلی بازنویسی نشده. پیش‌فرض خاموش است (`MOLIDO_V2_ENGINES_ENABLED`). Risk Brain را Override نمی‌کند. Entry/SL/TP در SP2L مثل Pro BTB روی `WAIT` می‌ماند مگر قوانین قیمت `SPECIFIED` شوند.

نقطهٔ بازگشت: `checkpoint/v2-audit-20261122` و شاخهٔ `agents/stage-22-pro-btb`.

## منابع بررسی‌شده (فاز ۳)

### Previous New York Close و Daily H/L
کلوز متعارف روز معاملاتی فارکس ساعت ۱۷:۰۰ به وقت `America/New_York` است (با DST). آخر هفته: آخرین کلوز جمعه ۱۷:۰۰، شروع هفته یکشنبه ۱۷:۰۰.
- [Daily Cut-Off and the 5 pm New York Rollover](https://autofxrebate.com/en/learn/glossary/daily-cut-off)
- اجماع آموزشی BabyPips دربارهٔ پایان عملی روز در ساعت ۵ بعدازظهر نیویورک

### Round numbers
تیک‌سایز نماد رعایت می‌شود؛ سطوح major و minor جدا طبقه‌بندی می‌شوند. اندازهٔ پیش‌فرض گام‌ها `RESEARCH` است و باید در صورت امکان توسط فراخوان‌کننده داده شود.

### Weekly MAP
تعریف رسمی و یکتایی پیدا نشد. اسکریپت‌های TradingView با نام «Weekly Map» معمولاً سقف/کف هفته را به درصد تقسیم می‌کنند یا OHLC هفته را می‌کشند؛ این یک فرمول استاندارد نیست. صفحات CME دربارهٔ میانگین متحرک یا آپشن هفتگی هستند، نه MAP. **با Pivot یا Midpoint جایگزین نشده.** وضعیت: `RESEARCH` stub.

### Valid Break-Even
به‌عنوان یک سطح کلیدی مستقل با فرمول منتشرشده پیدا نشد. با Break-even حسابداری/معامله فرق دارد. مناطق سربه‌سر Pro BTB موتور جداگانه‌اند و اینجا به‌جای این سطح استفاده نشده‌اند. وضعیت: `RESEARCH` stub.

### SP2L (Spike–2Leg)
منبع اصلی: [poursamadi.com/sp2l-strategy](https://poursamadi.com/sp2l-strategy/) (محمدعلی پورصمدی).
- اسپایک معتبر نیازمند گپ قیمتی (P-Gap) است.
- لگ دوم: در صعود، کندل اصلاحی کف کندل قبلی را می‌زند؛ در نزول، سقف را.
- صفحهٔ رسمی SL را پشت شروع اسپایک و TP را ۱:۱ می‌گوید، اما پیاده‌سازی‌های TradingFinder در جزئیات ورود اختلاف دارند. به همین دلیل قیمت Entry/SL/TP صادر نمی‌شود (`WAIT`).

منبع فرعی (فقط توصیف HL/LH، نه قانون قطعی ورود):
- [TradingFinder SP2L on TradingView](https://www.tradingview.com/script/Qiv9aTi0-SP2L-Pour-Samadi-Indicator-TradingFinder-Spike-2-Legs-PA/)

### Spike & Imbalance / FVG
تشخیص FVG از `app.agents.analyzers.smc.fair_value_gaps` است؛ منطق کپی نشده. پرشدن گپ با همان قاعدهٔ SM04 تست توافق دارد. احتمال ادامه/برگشت حدس زده نشده است.

## آداپتور امتیازدهی
`read_only_v2_input` خروجی هر چهار موتور (Key Levels، SP2L، Spike & Imbalance، Pro BTB) را می‌گیرد. خانواده‌های مشترک (spike، FVG، retest، breakout) فقط یک‌بار شمرده می‌شوند و منبع‌ها فهرست می‌شوند. وزن برابر فقط placeholder با وضعیت `RESEARCH` است.

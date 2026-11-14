# رجیستری ۵۱ ایجنت (مراحل ۱ تا ۱۳)

*ساخته‌شده روی شاخه `agents/stage-1-registry` از `main` در `ae99797` — ۲۳ آبان ۱۴۰۵ (14 Nov 2026)*

## این مرحله چه هست و چه نیست

مرحله ۱ فقط **توصیف** است: هر ۵۱ نقش درخواستی با شناسه، نام فارسی و انگلیسی، گروه،
وظایف، سطح دسترسی، محدودیت‌ها، رویدادهای فعال‌سازی، ماژول‌های موجودی که امروز آن نقش
را (کامل یا بخشی) انجام می‌دهند، و **وضعیت صادقانه** هر نقش ثبت شده است.

- هیچ نقشی به‌عنوان فرایند جداگانه اجرا نمی‌شود.
- هیچ نقشی مدل زبانی (Grok یا دیگری) صدا نمی‌زند.
- هیچ رفتاری در تصمیم، ریسک یا اجرا تغییر نکرده است. هیچ فایلی در `app/execution`،
  `app/workers`، `app/pipeline` یا `app/brain` این بسته را import نمی‌کند و تست
  import-graph این را تضمین می‌کند.
- حالت این مرحله **فقط Paper** است. هیچ سفارش LIVE مجاز نیست.

## فایل‌ها

| مسیر | کار |
|---|---|
| `backend/app/agents/model.py` | نوع‌ها: گروه، سطح دسترسی L1–L4، وضعیت، `AgentRole` |
| `backend/app/agents/roles.py` | داده ۵۱ نقش |
| `backend/app/agents/registry.py` | جست‌وجو و `snapshot()` |
| `backend/app/agents/messages.py` | پروتکل پیام استاندارد (`AgentMessage`، pydantic) |
| `backend/app/api/v1/agents.py` | `GET /api/v1/agents/registry` — فقط‌خواندنی، با مجوز READ |
| `backend/tests/test_agents_registry.py` | ۲۸ تست |

## سطوح دسترسی

| سطح | نام | معنا |
|---|---|---|
| L1 | READ | خواندن داده مشترک و سوابق خود |
| L2 | ANALYZE | تحلیل، امتیاز، سناریو |
| L3 | PROPOSE | پیشنهاد استراتژی، معامله یا تغییر — بدون اجرا |
| L4 | CONTROL | رد پیشنهاد مغایر با قوانین، توقف اضطراری در محدوده مجاز |
| L5 | HUMAN | فقط انسان: تغییر سیاست ریسک، فعال‌کردن LIVE، تغییر دسترسی امنیتی، انتقال وجه |

L5 در نوع `PermissionLevel` **وجود ندارد**؛ ساختن نقشی با `may_override_risk=True` یا
`can_submit_orders=True` خطا می‌دهد. سطح L4 فقط به گروه‌های ریسک و اجرا داده شده و این
هم تست دارد. نقش‌های اجرا (EX) خودشان سفارش صادر نمی‌کنند؛ کد موجود فقط بعد از Risk Brain،
Kill Switch و gate نوع حساب ارسال می‌کند.

محدودیت‌های مشترک همه نقش‌ها: دورنزدن Risk Brain، نداشتن سفارش LIVE، دسترسی‌نداشتن به
رمز و کلید، و اعلام WAIT یا ABSTAIN در نبود داده معتبر.

## پیام استاندارد

`AgentMessage`: `message_id` (UUID یکتا)، `agent_id` (باید در رجیستری باشد)، `timestamp`
(باید منطقه زمانی داشته باشد؛ به UTC تبدیل می‌شود)، `market` (forex/gold/crypto)، `symbol`،
`timeframe` (از enum موجود)، `analysis`، `evidence`، `confidence` (۰ تا ۱)، `risk_assessment`،
`recommendation` (BUY/SELL/WAIT/ABSTAIN/BLOCK)، `data_source`، `model_version`، `in_reply_to`.

قواعد: BUY یا SELL بدون شاهد رد می‌شود؛ BLOCK فقط از نقش L4؛ فیلد اضافه (مثلاً کلید) رد
می‌شود؛ `dedup_key` برای حذف پیام تکراری قطعی است.

## وضعیت ۵۱ نقش

خلاصه (پس از مرحله ۱۵): **50 IMPLEMENTED**، **1 PARTIAL** (EX02: دادهٔ قیمت درخواستی در برابر قیمت پر شده برای آمار لغزش وجود ندارد)، **0 NOT_IMPLEMENTED**. پس از مرحله ۱۲: 42 / 9 / 0. در مرحله ۱: 14 / 21 / 16.

همه نقش‌های موجود قانون‌محور و قطعی‌اند. «IMPLEMENTED» یعنی کد موجود کار نقش را انجام می‌دهد، نه اینکه یک ایجنت هوش مصنوعی مستقل با این شناسه اجرا می‌شود.

| شناسه | نام | سطح | وضعیت | ماژول‌های موجود |
|---|---|---|---|---|
| SC01 | فرمانده اسکالپینگ | L3 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SC02 | تحلیلگر ریزساختار بازار | L2 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py`<br>`backend/app/services/agent_run.py` |
| SC03 | شکارچی مومنتوم | L2 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SC04 | شکارچی نقدینگی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SC05 | هوش تحلیل اسپرد | L2 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py`<br>`backend/app/workers/autotrade.py` |
| SC06 | شکارچی نوسانات | L2 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SC07 | هوش ورود دقیق | L3 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SC08 | هوش خروج سریع | L3 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py`<br>`backend/app/learning/exits.py`<br>`backend/app/workers/trailing.py` |
| SC09 | مدیر پوزیشن اسکالپینگ | L3 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py`<br>`backend/app/workers/trailing.py` |
| SC10 | تحلیلگر عملکرد اسکالپینگ | L2 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SM01 | تحلیلگر پول هوشمند | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM02 | شکارچی جاروکردن نقدینگی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM03 | شکارچی بلوک سفارش | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM04 | تحلیلگر Fair Value Gap | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM05 | تشخیص‌دهنده BOS و CHoCH | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM06 | تحلیلگر ساختار بازار | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM07 | تحلیلگر نقدینگی سمت خرید و فروش | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM08 | تحلیلگر Premium و Discount | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM09 | تحلیلگر سشن‌های معاملاتی ICT | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py` |
| SM10 | تحلیلگر ردپای مؤسسات مالی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/smc.py`<br>`backend/app/services/positioning.py`<br>`backend/app/services/agent_run.py` |
| TA01 | تحلیلگر تکنیکال | L2 | IMPLEMENTED | `backend/app/features/indicators.py`<br>`backend/app/services/feature_store.py`<br>`backend/app/brain/council.py` |
| TA02 | تحلیلگر چندتایم‌فریمی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/extra.py`<br>`backend/app/core/timeframes.py`<br>`backend/app/workers/autotrade.py` |
| TA03 | تحلیلگر پرایس اکشن | L2 | IMPLEMENTED | `backend/app/agents/analyzers/extra.py`<br>`backend/app/brain/strategy.py` |
| TA04 | تشخیص‌دهنده روند | L2 | IMPLEMENTED | `backend/app/brain/council.py`<br>`backend/app/learning/rules.py` |
| TA05 | شکارچی نقاط بازگشت | L2 | IMPLEMENTED | `backend/app/learning/rules.py` |
| TA06 | متخصص شکست قیمت | L2 | IMPLEMENTED | `backend/app/learning/rules.py`<br>`backend/app/brain/strategy.py` |
| AI01 | هوش تشخیص وضعیت بازار | L2 | IMPLEMENTED | `backend/app/services/regime.py`<br>`backend/app/learning/regimes.py`<br>`backend/app/brain/council.py` |
| AI02 | هوش پیش‌بینی بازار | L2 | IMPLEMENTED | `backend/app/agents/analyzers/ai02.py`<br>`backend/app/agents/analyzers/ml.py`<br>`backend/app/brain/calibration.py` |
| AI03 | هوش یادگیری تطبیقی | L3 | IMPLEMENTED | `backend/app/agents/council/versions.py`<br>`backend/app/services/agent_council.py`<br>`backend/app/learning/brain_selection.py`<br>`backend/app/learning/drift.py`<br>`backend/app/learning/registry.py`<br>`backend/app/learning/lab.py` |
| AI04 | هوش تحلیل خصمانه | L2 | IMPLEMENTED | `backend/app/brain/meta.py` |
| RK01 | نگهبان اصلی ریسک | L4 | IMPLEMENTED | `backend/app/brain/risk.py`<br>`backend/app/execution/safety.py`<br>`backend/app/execution/killswitch_store.py`<br>`backend/app/core/safe_mode.py` |
| RK02 | هوش حد ضرر و حد سود پویا | L3 | IMPLEMENTED | `backend/app/agents/analyzers/extra.py`<br>`backend/app/learning/exits.py`<br>`backend/app/workers/trailing.py` |
| RK03 | هوش محاسبه حجم معامله | L4 | IMPLEMENTED | `backend/app/services/calculators.py`<br>`backend/app/workers/autotrade.py` |
| RK04 | هوش مدیریت ریسک پرتفوی | L4 | IMPLEMENTED | `backend/app/brain/portfolio.py`<br>`backend/app/workers/autotrade.py` |
| RK05 | ناظر قوانین FTMO | L4 | IMPLEMENTED | `backend/app/brain/challenge.py`<br>`backend/app/brain/rulebooks.py`<br>`backend/app/services/challenge_accounts.py` |
| EX01 | ایجنت اجرای معاملات متاتریدر | L4 | IMPLEMENTED | `backend/app/execution/metatrader_broker.py`<br>`backend/app/execution/paper_broker.py`<br>`infra/mql5/MolidoBridge.mq5` |
| EX02 | هوش کنترل لغزش قیمت | L4 | PARTIAL | `backend/app/execution/broker.py`<br>`infra/mql5/MolidoBridge.mq5` |
| EX03 | ناظر هوشمند معاملات | L4 | IMPLEMENTED | `backend/app/execution/engine.py`<br>`backend/app/api/v1/execution.py`<br>`backend/app/workers/trailing.py` |
| EX04 | مدیر دفتر ثبت معاملات | L1 | IMPLEMENTED | `backend/app/brain/journal.py`<br>`backend/app/services/journal_log.py`<br>`backend/app/services/audit.py` |
| EX05 | فرمانده کل معاملات | L4 | IMPLEMENTED | `backend/app/execution/autopilot.py`<br>`backend/app/workers/autotrade.py`<br>`backend/app/execution/modes.py` |
| BRAIN-01 | تحلیلگر مغزها و هوش جمعی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/brain01.py`<br>`backend/app/agents/council/versions.py`<br>`backend/app/agents/analyzers/runner.py`<br>`backend/app/agents/gateway/ledger.py` |
| RT01 | شکارچی انفجار قیمت | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT02 | تحلیلگر جهش مومنتوم | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT03 | شکارچی شکست انفجاری | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT04 | تحلیلگر فشردگی قیمت | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT05 | شکارچی حجم غیرعادی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT06 | تحلیلگر اخبار محرک | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py`<br>`backend/app/services/agent_events.py`<br>`backend/app/services/calendar.py` |
| RT07 | شکارچی نقدینگی انفجاری | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT08 | پیش‌بینی‌کننده حرکت شارپی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT09 | مدیر خروج موشکی | L3 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT10 | ارزیاب فرصت‌های موشکی | L3 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |

## Grok Gateway (مرحله ۳)

مسیر: `backend/app/agents/gateway/`. فقط مشورتی؛ هیچ مسیر تصمیم، ریسک یا اجرا آن را import نمی‌کند.

- **Endpoint و مدل‌ها** از مستندات رسمی xAI در ۲۳ آبان ۱۴۰۵ بررسی شد:
  [docs.x.ai/docs/models](https://docs.x.ai/docs/models) و
  [docs.x.ai/docs/api-reference](https://docs.x.ai/docs/api-reference) —
  `POST https://api.x.ai/v1/responses`، احراز با `Authorization: Bearer`، فیلدهای
  `usage.input_tokens`، `usage.input_tokens_details.cached_tokens`، `usage.output_tokens`.
  پیش‌فرض‌ها: سبک و استاندارد `grok-4.3`، عمیق `grok-4.7` (با env قابل تغییر:
  `MOLIDO_XAI_MODEL_LIGHT/STANDARD/DEEP`). درخواست‌ها با `store: false` ارسال می‌شوند.
- **کلید** فقط از `XAI_API_KEY` در لحظهٔ درخواست خوانده می‌شود و هیچ‌جا ذخیره یا نمایش داده
  نمی‌شود. بدون کلید: gateway غیرفعال ← همهٔ ایجنت‌ها ABSTAIN ← تصمیم WAIT.
- **قیمت در کد نیست.** از `MOLIDO_XAI_PRICING_JSON` خوانده می‌شود، مثلاً (قیمت‌های صفحهٔ
  مدل‌ها در همان تاریخ، دلار به ازای یک میلیون توکن — پیش از استفاده دوباره بررسی شود):
  `{"grok-4.3": {"input": 1.25, "cached_input": 0.2, "output": 2.5, "long_context_threshold": 200000, "long_input": 2.5, "long_cached_input": 0.4, "long_output": 5.0}, "grok-4.7": {"input": 2.0, "cached_input": 0.5, "output": 6.0, "long_context_threshold": 200000, "long_input": 4.0, "long_cached_input": 1.0, "long_output": 12.0}}`.
  بدون قیمت، هزینه «نامعلوم» (null) ثبت می‌شود و فقط سقف توکن اعمال می‌شود.
- **کنترل‌ها:** صف محدود با اولویت (CRITICAL/HIGH/NORMAL/LOW)، سقف هم‌زمانی، حذف درخواست
  تکراری هم‌زمان، Cache با TTL و LRU، سقف توکن ورودی و خروجی، Timeout، Retry محدود با
  Exponential Backoff فقط برای 408/409/429/5xx، Circuit Breaker با یک probe.
- **بودجه:** NORMAL؛ ECONOMY از ۷۰٪ سقف (فقط CRITICAL و HIGH، مدل عمیق به استاندارد)؛
  EMERGENCY در ۱۰۰٪ (هیچ فراخوانی). ریسک، ایمنی و ژورنال اصلاً به gateway وابسته نیستند.
- **دفتر هزینه:** جدول `agent_llm_usage` (migration `0030_agent_llm_usage`)، یک ردیف برای هر
  نتیجه؛ Cache hit با صفر توکن ثبت می‌شود.
- **API فقط‌خواندنی:** `GET /api/v1/agents/gateway` و `GET /api/v1/agents/gateway/usage?days=N`.
- خروجی مدل فقط JSON مشخص پذیرفته می‌شود؛ BLOCK از مدل به WAIT تبدیل می‌شود؛ BUY/SELL بدون
  شاهد به WAIT؛ خروجی نامعتبر ABSTAIN. اطمینان اعلام‌شدهٔ مدل ثبت می‌شود ولی در وزن‌دهی استفاده نمی‌شود.

## شورای v2 (مرحله ۴) — فقط حالت سایه

مسیر: `backend/app/agents/council/`. شورای موجود (`app/brain/council.py`) دست‌نخورده است.

- اعضای جدید، همه abstain-first: macro (اختلاف نرخ بهره)، news (نزدیکی رویداد پراهمیت؛ بدون جهت،
  فقط اعتراض)، sentiment (ازدحام موقعیت COT، خلاف جهت)، quant (z-score، بازگشت به میانگین)،
  execution (نسبت اسپرد به ATR؛ بدون جهت، فقط اعتراض) و adversarial (حمله به اکثریت با شواهد اقلیت).
- **اعتبار** فقط از نتایج خارج از نمونه، با shrinkage (یک برد تصادفی تقریباً هیچ وزنی نمی‌دهد).
  اطمینان اعلام‌شدهٔ اعضا در وزن‌دهی **استفاده نمی‌شود** (تست دارد).
- **تعارض:** اعضای قوی در دو جهت مخالف، یا وزن مخالف ≥ ۳۴٪ ← WAIT. کمبود حد نصاب ← WAIT.
  اعتراض روی موردی که قوی نیست ← WAIT.
- **وزن‌ها نسخه‌دار:** هر تغییر نسخهٔ جدید با دلیل و نویسنده؛ Rollback هم نسخهٔ جدید است؛ ذخیرهٔ JSON اتمیک.
- **flag** `MOLIDO_AGENT_COUNCIL_LIVE` پیش‌فرض خاموش است و حتی روشن هم به جایی وصل نیست؛ وصل‌کردن
  به مسیر تصمیم تغییر جداگانه با تأیید مالک است. خروجی فقط لاگ سایه است و Risk Brain مرجع نهایی می‌ماند.

## حافظه (مرحله ۵)

چهار جدول جدید (migration `0031_agent_memory`):

- `agent_memory`: حافظهٔ هر ایجنت با نوع (market، agent، strategy، trade، failure، pattern، news،
  regime، risk، rocket، council، model_performance)، نماد، خلاصه، محتوا و `source_ref` برای ردیابی.
- `agent_council_decisions`: هر رأی سایهٔ شورا با نظر همهٔ اعضا و نسخهٔ وزن‌ها؛ نتیجه (R) فقط یک بار
  ثبت می‌شود و بازنویسی نمی‌شود. اعتبار اعضا از همین نتایج ساخته می‌شود (`credibility_from_decisions`).
- `agent_failures`: حافظهٔ خطا با دسته‌بندی ثابت (سیگنال اشتباه، شکست جعلی، ورود دیر، خروج زود، تغییر رژیم،
  خطای داده، خطای استدلال، اختلاف شورا، اجرا، سایر).
- `agent_learning_records`: پیشنهاد یادگیری ← VALIDATED (فقط با شاهد خارج از نمونه) ← APPROVED/REJECTED
  فقط با نام یک انسان. **تأیید هیچ چیزی را مستقر نمی‌کند** و هیچ کدی در برنامه تأیید خودکار انجام نمی‌دهد (تست دارد).

API فقط‌خواندنی: `/api/v1/agents/memory`، `/agents/council/decisions`، `/agents/failures`، `/agents/learning`.

## تحلیلگرها (مرحله ۶) — قطعی، سایه، بدون اجرا

- `analyzers/bars.py`: `make_context` فقط کندل‌هایی را می‌بیند که تا `as_of` بسته شده‌اند (`open_time + delta <= as_of`). تست می‌کند که افزودن کندل‌های آینده هیچ خروجی‌ای را تغییر نمی‌دهد. سوئینگ‌ها فقط پس از ۲ کندل تأیید شمرده می‌شوند.
- `scalping.py` (SC01–SC10)، `smc.py` (SM01–SM10)، `rocket.py` (RT01–RT10)، `ai02.py`، `brain01.py`، `runner.run_all`.
- هر تحلیلگر یک `AgentMessage` می‌دهد. وقتی داده کافی نیست ABSTAIN می‌دهد. هیچ‌کدام BLOCK نمی‌دهند، چون فقط Risk Brain حق BLOCK دارد.
- RT10 یک `RocketSignal` کامل با این فیلدها می‌سازد: رتبه R1–R5، ورود، SL، TP، R:R خالص، اسپرد، لغزش، ATR، شواهد موافق و مخالف، و ابطال. وضعیت آن همیشه `PROPOSED` و `risk_approval_status=NOT_SUBMITTED` است. این امتیازها جریمه می‌گیرند: شکست جعلی، دنبال‌کردن قیمت بیش از ۳ ATR، پنجره خبر، و R:R کمتر از 1.2. اگر کندلی هم به استاپ و هم به تارگت برسد، `evaluate_outcome` آن را استاپ حساب می‌کند.
- AI02 فقط یک خط پایهٔ آماری است، نه یادگیری ماشین. امتیاز Brier آن درون‌نمونه‌ای است و با همین برچسب گزارش می‌شود.
- SMC روی کندل بروکر کار می‌کند و دادهٔ سفارش مؤسسات نیست. SM10 فقط دادهٔ هفتگی و با تأخیر CFTC را به‌عنوان ورودی می‌پذیرد.
- هیچ‌چیز این بسته در مسیر اجرا/پایپلاین import نمی‌شود (تست گراف import). لبهٔ سودده هیچ تحلیلگری سنجیده نشده است. walk-forward و ثبت سیگنال‌ها در حافظه مرحلهٔ بعد است.

## تایم‌فریم‌ها (مرحله ۷)

- `Timeframe` حالا این دوره‌ها را هم دارد: M2، M3، M4، M6، M10، M12، M20، H2، H6، H8 و H12. ستون‌های DB از نوع `String(8)` هستند، پس migration لازم نبود.
- **Native** یعنی همان هفت دوره‌ای که EA واقعاً منتشر می‌کند (`TimeframeName`): M1، M5، M15، M30، H1، H4 و D1. بقیه **Derived** هستند و از بزرگ‌ترین دورهٔ native که بر آن بخش‌پذیرند ساخته می‌شوند. فهرست کامل از `GET /api/v1/agents/timeframes` می‌آید.
- `resample` فقط سطل‌هایی را برمی‌گرداند که تا `as_of` بسته شده‌اند، و فقط کندل‌های منبعِ بسته را می‌خواند. سطلی که کندل کم دارد با `complete=False` علامت می‌خورد. تراز ساعت سرور بروکر با `shift_hours` تنظیم می‌شود. W1 و MN1 بازنمونه نمی‌شوند.
- هنوز هیچ worker یا collector این دوره‌های جدید را جمع‌آوری یا ذخیره نمی‌کند. فعلاً فقط برچسب و ابزار ساخت آن‌ها آماده است.

## داشبورد (مرحله ۸)

- `/agents`: رجیستری زنده را از `GET /api/v1/agents/registry` می‌خواند و نقش‌ها را بر اساس گروه، وضعیت و ماژول نشان می‌دهد.
- `/rocket`: داده‌اش از `GET /api/v1/agents/rocket/scan?timeframe=` می‌آید. این endpoint روی کندل‌های ذخیره‌شده با `get_bars` و در لحظهٔ اکنون RT10 را اجرا می‌کند. اگر چند provider داده داشته باشند، آنی که بیشترین کندل را دارد انتخاب و نامش در خروجی ذکر می‌شود. سیگنال‌ها فقط PROPOSED هستند و جایی ذخیره یا ارسال نمی‌شوند. وقتی داده نیست، حالت خالی نمایش داده می‌شود.
- `/grok-cost`: از `GET /api/v1/agents/gateway` و `/gateway/usage` (امروز و ۷ روز اخیر) می‌خواند. بدون کلید، وضعیت «خاموش» نمایش داده می‌شود. هزینه‌ای که قیمتش تنظیم نشده «—» نشان داده می‌شود، نه صفر.
- هیچ صفحه‌ای داده ساختگی ندارد. قرارداد فیلدها در `test_frontend_contract.py` چک می‌شود.

## Risk Brain ایجنت‌ها (مرحله ۹) — فقط سایه

- `backend/app/agents/risk_gate.py` قطعی است و یکی از سه حکم APPROVE، REDUCE یا BLOCK را می‌دهد. از سیگنال فقط عددها را می‌خواند. هیچ فیلدی که ایجنت بفرستد (verdict، override، confidence یا risk_approval_status) روی حکم اثر ندارد.
- اگر هرکدام از این‌ها نباشد، حکم BLOCK است: equity، P&L روزانه، پوزیشن‌های باز، تازه‌بودن داده، ورود، SL، TP یا جهت. مقدار NaN هم «نبودن داده» حساب می‌شود.
- **BLOCK** در این حالت‌ها: kill switch روشن، SL یا TP در سمت اشتباه، R:R خالص کمتر از 1.2، اسپرد بیش از ۲۵٪ ATR، رسیدن به سقف ضرر روزانه، پوزیشن تکراری روی همان نماد، پرشدن سقف پوزیشن‌ها، رتبه کمتر از R3.
- **REDUCE** در این حالت‌ها: رتبه R3، گذشتن ضرر روزانه از نیمهٔ سقف، خبر مهم نزدیک.
- خروجی شورا ورود، SL و TP ندارد، پس هیچ‌وقت به‌تنهایی تأیید نمی‌شود.
- این حکم به RT10 در `/agents/rocket/scan` و به رکورد سایهٔ شورا وصل است. چون در این مرحله وضعیت حساب هنوز وصل نیست، حکم فعلاً همیشه BLOCK است. `app/brain/risk.py` همچنان مرجع نهایی مسیر اجرای موجود است.

## MT5 فقط‌خواندنی و Paper (مرحله ۱۰)

- **`backend/app/services/agent_account.py`:** وضعیت حساب را از bridge فایلی موجود فقط می‌خواند: equity، P&L روزانه (معاملات بسته‌شدهٔ امروز به‌اضافهٔ سود و زیان شناور) و نمادهای باز. چیزی نمی‌نویسد و دستوری نمی‌فرستد. اگر زمان یک deal خوانا نباشد، P&L روزانه «نامعلوم» می‌شود و حکم ریسک BLOCK است.
- **`GET /agents/account`:** همان دیدی را برمی‌گرداند که Risk Gate از حساب دارد. `/agents/rocket/scan` حالا با همین context ارزیابی می‌کند.
- **`backend/app/agents/paper.py` و `backend/app/services/agent_paper.py`:** معامله Paper فقط با حکم APPROVE یا REDUCE باز می‌شود و در حافظه (kind=trade، mode=paper) ثبت می‌شود. اگر کندلی هم به استاپ و هم به تارگت برسد، استاپ حساب می‌شود. سیگنال تکراری دوباره باز نمی‌شود (`trade_id` قطعی).
  - این مسیر به‌طور پیش‌فرض خاموش است. با `MOLIDO_AGENT_PAPER=1` و دستور `python -m app.services.agent_paper` اجرا می‌شود. زمان‌بندی خودکار ندارد.
  - نتیجه‌ها از `GET /agents/paper` خوانده می‌شوند.
- **EA (نسخه 1.10):** حالا `AllowTrading=false` پیش‌فرض است. روی حساب Real، EA اجرا نمی‌شود (`INIT_FAILED`) مگر اینکه `AllowRealAccount=true` شود. با `ExpectedLogin` می‌شود EA را به یک login مشخص قفل کرد.

## جمع‌آوری تایم‌فریم‌های مشتق و Walk-forward (مرحله ۱۱)

- **`workers/live_bars.py`:** دوره‌های M2، M3، M4، M6، M10، M12، M20، H2، H6، H8 و H12 را با همان `fold` موجود از دوره‌های native می‌سازد. هر کندل همهٔ اجزایش را لازم دارد. خروجی زیر provider `metatrader-derived` ذخیره می‌شود. این کار فقط با `MOLIDO_DERIVE_EXTRA_TIMEFRAMES=1` روشن می‌شود و پیش‌فرض خاموش است.
- **سیگنال‌های RT10:** هر سیگنال یک‌بار در حافظه ثبت می‌شود (kind=rocket، event=signal). سیگنال روی کندل‌های بستهٔ بعدی، فقط یک‌بار، حل می‌شود (event=outcome). نتیجه از `GET /agents/rocket/forward` خوانده می‌شود. چرخهٔ Paper این دو کار را خودش انجام می‌دهد.
- **`GET /agents/rocket/walkforward?symbol=&timeframe=&folds=`:** RT10 را روی تاریخچهٔ ذخیره‌شده قدم‌به‌قدم و point-in-time اجرا می‌کند. هم‌زمان فقط یک پوزیشن باز است. نتیجه به تفکیک fold زمانی و رتبه گزارش می‌شود. چون پارامتری fit نمی‌شود، همه‌چیز out-of-sample است. هزینه‌ها (اسپرد و لغزش) فقط وقتی حساب می‌شوند که داده‌شان داده شود.

## تقویم RT06 و لیست نماد پویا (مرحله ۱۲)

- **`services/agent_events.py`:** رویدادهای High را از همان فید رایگان و بدون کلید `services/calendar.py` (ForexFactory XML) می‌خواند. با `MOLIDO_AGENT_CALENDAR=1` روشن می‌شود و پیش‌فرض خاموش است.
  - اگر فید خاموش باشد، خطا بدهد یا ساعتش جابه‌جا به نظر برسد، نتیجه «نامعلوم» است و RT06 ABSTAIN می‌دهد. هیچ‌وقت «خبری نیست» گزارش نمی‌شود.
  - برای هر نماد، از ۶۰ دقیقه قبل تا ۳۰ دقیقه بعد از خبر، Risk Gate حکم را REDUCE می‌کند. این بازه برای طلا رویدادهای USD را هم شامل می‌شود.
  - خروجی از `GET /agents/calendar` خوانده می‌شود.
- **`services/agent_symbols.py`:** اگر ترمینالی مشخصات قرارداد منتشر کند، فقط نمادهایی اسکن می‌شوند که بروکر واقعاً دارد. پسوندهای بروکر مثل `EURUSD.` و `EURUSDm` هم تطبیق داده می‌شوند. اگر هیچ ترمینالی مشخصات منتشر نکند، همهٔ نمادهای فعال اسکن می‌شوند و منبع ذکر می‌شود. فهرست از `GET /agents/symbols` می‌آید و اسکن و چرخهٔ Paper از همین فهرست استفاده می‌کنند.

## پایش FTMO (مرحله ۱۳)

- صفحهٔ `/ftmo` داده‌اش را از `GET /api/v1/agents/ftmo-monitor` می‌گیرد. هر حساب چالش ثبت‌شده با rulebook خودش (`brain/rulebooks.py`) و `brain/challenge.check` در برابر دادهٔ زندهٔ bridge بررسی می‌شود.
- **جفت‌شدن حساب‌ها:** حساب چالش با حسابی از bridge جفت می‌شود که کلیدش با برچسب حساب چالش یکی باشد. اگر فقط یک حساب از هر طرف وجود داشته باشد، همان دو با هم جفت می‌شوند.
- **وضعیت‌های «نامعلوم»:** نبودن داده زنده، نبودن rulebook، نامعلوم‌بودن P&L روزانه و جفت‌نشدن حساب هرکدام جداگانه گزارش می‌شوند و هیچ‌کدام صفر حساب نمی‌شود.
- **محدودیت:** bridge تاریخچهٔ equity منتشر نمی‌کند، پس peak برابر max(موجودی اولیه، equity فعلی) فرض می‌شود.
- این صفحه فقط پایش است و هیچ معامله‌ای را باز، بسته یا مسدود نمی‌کند.

## EA کم‌حجم با تنظیمات از راه دور (مرحله ۱۴)

- **EA نسخه 1.20:** فهرست نمادها، فاصلهٔ انتشار و تعداد کندل‌ها را از `GET /api/v1/bridge/config` می‌گیرد. این endpoint با دسترسی BROKER و فقط خواندنی است (`services/ea_config.py`).
  - قفل‌های AllowTrading، AllowRealAccount و ExpectedLogin فقط input هستند و EA آن‌ها را از سرور نمی‌خواند. این در `tests/test_ea_remote_config.py` چک می‌شود.
  - مقدارهای دریافتی محدود و نام نمادها بررسی می‌شوند.
- **بررسی نسخه:** EA نسخه‌اش را در heartbeat و publish گزارش می‌دهد، و اگر نسخهٔ جدیدتری اعلام شود فقط آن را log می‌کند.
- **`infra/mql5/MolidoBridge.mq5.sha256`:** تست تضمین می‌کند این فایل با خود EA یکی بماند.
- **`infra/mql5/ea-updater.ps1`:** فایل را دانلود می‌کند، SHA-256 و نسخه را بررسی می‌کند، نسخهٔ پشتیبان می‌گیرد، با `metaeditor64 /compile` کامپایل می‌کند و اگر کامپایل خطا بدهد به نسخهٔ قبل برمی‌گردد. هیچ رمز یا کلیدی در آن نیست. روی ویندوز تست نشده است.

## برنامه مرحله‌ای

هر مرحله روی شاخه جدا، با تست، و فقط با تأیید مالک merge می‌شود. هیچ مرحله‌ای LIVE را فعال نمی‌کند.

| مرحله | کار | برآورد |
|---|---|---|
| ۱ | رجیستری ۵۱ نقش و پیام استاندارد (همین شاخه) | انجام شد |
| ۲ | مستندات و امنیت: حذف IP و شماره حساب از docs، gate پول واقعی داخل EA (`AllowRealAccount=false`؛ نیاز به کامپایل روی ترمینال) | انجام شد |
| ۳ | Grok Gateway مشورتی (`backend/app/agents/gateway/`) | انجام شد — بخش «Grok Gateway» |
| ۴ | شورای v2 در حالت سایه (`backend/app/agents/council/`) | انجام شد — بخش «شورای v2» |
| ۵ | حافظه ایجنت‌ها (`backend/app/agents/memory.py`، migration `0031_agent_memory`) | انجام شد — بخش «حافظه» |
| ۶ | تحلیلگرهای قطعی SC/SM/RT/AI02/BRAIN-01 (`backend/app/agents/analyzers/`) | انجام شد — بخش «تحلیلگرها»؛ walk-forward مانده |
| ۷ | تایم‌فریم‌های کامل MT5 با برچسب Native/Derived (`backend/app/core/timeframes.py`) | انجام شد — بخش «تایم‌فریم‌ها»؛ لیست نماد پویا مانده |
| ۸ | بازبینی تنظیمات ریسک و تست‌های حجم و همبستگی | ۱–۲ روز |
| ۹ | MT5 فقط‌خواندنی و Paper | انجام شد (مرحله ۱۰) |
| ۱۰ | داشبورد: Agent Command Center (`/agents`)، Rocket Radar (`/rocket`)، Grok Cost (`/grok-cost`) | انجام شد (مرحله ۸)؛ FTMO Monitor (`/ftmo`) در مرحله ۱۳ |
| ۱۱ | تست جامع و regression | پیوسته |

تغییر وضعیت یک نقش در `roles.py` یک ادعاست و commit آن باید شاهد (کد و تست) داشته باشد.


## مرحله ۱۵ — تکمیل نقش‌ها (فقط سایه)

- TA02/TA03/RK02: `agents/analyzers/extra.py` (چندتایم‌فریمی از گروه‌های کامل، الگوهای کندلی، پیشنهاد SL/TP).
- SC02: تیک‌های quote از EA 1.30 (`molido_ticks_<SYM>.csv`، فقط وقتی `MOLIDO_EA_TICK_COUNT` بیشتر از صفر باشد)؛ بدون تیک برمی‌گردد به کندل.
- AI02: رگرسیون لجستیک پایتون خالص (`analyzers/ml.py`)، Brier خارج از نمونه؛ بدون مهارت = WAIT.
- SM10: CFTC COT با `MOLIDO_AGENT_COT` (پیش‌فرض خاموش).
- BRAIN-01/AI03: `agents/council/versions.py` و `services/agent_council.py`: بازپخش تصمیم‌های ثبت‌شده با دو نسخهٔ وزن در حافظه؛ پیشنهاد وزن فقط به صورت PROPOSED.
- `GET /agents/run?symbol=` همهٔ تحلیلگرها با سلامت هر ایجنت؛ `GET /agents/council/versions`.
- اصلاح باگ: EA فقط M5، M15 و H1 را منتشر می‌کند (نه هفت تایم‌فریم)؛ برچسب Native و تایم‌فریم‌های مشتق‌شدهٔ اضافه اصلاح شد (M2/M3/M4/M6/M12 منبع ندارند).

## مرحله ۱۶ — سلامت، عملکرد، توضیح تصمیم، هشدار (فقط خواندنی)

- `python -m app.services.agent_run` با `MOLIDO_AGENT_RUN=1` (پیش‌فرض خاموش): یک دور ثبت‌شده روی نمادها؛ هر اجرا در حافظه (kind `agent`، event `run`) با تأخیر و خطای هر ایجنت.
- `GET /agents/health`: هر ۵۱ نقش؛ برای تحلیلگرها: ok / degraded (خطا بیشتر از ۲۰٪) / stale (بیش از ۲۴ ساعت) / never_run.
- `GET /agents/performance`: درصد درست بودن جهت BUY/SELL هر ایجنت پس از N کندل، قبل از اسپرد و هزینه؛ زیر ۳۰ مورد مدرک نیست.
- `GET /agents/explain?symbol=`: رأی‌ها، شواهد، مخالفان، ورودی‌های ناموجود و دلیل «بدون سفارش».
- `GET /agents/alerts`: هشدار از سلامت ایجنت‌ها، Kill Switch، زیان روزانه، دادهٔ کهنه و قوانین FTMO. فقط نمایش داده می‌شود؛ هیچ پیامی ارسال نمی‌شود.
- صفحهٔ `/agent-health`.

# رجیستری ۵۱ ایجنت (مراحل ۱ تا ۶)

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

خلاصه (پس از مرحله ۶): **41 IMPLEMENTED**، **10 PARTIAL**، **0 NOT_IMPLEMENTED**. در مرحله ۱: 14 / 21 / 16.

همه نقش‌های موجود قانون‌محور و قطعی‌اند. «IMPLEMENTED» یعنی کد موجود کار نقش را انجام می‌دهد، نه اینکه یک ایجنت هوش مصنوعی مستقل با این شناسه اجرا می‌شود.

| شناسه | نام | سطح | وضعیت | ماژول‌های موجود |
|---|---|---|---|---|
| SC01 | فرمانده اسکالپینگ | L3 | IMPLEMENTED | `backend/app/agents/analyzers/scalping.py` |
| SC02 | تحلیلگر ریزساختار بازار | L2 | PARTIAL | `backend/app/agents/analyzers/scalping.py` |
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
| SM10 | تحلیلگر ردپای مؤسسات مالی | L2 | PARTIAL | `backend/app/agents/analyzers/smc.py`<br>`backend/app/services/positioning.py` |
| TA01 | تحلیلگر تکنیکال | L2 | IMPLEMENTED | `backend/app/features/indicators.py`<br>`backend/app/services/feature_store.py`<br>`backend/app/brain/council.py` |
| TA02 | تحلیلگر چندتایم‌فریمی | L2 | PARTIAL | `backend/app/workers/autotrade.py`<br>`backend/app/core/enums.py`<br>`backend/app/services/point_in_time.py` |
| TA03 | تحلیلگر پرایس اکشن | L2 | PARTIAL | `backend/app/brain/strategy.py` |
| TA04 | تشخیص‌دهنده روند | L2 | IMPLEMENTED | `backend/app/brain/council.py`<br>`backend/app/learning/rules.py` |
| TA05 | شکارچی نقاط بازگشت | L2 | IMPLEMENTED | `backend/app/learning/rules.py` |
| TA06 | متخصص شکست قیمت | L2 | IMPLEMENTED | `backend/app/learning/rules.py`<br>`backend/app/brain/strategy.py` |
| AI01 | هوش تشخیص وضعیت بازار | L2 | IMPLEMENTED | `backend/app/services/regime.py`<br>`backend/app/learning/regimes.py`<br>`backend/app/brain/council.py` |
| AI02 | هوش پیش‌بینی بازار | L2 | PARTIAL | `backend/app/agents/analyzers/ai02.py`<br>`backend/app/brain/expected_value.py`<br>`backend/app/brain/calibration.py` |
| AI03 | هوش یادگیری تطبیقی | L3 | PARTIAL | `backend/app/learning/brain_selection.py`<br>`backend/app/learning/drift.py`<br>`backend/app/learning/registry.py`<br>`backend/app/learning/lab.py` |
| AI04 | هوش تحلیل خصمانه | L2 | IMPLEMENTED | `backend/app/brain/meta.py` |
| RK01 | نگهبان اصلی ریسک | L4 | IMPLEMENTED | `backend/app/brain/risk.py`<br>`backend/app/execution/safety.py`<br>`backend/app/execution/killswitch_store.py`<br>`backend/app/core/safe_mode.py` |
| RK02 | هوش حد ضرر و حد سود پویا | L3 | PARTIAL | `backend/app/learning/exits.py`<br>`backend/app/learning/geometry.py`<br>`backend/app/workers/trailing.py` |
| RK03 | هوش محاسبه حجم معامله | L4 | IMPLEMENTED | `backend/app/services/calculators.py`<br>`backend/app/workers/autotrade.py` |
| RK04 | هوش مدیریت ریسک پرتفوی | L4 | IMPLEMENTED | `backend/app/brain/portfolio.py`<br>`backend/app/workers/autotrade.py` |
| RK05 | ناظر قوانین FTMO | L4 | IMPLEMENTED | `backend/app/brain/challenge.py`<br>`backend/app/brain/rulebooks.py`<br>`backend/app/services/challenge_accounts.py` |
| EX01 | ایجنت اجرای معاملات متاتریدر | L4 | IMPLEMENTED | `backend/app/execution/metatrader_broker.py`<br>`backend/app/execution/paper_broker.py`<br>`infra/mql5/MolidoBridge.mq5` |
| EX02 | هوش کنترل لغزش قیمت | L4 | PARTIAL | `backend/app/execution/broker.py`<br>`infra/mql5/MolidoBridge.mq5` |
| EX03 | ناظر هوشمند معاملات | L4 | IMPLEMENTED | `backend/app/execution/engine.py`<br>`backend/app/api/v1/execution.py`<br>`backend/app/workers/trailing.py` |
| EX04 | مدیر دفتر ثبت معاملات | L1 | IMPLEMENTED | `backend/app/brain/journal.py`<br>`backend/app/services/journal_log.py`<br>`backend/app/services/audit.py` |
| EX05 | فرمانده کل معاملات | L4 | IMPLEMENTED | `backend/app/execution/autopilot.py`<br>`backend/app/workers/autotrade.py`<br>`backend/app/execution/modes.py` |
| BRAIN-01 | تحلیلگر مغزها و هوش جمعی | L2 | PARTIAL | `backend/app/agents/analyzers/brain01.py`<br>`backend/app/brain/analyst.py`<br>`backend/app/agents/gateway/ledger.py` |
| RT01 | شکارچی انفجار قیمت | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT02 | تحلیلگر جهش مومنتوم | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT03 | شکارچی شکست انفجاری | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT04 | تحلیلگر فشردگی قیمت | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT05 | شکارچی حجم غیرعادی | L2 | IMPLEMENTED | `backend/app/agents/analyzers/rocket.py` |
| RT06 | تحلیلگر اخبار محرک | L2 | PARTIAL | `backend/app/agents/analyzers/rocket.py`<br>`backend/app/brain/challenge.py` |
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
| ۷ | تایم‌فریم‌های کامل MT5 با برچسب Native/Derived و لیست نماد پویا | ۲–۳ روز |
| ۸ | بازبینی تنظیمات ریسک و تست‌های حجم و همبستگی | ۱–۲ روز |
| ۹ | MT5 فقط‌خواندنی و Paper به‌عنوان پیش‌فرض حساب جدید | ۲ روز |
| ۱۰ | داشبورد: Agent Command Center، Rocket Radar، Grok Cost، FTMO Monitor | ۳–۴ روز |
| ۱۱ | تست جامع و regression | پیوسته |

تغییر وضعیت یک نقش در `roles.py` یک ادعاست و commit آن باید شاهد (کد و تست) داشته باشد.

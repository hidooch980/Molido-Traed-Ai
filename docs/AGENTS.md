# رجیستری ۵۱ ایجنت — مرحله ۱

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

خلاصه: **14 IMPLEMENTED**، **21 PARTIAL**، **16 NOT_IMPLEMENTED**.

همه نقش‌های موجود قانون‌محور و قطعی‌اند. «IMPLEMENTED» یعنی کد موجود کار نقش را انجام می‌دهد، نه اینکه یک ایجنت هوش مصنوعی مستقل با این شناسه اجرا می‌شود.

| شناسه | نام | سطح | وضعیت | ماژول‌های موجود |
|---|---|---|---|---|
| SC01 | فرمانده اسکالپینگ | L3 | NOT_IMPLEMENTED | — |
| SC02 | تحلیلگر ریزساختار بازار | L2 | NOT_IMPLEMENTED | — |
| SC03 | شکارچی مومنتوم | L2 | PARTIAL | `backend/app/brain/council.py`<br>`backend/app/features/indicators.py` |
| SC04 | شکارچی نقدینگی | L2 | NOT_IMPLEMENTED | — |
| SC05 | هوش تحلیل اسپرد | L2 | PARTIAL | `backend/app/workers/autotrade.py`<br>`backend/app/brain/challenge.py` |
| SC06 | شکارچی نوسانات | L2 | PARTIAL | `backend/app/brain/council.py`<br>`backend/app/brain/strategy.py`<br>`backend/app/features/indicators.py` |
| SC07 | هوش ورود دقیق | L3 | PARTIAL | `backend/app/brain/strategy.py`<br>`backend/app/pipeline/decide.py` |
| SC08 | هوش خروج سریع | L3 | PARTIAL | `backend/app/learning/exits.py`<br>`backend/app/workers/trailing.py` |
| SC09 | مدیر پوزیشن اسکالپینگ | L3 | PARTIAL | `backend/app/workers/trailing.py`<br>`backend/app/execution/engine.py` |
| SC10 | تحلیلگر عملکرد اسکالپینگ | L2 | PARTIAL | `backend/app/learning/scorecard.py`<br>`backend/app/learning/measure.py` |
| SM01 | تحلیلگر پول هوشمند | L2 | NOT_IMPLEMENTED | — |
| SM02 | شکارچی جاروکردن نقدینگی | L2 | NOT_IMPLEMENTED | — |
| SM03 | شکارچی بلوک سفارش | L2 | NOT_IMPLEMENTED | — |
| SM04 | تحلیلگر Fair Value Gap | L2 | NOT_IMPLEMENTED | — |
| SM05 | تشخیص‌دهنده BOS و CHoCH | L2 | NOT_IMPLEMENTED | — |
| SM06 | تحلیلگر ساختار بازار | L2 | PARTIAL | `backend/app/brain/council.py`<br>`backend/app/learning/rules.py` |
| SM07 | تحلیلگر نقدینگی سمت خرید و فروش | L2 | NOT_IMPLEMENTED | — |
| SM08 | تحلیلگر Premium و Discount | L2 | PARTIAL | `backend/app/brain/council.py` |
| SM09 | تحلیلگر سشن‌های معاملاتی ICT | L2 | PARTIAL | `backend/app/services/sessions.py`<br>`backend/app/brain/council.py`<br>`backend/app/learning/session_map.py` |
| SM10 | تحلیلگر ردپای مؤسسات مالی | L2 | PARTIAL | `backend/app/services/positioning.py` |
| TA01 | تحلیلگر تکنیکال | L2 | IMPLEMENTED | `backend/app/features/indicators.py`<br>`backend/app/services/feature_store.py`<br>`backend/app/brain/council.py` |
| TA02 | تحلیلگر چندتایم‌فریمی | L2 | PARTIAL | `backend/app/workers/autotrade.py`<br>`backend/app/core/enums.py`<br>`backend/app/services/point_in_time.py` |
| TA03 | تحلیلگر پرایس اکشن | L2 | PARTIAL | `backend/app/brain/strategy.py` |
| TA04 | تشخیص‌دهنده روند | L2 | IMPLEMENTED | `backend/app/brain/council.py`<br>`backend/app/learning/rules.py` |
| TA05 | شکارچی نقاط بازگشت | L2 | IMPLEMENTED | `backend/app/learning/rules.py` |
| TA06 | متخصص شکست قیمت | L2 | IMPLEMENTED | `backend/app/learning/rules.py`<br>`backend/app/brain/strategy.py` |
| AI01 | هوش تشخیص وضعیت بازار | L2 | IMPLEMENTED | `backend/app/services/regime.py`<br>`backend/app/learning/regimes.py`<br>`backend/app/brain/council.py` |
| AI02 | هوش پیش‌بینی بازار | L2 | PARTIAL | `backend/app/brain/expected_value.py`<br>`backend/app/brain/calibration.py` |
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
| BRAIN-01 | تحلیلگر مغزها و هوش جمعی | L2 | PARTIAL | `backend/app/brain/analyst.py` |
| RT01 | شکارچی انفجار قیمت | L2 | NOT_IMPLEMENTED | — |
| RT02 | تحلیلگر جهش مومنتوم | L2 | NOT_IMPLEMENTED | — |
| RT03 | شکارچی شکست انفجاری | L2 | PARTIAL | `backend/app/learning/rules.py` |
| RT04 | تحلیلگر فشردگی قیمت | L2 | PARTIAL | `backend/app/learning/rules.py` |
| RT05 | شکارچی حجم غیرعادی | L2 | NOT_IMPLEMENTED | — |
| RT06 | تحلیلگر اخبار محرک | L2 | PARTIAL | `backend/app/brain/challenge.py`<br>`backend/app/api/v1/fundamentals.py` |
| RT07 | شکارچی نقدینگی انفجاری | L2 | NOT_IMPLEMENTED | — |
| RT08 | پیش‌بینی‌کننده حرکت شارپی | L2 | NOT_IMPLEMENTED | — |
| RT09 | مدیر خروج موشکی | L3 | NOT_IMPLEMENTED | — |
| RT10 | ارزیاب فرصت‌های موشکی | L3 | NOT_IMPLEMENTED | — |

## برنامه مرحله‌ای

هر مرحله روی شاخه جدا، با تست، و فقط با تأیید مالک merge می‌شود. هیچ مرحله‌ای LIVE را فعال نمی‌کند.

| مرحله | کار | برآورد |
|---|---|---|
| ۱ | رجیستری ۵۱ نقش و پیام استاندارد (همین شاخه) | انجام شد |
| ۲ | مستندات و امنیت: حذف IP و شماره حساب از docs، gate پول واقعی داخل EA (`AllowRealAccount=false`؛ نیاز به کامپایل روی ترمینال) | انجام شد |
| ۳ | Grok Gateway مشورتی: کش، حذف تکرار، صف، بودجه، circuit breaker، ثبت توکن و هزینه؛ بدون مسیر به execution | ۳–۵ روز |
| ۴ | مغز و شورا: تحلیلگرهای خبر، اقتصاد کلان و Quant؛ وزن‌دهی بر اساس عملکرد خارج از نمونه | ۳–۴ روز |
| ۵ | حافظه هر ایجنت و حافظه تصمیم شورا روی جدول‌های موجود | ۲–۳ روز |
| ۶ | Rocket Hunter (RT01–RT10) به‌صورت PROPOSED، ثبت R1–R5 بدون معامله، سپس walk-forward | ۵–۸ روز |
| ۷ | تایم‌فریم‌های کامل MT5 با برچسب Native/Derived و لیست نماد پویا | ۲–۳ روز |
| ۸ | بازبینی تنظیمات ریسک و تست‌های حجم و همبستگی | ۱–۲ روز |
| ۹ | MT5 فقط‌خواندنی و Paper به‌عنوان پیش‌فرض حساب جدید | ۲ روز |
| ۱۰ | داشبورد: Agent Command Center، Rocket Radar، Grok Cost، FTMO Monitor | ۳–۴ روز |
| ۱۱ | تست جامع و regression | پیوسته |

تغییر وضعیت یک نقش در `roles.py` یک ادعاست و commit آن باید شاهد (کد و تست) داشته باشد.

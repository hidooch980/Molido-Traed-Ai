# اسمارت مانی (SMC) و راکت هانتر — قوانین و وضعیت (Molido Expert 2.31)

کد: `infra/mql5/MolidoSMC.mqh` و `infra/mql5/MolidoRocket.mqh` (افزایشی؛ هیچ قابلیت قبلی حذف نشده).
اتصال: `MolidoDemoScalper.mqh` → `DemoEvaluateSymbol` (کاندید ورود)، `MolidoRuntime.mqh` (include)، دکمه‌های `rk` و `sm` در `MolidoExpertUI.mqh`.

## قانون مشترک
هر دو استراتژی فقط «کاندید ورود» می‌سازند. کاندید از همان مسیرها عبور می‌کند:
`DemoSmartAllowEntry` → `DemoProtectAllowEntry` → `DemoReview` (Risk Brain، سقف ریسک، حفاظت پراپ، سقف لات) → `ExpertPolicyAllow`
(قفل تک‌نمونه، بلاک فلزات در لندن، فیلتر روند H1/H4، اسپرد/ATR، فیلتر خبر، SP2L/FVG در صورت روشن بودن، حداقل TP به R).
حساب واقعی همچنان قفل است. فقط کندل‌های بسته‌شده استفاده می‌شوند (بدون repaint).
ورودی‌ها: `InpUseSmartMoney` و `InpUseRocket` (پیش‌فرض false). دکمه‌های داشبورد وضعیت را عوض می‌کنند و در GlobalVariable ذخیره می‌شود (`Molido.Strat.SMC` / `Molido.Strat.Rocket`).

وضعیت‌ها: RESEARCH (تحقیق) · SPECIFIED (مشخص‌شده) · IMPLEMENTED (پیاده‌سازی) · TESTED (کامپایل + بک‌تست) · VERIFIED (سودده در خارج از نمونه).

## اسمارت مانی (SMC)
| # | قانون | منبع | وضعیت |
|---|---|---|---|
| S1 | سوئینگ: پیووت با k=2 کندل بسته در هر طرف، اکسترمم یکتا | backend `bars.swings` | IMPLEMENTED |
| S2 | بایاس HTF (H1): HH+HL = صعودی، LH+LL = نزولی، رنج = بدون معامله | backend SM06 | IMPLEMENTED |
| S3 | سوئیپ نقدینگی: شدو زیر کف سوئینگی که «کف‌های برابر» است (تلورانس 0.1×ATR) یا زیر کف روز قبل، و بسته شدن بالای آن (قرینه برای فروش) | backend SM02 + `equal_levels` | IMPLEMENTED |
| S4 | CHoCH: حداکثر 20 کندل بعد از سوئیپ، بسته شدن بالای آخرین سقف سوئینگی | backend SM05 | IMPLEMENTED |
| S5 | اردربلاک: آخرین کندل مخالف قبل از حرکت جابه‌جایی (بین سوئیپ و CHoCH)؛ با بسته شدن کندل فراتر از لبهٔ دور، باطل | تعریف استاندارد / SM03 | IMPLEMENTED |
| S6 | FVG: گپ سه‌کندلی پرنشده بین سوئیپ و CHoCH، اگر برگشت به OB نبود | backend SM04 / کد FVG موجود | IMPLEMENTED |
| S7 | ورود: آخرین کندل بسته‌شده وارد OB/FVG شود و داخل/بالای لبهٔ پایین بسته شود؛ حداکثر 30 کندل بعد از CHoCH | تعریف استاندارد | IMPLEMENTED |
| S8 | پریمیوم/دیسکانت: خرید فقط زیر 50٪ رنج (سوئیپ تا CHoCH)، فروش فقط بالای 50٪ | backend SM08 | IMPLEMENTED |
| S9 | SL: فراتر از min(کف OB، کف سوئیپ) + 0.1×ATR + اسپرد | brief | IMPLEMENTED |
| S10 | TP: نزدیک‌ترین نقدینگی مقابل (سقف سوئینگ یا سقف روز قبل) با حداقل 2R؛ اگر نبود، ثابت 2R | brief | IMPLEMENTED (حالت جایگزین 2R ثابت یک انتخاب مهندسی است) |
| S11 | هر زون فقط یک بار معامله می‌شود | ایمنی | IMPLEMENTED |

## راکت هانتر (Rocket)
هم‌راستا با نقش‌های سرور `backend/app/agents/analyzers/rocket.py`.
| # | قانون | منبع | وضعیت |
|---|---|---|---|
| R1 | انفجار رنج: رنج کندل ≥ 2.5×ATR20 (الزامی) | RT01 | IMPLEMENTED |
| R2 | شکست باکس: بسته شدن فراتر از سقف/کف 20 کندل قبلی + 0.2×ATR (الزامی) | RT03 | IMPLEMENTED |
| R3 | مومنتوم: حرکت 3 کندلی ≥ 1.5×ATR و شتاب‌دار (+1) | RT02 | IMPLEMENTED |
| R4 | فشردگی: صدک عرض (انحراف معیار/میانگین 20) ≤ 20٪ در 100 کندل اخیر (+1) | RT04 | IMPLEMENTED |
| R5 | حجم تیک ≥ 2.5× میانهٔ همان ساعت (+1) | RT05 | IMPLEMENTED |
| R6 | امتیاز = موافق‌ها − جریمه‌ها؛ شکست فیک قبلی −1، فاصله > 3×ATR از EMA20 −1.5؛ حداقل امتیاز 3 | RT10 | IMPLEMENTED |
| R7 | فیلتر روند: EMA50/200 در H1 و H4 (فیلتر مشترک Expert) | brief / ExpertTrendAligned | IMPLEMENTED |
| R8 | SL: دورتر از آخرین سوئینگ و 1×ATR از قیمت بسته شدن | RT10 | IMPLEMENTED |
| R9 | TP = 2R؛ R:R خالص بعد از اسپرد و لغزش 0.05×ATR باید ≥ 1.2 | RT10 | IMPLEMENTED |
| R10 | مدیریت خروج: سربه‌سر در 1R، تریل 1×ATR بعد از 1.5R (خروج مشترک Expert) | RT09 | IMPLEMENTED |
| R11 | حالت ورود 1: ورود روی ری‌تست سطح شکست تا 3 کندل | brief | IMPLEMENTED (پیش‌فرض خاموش) |
| R12 | خبر به‌عنوان کاتالیزور (RT06) | RT06 | NOT IMPLEMENTED (فید تقویم معمولاً خالی است؛ فیلتر خبر مشترک اعمال می‌شود) |

## نتایج بک‌تست
در `docs/smc-rocket-backtest-fa.md` و `deliver/molido-expert/smc-rocket-progress.json` ثبت می‌شود. وضعیت TESTED فقط بعد از کامپایل بدون خطا و بک‌تست واقعی؛ VERIFIED فقط با نتیجهٔ مثبت خارج از نمونه.

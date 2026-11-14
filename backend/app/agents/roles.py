# ruff: noqa: E501 - role notes are Persian prose data, kept on one line each.
"""The 51 roles, with the honest status of each (updated at stage 6).

Status comes from the read-only audit of `main` at ae99797 (2026-11-14):
every existing analyst, brain and guard in this codebase is rule-based and
deterministic, and none of them carries one of these IDs yet. A role is
IMPLEMENTED when existing code already does what the role describes, PARTIAL
when some of it exists (often on a different horizon or as a proposed rule
that does not trade), and NOT_IMPLEMENTED when nothing does. Changing a status
here is a claim; the commit that changes it should carry the evidence.

Stage 6 (2026-11-14) added deterministic shadow analyzers under
`app/agents/analyzers/` for SC, SM, RT, AI02 and BRAIN-01. IMPLEMENTED there
means the logic exists and is tested for point-in-time safety; it is not wired
into decisions and no profitable edge has been measured.
"""

from __future__ import annotations

from app.agents.model import AgentGroup as G
from app.agents.model import AgentRole
from app.agents.model import ImplementationStatus as S
from app.agents.model import PermissionLevel as P

B = "backend/app/"

NO_ORDERS = "حق اجرای معامله ندارد؛ فقط پیشنهاد می‌دهد."
NO_PRIVATE_FLOW = "نباید ادعای دسترسی به سفارش‌های محرمانه بانک‌ها یا کل بازار OTC کند."
NOT_CERTAIN = "الگوی تصادفی یا آماری را قطعی معرفی نمی‌کند."

ON_BAR = "بسته‌شدن کندل در تایم‌فریم مربوط"
ON_SIGNAL = "سیگنال یا پیشنهاد جدید از ایجنت دیگر"
ON_POSITION = "باز یا بسته‌شدن پوزیشن، یا تغییر قیمت پوزیشن باز"
ON_NEWS = "نزدیک‌شدن رویداد پراهمیت تقویم اقتصادی"
ON_SCHEDULE = "اجرای زمان‌بندی‌شده (روزانه یا هفتگی)"
ON_REQUEST = "درخواست تحلیل از فرمانده یا شورا"
ON_VOLATILITY = "جهش نوسان یا حجم تیک نسبت به خط پایه همان نماد و سشن"


def _role(
    id_: str,
    fa: str,
    en: str,
    group: G,
    responsibilities: tuple[str, ...],
    level: P,
    status: S,
    *,
    modules: tuple[str, ...] = (),
    restrictions: tuple[str, ...] = (NO_ORDERS,),
    triggers: tuple[str, ...] = (ON_BAR, ON_REQUEST),
    notes: str = "",
) -> AgentRole:
    return AgentRole(
        id=id_,
        name_fa=fa,
        name_en=en,
        group=group,
        responsibilities=responsibilities,
        permission_level=level,
        restrictions=restrictions,
        triggers=triggers,
        modules=tuple(B + m if not m.startswith("infra/") else m for m in modules),
        status=status,
        notes=notes,
    )


ROLES: tuple[AgentRole, ...] = (
    # ------------------------------------------------------------ A scalping
    _role(
        "SC01", "فرمانده اسکالپینگ", "Scalping Commander", G.SCALPING,
        ("هماهنگی کل عملیات اسکالپینگ", "تجمیع نظر SC02 تا SC10", "اعلام WAIT در نبود اجماع معتبر"),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        triggers=(ON_SIGNAL, ON_VOLATILITY, ON_REQUEST),
    ),
    _role(
        "SC02", "تحلیلگر ریزساختار بازار", "Market Microstructure Analyst", G.SCALPING,
        ("بررسی رفتار قیمت در سطح تیک", "تغییرات کوتاه‌مدت قیمت و اسپرد"),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py", "services/agent_run.py"),
        notes="مرحله ۱۵: تیک‌های quote از EA 1.30 (فایل molido_ticks_<SYM>.csv، فقط وقتی tick_count از سمت Molido بیشتر از صفر باشد؛ پیش‌فرض خاموش)؛ عدم‌توازن تیک و اسپرد؛ اسپرد غیرعادی = WAIT. بدون تیک به کندل برمی‌گردد با اطمینان حداکثر ۰٫۴. EA روی MT5 واقعی کامپایل/تست نشده. تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        triggers=(ON_VOLATILITY, ON_REQUEST),
    ),
    _role(
        "SC03", "شکارچی مومنتوم", "Momentum Hunter", G.SCALPING,
        ("تشخیص شتاب حرکت قیمت",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
    ),
    _role(
        "SC04", "شکارچی نقدینگی", "Liquidity Hunter", G.SCALPING,
        ("تشخیص مناطق تجمع نقدینگی",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW),
    ),
    _role(
        "SC05", "هوش تحلیل اسپرد", "Spread Intelligence", G.SCALPING,
        ("بررسی اسپرد و هزینه واقعی ورود", "رد ورود وقتی هزینه از لبه بیشتر است"),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py", "workers/autotrade.py"),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سقف اسپرد موجود در autotrade همچنان مرجع اجرایی است.",
    ),
    _role(
        "SC06", "شکارچی نوسانات", "Volatility Hunter", G.SCALPING,
        ("شناسایی افزایش و کاهش نوسان",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        triggers=(ON_BAR, ON_VOLATILITY),
    ),
    _role(
        "SC07", "هوش ورود دقیق", "Precision Entry", G.SCALPING,
        ("انتخاب نقطه ورود معتبر", "بررسی تأیید ورود و نسبت سود به زیان"),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        triggers=(ON_SIGNAL, ON_REQUEST),
    ),
    _role(
        "SC08", "هوش خروج سریع", "Fast Exit", G.SCALPING,
        ("تشخیص زمان خروج",),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py", "learning/exits.py", "workers/trailing.py"),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        triggers=(ON_POSITION,),
    ),
    _role(
        "SC09", "مدیر پوزیشن اسکالپینگ", "Scalping Position Manager", G.SCALPING,
        ("مدیریت موقعیت‌های باز", "پیشنهاد جابه‌جایی حد ضرر"),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py", "workers/trailing.py"),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. فقط پیشنهاد جابه‌جایی استاپ؛ اجرا با trailing موجود است.",
        triggers=(ON_POSITION,),
    ),
    _role(
        "SC10", "تحلیلگر عملکرد اسکالپینگ", "Scalping Performance Analyst", G.SCALPING,
        ("بررسی عملکرد استراتژی‌ها پس از هزینه",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/scalping.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        triggers=(ON_SCHEDULE, ON_POSITION),
    ),
    # ---------------------------------------------------------- B smart money
    _role(
        "SM01", "تحلیلگر پول هوشمند", "Smart Money Analyst", G.SMART_MONEY,
        ("تجمیع مفاهیم SMC بر پایه داده قابل دسترس",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW),
    ),
    _role(
        "SM02", "شکارچی جاروکردن نقدینگی", "Liquidity Sweep Hunter", G.SMART_MONEY,
        ("تشخیص Sweep سقف و کف‌ها",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW),
    ),
    _role(
        "SM03", "شکارچی بلوک سفارش", "Order Block Hunter", G.SMART_MONEY,
        ("شناسایی Order Block",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW, NOT_CERTAIN),
    ),
    _role(
        "SM04", "تحلیلگر Fair Value Gap", "Fair Value Gap Analyst", G.SMART_MONEY,
        ("شناسایی و پیگیری FVG",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
        restrictions=(NO_ORDERS, NOT_CERTAIN),
    ),
    _role(
        "SM05", "تشخیص‌دهنده BOS و CHoCH", "BOS/CHoCH Detector", G.SMART_MONEY,
        ("تشخیص شکست ساختار و تغییر شخصیت بازار",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
        restrictions=(NO_ORDERS, NOT_CERTAIN),
    ),
    _role(
        "SM06", "تحلیلگر ساختار بازار", "Market Structure Analyst", G.SMART_MONEY,
        ("تحلیل سقف‌ها و کف‌های swing",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
    ),
    _role(
        "SM07", "تحلیلگر نقدینگی سمت خرید و فروش", "Buy/Sell-Side Liquidity Analyst",
        G.SMART_MONEY,
        ("شناسایی BSL و SSL",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW),
    ),
    _role(
        "SM08", "تحلیلگر Premium و Discount", "Premium/Discount Analyst", G.SMART_MONEY,
        ("تعیین موقعیت قیمت در محدوده",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
    ),
    _role(
        "SM09", "تحلیلگر سشن‌های معاملاتی ICT", "ICT Session Analyst", G.SMART_MONEY,
        ("تحلیل رفتار سشن‌های سیدنی، توکیو، لندن و نیویورک",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. الگو روی کندل بروکر است، نه داده سفارش مؤسسات.",
    ),
    _role(
        "SM10", "تحلیلگر ردپای مؤسسات مالی", "Institutional Footprint Analyst",
        G.SMART_MONEY,
        ("تحلیل موقعیت مؤسسات فقط بر اساس داده عمومی قابل دسترس",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/smc.py", "services/positioning.py", "services/agent_run.py"),
        notes="مرحله ۱۵: فقط داده عمومی و هفتگی CFTC COT (با تأخیر) از positioning.pair_tilt، پشت پرچم MOLIDO_AGENT_COT (پیش‌فرض خاموش)؛ نبود داده = WAIT. تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW),
        triggers=(ON_SCHEDULE, ON_REQUEST),
    ),
    # ------------------------------------------------------------ C technical
    _role(
        "TA01", "تحلیلگر تکنیکال", "Technical Analyst", G.TECHNICAL,
        ("RSI، MACD، ATR و سایر اندیکاتورها", "ثبت شواهد تحلیل"),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "features/indicators.py", "services/feature_store.py", "brain/council.py"),
    ),
    _role(
        "TA02", "تحلیلگر چندتایم‌فریمی", "Multi-Timeframe Analyst", G.TECHNICAL,
        ("هماهنگی تحلیل بین تایم‌فریم‌ها بدون داده آینده",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/extra.py", "core/timeframes.py", "workers/autotrade.py"),
        notes="مرحله ۱۵: روند EMA20 روی پایه، ×۴ و ×۱۶ از کندل‌های بسته و گروه‌های کامل (بدون نگاه به آینده). تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
    ),
    _role(
        "TA03", "تحلیلگر پرایس اکشن", "Price Action Analyst", G.TECHNICAL,
        ("تحلیل رفتار کندل و setupهای قیمتی",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/extra.py", "brain/strategy.py"),
        notes="مرحله ۱۵: engulfing، pin bar، inside bar، doji؛ قوی‌تر کنار سوئینگ تأییدشده. تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده.",
    ),
    _role(
        "TA04", "تشخیص‌دهنده روند", "Trend Detector", G.TECHNICAL,
        ("تشخیص جهت و قدرت روند",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "brain/council.py", "learning/rules.py"),
        notes="تحلیلگر trend شورا و مغزهای trend-following و time-series-momentum.",
    ),
    _role(
        "TA05", "شکارچی نقاط بازگشت", "Reversal Hunter", G.TECHNICAL,
        ("تشخیص نقاط بازگشت",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "learning/rules.py",),
        restrictions=(NO_ORDERS, NOT_CERTAIN),
        notes="rsi-mean-reversion، stochastic-reversion و short-horizon-reversal.",
    ),
    _role(
        "TA06", "متخصص شکست قیمت", "Breakout Specialist", G.TECHNICAL,
        ("تشخیص شکست معتبر سطوح",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "learning/rules.py", "brain/strategy.py"),
        notes="donchian-breakout و breakout_continuation.",
    ),
    # ----------------------------------------------------------- D prediction
    _role(
        "AI01", "هوش تشخیص وضعیت بازار", "Market Regime Intelligence", G.PREDICTION,
        ("تشخیص رژیم روند، رنج، نوسان شدید یا نامطمئن",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "services/regime.py", "learning/regimes.py", "brain/council.py"),
    ),
    _role(
        "AI02", "هوش پیش‌بینی بازار", "Market Prediction Intelligence", G.PREDICTION,
        ("ساخت سناریوی احتمالی با کالیبراسیون", "اعلام عدم قطعیت"),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/ai02.py", "agents/analyzers/ml.py", "brain/calibration.py"),
        notes="مرحله ۱۵: رگرسیون لجستیک سبک (پایتون خالص، ۷ ویژگی) با تقسیم زمانی ۷۰/۳۰ و Brier خارج از نمونه؛ بدون مهارت OOS = WAIT؛ زیر ۳۰۰ کندل خط پایهٔ ساده. آفلاین/سایه.",
        restrictions=(NO_ORDERS, NOT_CERTAIN),
    ),
    _role(
        "AI03", "هوش یادگیری تطبیقی", "Adaptive Learning Intelligence", G.PREDICTION,
        ("یادگیری از نتایج خارج از نمونه", "پیشنهاد وزن‌دهی؛ هرگز اعمال مستقیم روی LIVE"),
        P.PROPOSE, S.IMPLEMENTED,
        notes="مرحله ۱۵: پیشنهاد وزن شورا از اعتبار خارج از نمونهٔ اعضا (گام محدود، حداقل ۳۰ نتیجه)، بازپخش روی تصمیم‌های ثبت‌شده و ثبت به صورت PROPOSED؛ اعمال فقط با تأیید انسانی. انتخاب مغز و drift قانون‌محورند؛ وزن‌های meta-brain در مسیر اجرا ثابت می‌مانند.",
        modules=("agents/analyzers/fleet.py", 
            "agents/council/versions.py", "services/agent_council.py",
            "learning/brain_selection.py", "learning/drift.py",
            "learning/registry.py", "learning/lab.py",
        ),
        restrictions=(NO_ORDERS, "مدل عملیاتی را بدون اعتبارسنجی و تأیید انسانی تغییر نمی‌دهد."),
        triggers=(ON_SCHEDULE, ON_POSITION),
    ),
    _role(
        "AI04", "هوش تحلیل خصمانه", "Adversarial Intelligence", G.PREDICTION,
        ("استدلال علیه هر پیشنهاد", "کاهش اطمینان در صورت یافتن شواهد مخالف"),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "brain/meta.py",),
        triggers=(ON_SIGNAL,),
    ),
    # ----------------------------------------------------------------- E risk
    _role(
        "RK01", "نگهبان اصلی ریسک", "Chief Risk Guardian", G.RISK,
        ("صدور APPROVE، REDUCE یا BLOCK", "حدود سخت تغییرناپذیر", "توقف اضطراری"),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", 
            "brain/risk.py", "execution/safety.py",
            "execution/killswitch_store.py", "core/safe_mode.py",
        ),
        restrictions=(
            "مستقل از Grok و امتیاز ایجنت‌ها تصمیم می‌گیرد.",
            "فقط می‌تواند ریسک را کم یا مسدود کند؛ هرگز افزایش نمی‌دهد.",
            "خاموش‌کردن Kill Switch فقط کار انسان است.",
        ),
        triggers=(ON_SIGNAL, ON_POSITION, ON_NEWS),
    ),
    _role(
        "RK02", "هوش حد ضرر و حد سود پویا", "Dynamic SL/TP Intelligence", G.RISK,
        ("محاسبه قطعی فاصله حد ضرر و حد سود", "پیشنهاد trailing"),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/extra.py", "learning/exits.py", "workers/trailing.py"),
        notes="مرحله ۱۵: حد ضرر پشت سوئینگ تأییدشده + ۰٫۲۵ ATR (بین ۱ تا ۳ ATR)، حد سود سوئینگ بعدی یا 2R؛ فقط پیشنهاد، همیشه WAIT.",
        triggers=(ON_SIGNAL, ON_POSITION),
    ),
    _role(
        "RK03", "هوش محاسبه حجم معامله", "Position Sizing Intelligence", G.RISK,
        ("محاسبه قطعی حجم از موجودی، فاصله استاپ و ارزش تیک بروکر",),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "services/calculators.py", "workers/autotrade.py"),
        restrictions=("حجم را با کد قطعی محاسبه می‌کند، نه با مدل زبانی.",),
        triggers=(ON_SIGNAL,),
    ),
    _role(
        "RK04", "هوش مدیریت ریسک پرتفوی", "Portfolio Risk Intelligence", G.RISK,
        ("کنترل همبستگی، Exposure و سقف‌های ناوگان",),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "brain/portfolio.py", "workers/autotrade.py"),
        restrictions=("فقط می‌تواند ریسک را کم یا مسدود کند.",),
        triggers=(ON_SIGNAL, ON_POSITION),
    ),
    _role(
        "RK05", "ناظر قوانین FTMO", "FTMO Rules Supervisor", G.RISK,
        ("کنترل حد ضرر روزانه و کل حساب پراپ", "قوانین آخر هفته و اخبار"),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "brain/challenge.py", "brain/rulebooks.py", "services/challenge_accounts.py"),
        restrictions=("فقط می‌تواند ریسک را کم یا مسدود کند.",),
        triggers=(ON_SIGNAL, ON_POSITION, ON_NEWS, ON_SCHEDULE),
    ),
    # ------------------------------------------------------------ F execution
    _role(
        "EX01", "ایجنت اجرای معاملات متاتریدر", "MetaTrader Execution Agent", G.EXECUTION,
        ("انتقال سفارش تأییدشده به پل MT5", "گزارش UNKNOWN به‌جای تکرار سفارش"),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", 
            "execution/metatrader_broker.py", "execution/paper_broker.py",
            "infra/mql5/MolidoBridge.mq5",
        ),
        restrictions=(
            "خود این نقش سفارش صادر نمی‌کند؛ کد موجود فقط پس از Risk Brain و gate حساب ارسال می‌کند.",
            "سفارش با وضعیت نامشخص هرگز دوباره ارسال نمی‌شود.",
        ),
        triggers=("تأیید Risk Brain برای یک intent",),
        notes="ارسال واقعی فقط روی حساب دمو مجاز است (account_gate)؛ این مرحله Paper است.",
    ),
    _role(
        "EX02", "هوش کنترل لغزش قیمت", "Slippage Control Intelligence", G.EXECUTION,
        ("برآورد و ثبت لغزش", "رد اجرا وقتی لغزش از سقف بیشتر است"),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/slippage.py", "agents/analyzers/fleet.py",
                 "services/agent_slippage.py", "execution/broker.py",
                 "infra/mql5/MolidoBridge.mq5"),
        triggers=("تأیید Risk Brain برای یک intent", ON_POSITION),
        notes="مرحله ۲۰: ثبت قیمت درخواستی در برابر قیمت پر شده، آمار (میانگین و p90) "
              "و رد اجرا وقتی برآورد از سقف بیشتر است. بدون نمونه، لغزش صفر فرض نمی‌شود "
              "(WAIT). فقط سایه/paper؛ Risk Brain را override نمی‌کند.",
    ),
    _role(
        "EX03", "ناظر هوشمند معاملات", "Position Guardian", G.EXECUTION,
        ("نظارت بر پوزیشن‌های باز و تطبیق با ترمینال",),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "execution/engine.py", "api/v1/execution.py", "workers/trailing.py"),
        triggers=(ON_POSITION, ON_SCHEDULE),
    ),
    _role(
        "EX04", "مدیر دفتر ثبت معاملات", "Trade Journal Manager", G.EXECUTION,
        ("ثبت کامل هر تصمیم و معامله برای ممیزی",),
        P.READ, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "brain/journal.py", "services/journal_log.py", "services/audit.py"),
        restrictions=("فقط می‌نویسد و می‌خواند؛ سابقه را بازنویسی نمی‌کند.",),
        triggers=(ON_SIGNAL, ON_POSITION),
    ),
    _role(
        "EX05", "فرمانده کل معاملات", "Execution Commander", G.EXECUTION,
        ("هماهنگی چرخه سفارش از تصمیم تا اجرا", "رعایت Kill Switch و gate حساب"),
        P.CONTROL, S.IMPLEMENTED,
        modules=("agents/analyzers/fleet.py", "execution/autopilot.py", "workers/autotrade.py", "execution/modes.py"),
        restrictions=("بدون تأیید Risk Brain هیچ intentی را جلو نمی‌برد.",),
        triggers=(ON_SIGNAL, ON_SCHEDULE),
    ),
    # -------------------------------------------------------------- G central
    _role(
        "BRAIN-01", "تحلیلگر مغزها و هوش جمعی", "Brain Analyst", G.CENTRAL,
        (
            "ارزیابی مغز مرکزی و مغزهای تخصصی", "کشف تناقض‌های تحلیلی",
            "بررسی هزینه‌های غیرضروری مدل زبانی", "آزمایش نسخه‌های جدید فقط در محیط ایزوله",
        ),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/brain01.py", "agents/council/versions.py",
                 "agents/analyzers/runner.py", "agents/gateway/ledger.py"),
        notes="ارزیاب قطعی پیام ایجنت‌ها (تعارض، اطمینان بیش‌ازحد، تکرار، اعتبار)، سلامت هر ایجنت (تأخیر/خطا) و دفتر هزینه Grok (درگاه مرحله ۳، بدون کلید غیرفعال)؛ مرحله ۱۵: آزمایش ایزولهٔ نسخهٔ وزن‌ها با بازپخش در حافظه، بدون اعمال.",
        restrictions=(
            NO_ORDERS, "مغزهای عملیاتی را خودسرانه تغییر نمی‌دهد.",
            "عددی خارج از trace تصمیم نمی‌سازد.",
        ),
        triggers=(ON_SCHEDULE, ON_REQUEST),
    ),
    # --------------------------------------------------------------- H rocket
    _role(
        "RT01", "شکارچی انفجار قیمت", "Price Explosion Hunter", G.ROCKET,
        ("تشخیص شروع حرکت‌های سریع و غیرعادی",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        triggers=(ON_VOLATILITY,),
    ),
    _role(
        "RT02", "تحلیلگر جهش مومنتوم", "Momentum Surge Analyst", G.ROCKET,
        ("بررسی شتاب قیمت و قدرت حرکت",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        triggers=(ON_VOLATILITY,),
    ),
    _role(
        "RT03", "شکارچی شکست انفجاری", "Explosive Breakout Hunter", G.ROCKET,
        ("تشخیص شکست معتبر و شکست جعلی",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        triggers=(ON_VOLATILITY, ON_BAR),
    ),
    _role(
        "RT04", "تحلیلگر فشردگی قیمت", "Compression Analyst", G.ROCKET,
        ("تشخیص فشردگی و احتمال خروج از محدوده",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
    ),
    _role(
        "RT05", "شکارچی حجم غیرعادی", "Abnormal Volume Hunter", G.ROCKET,
        ("مقایسه حجم تیک با خط پایه همان نماد و سشن",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        triggers=(ON_VOLATILITY,),
    ),
    _role(
        "RT06", "تحلیلگر اخبار محرک", "Catalyst News Analyst", G.ROCKET,
        ("بررسی رویدادهای اقتصادی اثرگذار",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py", "services/agent_events.py", "services/calendar.py"),
        notes="تقویم اقتصادی از فید رایگان و بدون کلید ForexFactory (مرحله ۱۲)؛ با MOLIDO_AGENT_CALENDAR=1 روشن می‌شود و پیش‌فرض خاموش است. اگر فید خاموش باشد یا خطا بدهد، RT06 ABSTAIN می‌دهد. تحلیلگر قطعی در حالت سایه.",
        restrictions=(NO_ORDERS, "خبر تأییدنشده را واقعیت اعلام نمی‌کند."),
        triggers=(ON_NEWS,),
    ),
    _role(
        "RT07", "شکارچی نقدینگی انفجاری", "Explosive Liquidity Hunter", G.ROCKET,
        ("شناسایی Sweep و جذب نقدینگی",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        restrictions=(NO_ORDERS, NO_PRIVATE_FLOW),
        triggers=(ON_VOLATILITY,),
    ),
    _role(
        "RT08", "پیش‌بینی‌کننده حرکت شارپی", "Sharp Move Forecaster", G.ROCKET,
        ("ساخت سناریوهای صعودی و نزولی با نقطه ابطال",),
        P.ANALYZE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        restrictions=(NO_ORDERS, NOT_CERTAIN),
        triggers=(ON_SIGNAL,),
    ),
    _role(
        "RT09", "مدیر خروج موشکی", "Rocket Exit Manager", G.ROCKET,
        ("مدیریت خروج سریع و برداشت مرحله‌ای",),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        triggers=(ON_POSITION,),
    ),
    _role(
        "RT10", "ارزیاب فرصت‌های موشکی", "Rocket Opportunity Evaluator", G.ROCKET,
        ("رتبه‌بندی R1 تا R5 (کیفیت سیگنال، نه تضمین سود)", "یادگیری از نتایج خارج از نمونه"),
        P.PROPOSE, S.IMPLEMENTED,
        modules=("agents/analyzers/rocket.py",),
        notes="تحلیلگر قطعی در حالت سایه؛ به مسیر تصمیم وصل نیست؛ لبهٔ سودده آن سنجیده نشده. سیگنال‌ها فقط PROPOSED هستند.",
        triggers=(ON_SIGNAL, ON_SCHEDULE),
    ),
)

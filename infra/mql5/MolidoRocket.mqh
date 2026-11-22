//+------------------------------------------------------------------+
//| MolidoRocket.mqh - Rocket Hunter momentum breakout, Expert 2.31+.|
//| Additive: default OFF (InpUseRocket=false). Rules follow the     |
//| server Rocket roles (backend/app/agents/analyzers/rocket.py):    |
//| RT01 range explosion, RT02 momentum surge, RT03 breakout,        |
//| RT04 compression release, RT05 abnormal tick volume, RT10 score, |
//| stretch penalty, swing/1-ATR stop and 2R target; RT09 exit plan  |
//| (BE at 1R, 1-ATR trail after 1.5R) = shared Expert exits.        |
//| Candidates still pass Risk Brain, prop guards, caps, news, lock. |
//| Rules and their status: docs/smc-rocket-fa.md                    |
//+------------------------------------------------------------------+
#ifndef MOLIDO_ROCKET_MQH
#define MOLIDO_ROCKET_MQH

input group "Expert 2.31 Rocket Hunter - default off"
input bool            InpUseRocket          = false;         // Rocket Hunter momentum breakout
input ENUM_TIMEFRAMES InpRocketTF           = PERIOD_CURRENT; // Rocket timeframe (current = chart)
input double          InpRocketRangeAtr     = 2.5;           // RT01: bar range >= k x ATR20 (required)
input int             InpRocketBoxBars      = 20;            // RT03: breakout of the prior N-bar range (required)
input double          InpRocketBreakAtr     = 0.2;           // RT03: close beyond the box by x ATR
input double          InpRocketVolMult      = 2.5;           // RT05: tick volume >= x same-hour median
input double          InpRocketCompPct      = 0.20;          // RT04: width percentile <= this
input double          InpRocketMinScore     = 3.0;           // RT10-style score (supports - conflicts)
input double          InpRocketMaxStretchAtr= 3.0;           // RT10: > x ATR from EMA20 = chasing (-1.5)
input int             InpRocketEntryMode    = 0;             // 0 market on breakout close, 1 quick retest (<=3 bars)
input double          InpRocketRR           = 2.0;           // RT10 target in R

bool     g_rt_rocket       = false;
datetime g_rocket_last_bar = 0;
//--- pending retest (mode 1)
string   g_rk_pend_side    = "";
double   g_rk_pend_level   = 0.0;
double   g_rk_pend_stop    = 0.0;
datetime g_rk_pend_bar     = 0;

double RkEma(const MxBar &b[], const int end_inclusive, const int period)
  {
   int start = MathMax(0, end_inclusive - period * 4);
   double k = 2.0 / (period + 1.0);
   double e = b[start].c;
   for(int i = start + 1; i <= end_inclusive; i++)
      e = b[i].c * k + e * (1.0 - k);
   return(e);
  }

//--- RT04 width = pstdev(close,20)/mean at end index (inclusive)
double RkWidth(const MxBar &b[], const int end_inclusive)
  {
   if(end_inclusive < 19) return(-1.0);
   double m = 0.0;
   for(int i = end_inclusive - 19; i <= end_inclusive; i++) m += b[i].c;
   m /= 20.0;
   if(m <= 0.0) return(-1.0);
   double v = 0.0;
   for(int i = end_inclusive - 19; i <= end_inclusive; i++) v += (b[i].c - m) * (b[i].c - m);
   return(MathSqrt(v / 20.0) / m);
  }

int RkScore(const MxBar &b[], const int n, const double a, const int dir, string &ev)
  {
   int last = n - 1;
   int score = 0;
   ev = "";
   //--- RT02 momentum surge: 3-bar move >= 1.5 ATR and accelerating
   if(last >= 7)
     {
      double now = (b[last].c - b[last - 3].c) / a, before = (b[last - 3].c - b[last - 6].c) / a;
      double acc = now - before;
      if(MathAbs(now) >= 1.5 && (now > 0) == (acc > 0) && ((now > 0) == (dir > 0))) { score++; ev += " RT02"; }
     }
   //--- RT04 compression release: width percentile of the bar before <= CompPct (last 100)
   if(last >= 120)
     {
      double cur = RkWidth(b, last - 1);
      int cnt = 0, le = 0;
      for(int i = last - 100; i <= last - 1; i++)
        {
         double w = RkWidth(b, i);
         if(w < 0.0) continue;
         cnt++;
         if(w <= cur) le++;
        }
      if(cnt > 0 && cur >= 0.0 && (double)le / cnt <= InpRocketCompPct) { score++; ev += " RT04"; }
     }
   //--- RT05 abnormal tick volume vs same-hour median
   if(b[last].v > 0)
     {
      MqlDateTime d0; TimeToStruct(b[last].t, d0);
      long vols[]; int m = 0;
      ArrayResize(vols, 0);
      for(int i = 0; i < last; i++)
        {
         MqlDateTime d; TimeToStruct(b[i].t, d);
         if(d.hour == d0.hour && b[i].v > 0) { m++; ArrayResize(vols, m); vols[m - 1] = b[i].v; }
        }
      if(m >= 5)
        {
         ArraySort(vols);
         double med = (m % 2 == 1) ? (double)vols[m / 2] : 0.5 * (vols[m / 2 - 1] + vols[m / 2]);
         if(med > 0.0 && (double)b[last].v / med >= InpRocketVolMult) { score++; ev += " RT05"; }
        }
     }
   return(score);
  }

bool RocketSignal(const string symbol, string &side, double &entry, double &sl,
                  double &tp, double &spread, double &atr, string &why)
  {
   side = ""; entry = sl = tp = spread = atr = 0.0; why = "";
   ENUM_TIMEFRAMES tf = (InpRocketTF == PERIOD_CURRENT ? (ENUM_TIMEFRAMES)Period() : InpRocketTF);
   MxBar b[];
   int n = MxCopyClosed(symbol, tf, b, 400);
   if(n < 130) { why = "Rocket: fewer than 130 closed bars"; return(false); }
   int last = n - 1;
   if(b[last].t == g_rocket_last_bar) { why = "Rocket: bar already evaluated"; return(false); }
   g_rocket_last_bar = b[last].t;
   double a = MxAtr(b, last, 20);           // ATR20 of bars before the signal bar
   atr = a;
   if(a <= 0.0) { why = "Rocket: missing ATR"; return(false); }
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     { why = "missing: bid/ask"; return(false); }
   spread = tick.ask - tick.bid;

   int dir = 0;
   double stop = 0.0;
   string ev = "";
   //--- mode 1: a pending breakout waits up to 3 bars for a retest of the level
   if(InpRocketEntryMode == 1 && g_rk_pend_side != "")
     {
      int age = 0;
      for(int i = last; i >= 0 && b[i].t > g_rk_pend_bar; i--) age++;
      bool up = (g_rk_pend_side == "buy");
      if(age > 3) g_rk_pend_side = "";
      else if((up && b[last].l <= g_rk_pend_level && b[last].c > g_rk_pend_level) ||
              (!up && b[last].h >= g_rk_pend_level && b[last].c < g_rk_pend_level))
        {
         dir = up ? 1 : -1; stop = g_rk_pend_stop; ev = " retest"; g_rk_pend_side = "";
        }
      else if((up && b[last].c < g_rk_pend_level - a) || (!up && b[last].c > g_rk_pend_level + a))
         g_rk_pend_side = "";   // failed breakout
     }

   if(dir == 0)
     {
      //--- RT01 explosion (required)
      double rng = b[last].h - b[last].l;
      if(rng < InpRocketRangeAtr * a) { why = "Rocket: no range explosion"; return(false); }
      int d = (b[last].c > b[last].o) ? 1 : (b[last].c < b[last].o ? -1 : 0);
      if(d == 0) { why = "Rocket: doji explosion"; return(false); }
      //--- RT03 breakout of the prior box (required)
      int nb = MathMax(5, InpRocketBoxBars);
      double top = b[last - 1].h, bot = b[last - 1].l;
      for(int i = last - nb; i < last; i++) { top = MathMax(top, b[i].h); bot = MathMin(bot, b[i].l); }
      bool brk = (d > 0) ? (b[last].c > top + InpRocketBreakAtr * a) : (b[last].c < bot - InpRocketBreakAtr * a);
      if(!brk) { why = "Rocket: explosion without box breakout"; return(false); }
      //--- RT03 fake-risk: previous bar was a failed breakout of the prior box
      double ptop = b[last - 2].h, pbot = b[last - 2].l;
      for(int i = last - nb - 1; i < last - 1; i++) { ptop = MathMax(ptop, b[i].h); pbot = MathMin(pbot, b[i].l); }
      bool fake = (b[last - 1].h > ptop && b[last - 1].c < ptop) || (b[last - 1].l < pbot && b[last - 1].c > pbot);
      double score = 2.0;   // RT01 + RT03
      ev = " RT01 RT03";
      string ev2;
      score += RkScore(b, n, a, d, ev2);
      ev += ev2;
      if(fake) { score -= 1.0; ev += " -fake"; }
      double e20 = RkEma(b, last, 20);
      if(MathAbs(b[last].c - e20) / a > InpRocketMaxStretchAtr) { score -= 1.5; ev += " -stretch"; }
      if(score < InpRocketMinScore)
        { why = "Rocket: score " + DoubleToString(score, 1) + " <" + DoubleToString(InpRocketMinScore, 1) + ev; return(false); }
      //--- RT10 stop: farther of the last swing (k=2) and 1 ATR from close
      int k = 2;
      double sw = 0.0;
      for(int i = last - 1 - k; i >= k; i--)
        {
         if(d > 0 && MxSwingLow(b, n, i, k))  { sw = b[i].l; break; }
         if(d < 0 && MxSwingHigh(b, n, i, k)) { sw = b[i].h; break; }
        }
      if(d > 0) stop = (sw > 0.0 ? MathMin(sw, b[last].c - a) : b[last].c - 1.5 * a);
      else      stop = (sw > 0.0 ? MathMax(sw, b[last].c + a) : b[last].c + 1.5 * a);
      if(InpRocketEntryMode == 1)
        {
         g_rk_pend_side = (d > 0 ? "buy" : "sell");
         g_rk_pend_level = (d > 0 ? top : bot);
         g_rk_pend_stop = stop;
         g_rk_pend_bar = b[last].t;
         why = "Rocket: breakout armed, waiting for retest" + ev;
         return(false);
        }
      dir = d;
     }
   bool up = (dir > 0);
   entry = up ? tick.ask : tick.bid;
   sl = up ? stop - spread : stop + spread;
   double risk = MathAbs(entry - sl);
   if(risk <= 0.0 || (up && sl >= entry) || (!up && sl <= entry)) { why = "Rocket: invalid stop"; return(false); }
   //--- RT10 cost check: net R:R after spread + 0.05 ATR slippage must stay >= 1.2
   double cost = spread + 0.05 * a;
   double rr = (InpRocketRR * risk - cost) / (risk + cost);
   if(rr < 1.2) { why = "Rocket: net R:R " + DoubleToString(rr, 2) + " after costs"; return(false); }
   tp = up ? entry + InpRocketRR * risk : entry - InpRocketRR * risk;
   side = up ? "buy" : "sell";
   why = "Rocket " + side + ev;
   Print("MolidoRocket: ", symbol, " ", why, " sl ", DoubleToString(sl, _Digits), " tp ", DoubleToString(tp, _Digits));
   return(true);
  }

void RocketStratInit()
  {
   g_rt_rocket = InpUseRocket;
   if(!MQLInfoInteger(MQL_TESTER) && GlobalVariableCheck("Molido.Strat.Rocket"))
      g_rt_rocket = (GlobalVariableGet("Molido.Strat.Rocket") > 0.5);
  }
bool StratUseRocket() { return(g_rt_rocket); }
void StratSetRocket(const bool on)
  {
   g_rt_rocket = on;
   if(!MQLInfoInteger(MQL_TESTER))
      GlobalVariableSet("Molido.Strat.Rocket", on ? 1.0 : 0.0);
  }

#endif

//+------------------------------------------------------------------+
//| MolidoSMC.mqh - Smart Money (SMC) entry strategy, Expert 2.31+.  |
//| Additive: default OFF (InpUseSmartMoney=false). Produces an      |
//| entry candidate only; every candidate still goes through the     |
//| same Risk Brain review, prop guards, lot caps, news filter,      |
//| Expert policy and single-instance lock as the other strategies.  |
//| Closed bars only (no bar 0), so nothing repaints.                |
//| Rules and their status: docs/smc-rocket-fa.md                    |
//+------------------------------------------------------------------+
#ifndef MOLIDO_SMC_MQH
#define MOLIDO_SMC_MQH

input group "Expert 2.31 Smart Money (SMC) - default off"
input bool            InpUseSmartMoney    = false;        // Smart Money strategy (BOS/CHoCH, OB, sweep, FVG)
input ENUM_TIMEFRAMES InpSmcTF            = PERIOD_CURRENT; // SMC entry timeframe (current = chart)
input ENUM_TIMEFRAMES InpSmcHtf           = PERIOD_H1;    // HTF bias timeframe (swing structure)
input int             InpSmcSwingK        = 2;            // swing pivot: k closed bars each side
input int             InpSmcLookback      = 240;          // closed LTF bars scanned
input int             InpSmcSweepMaxAge   = 40;           // sweep must be within this many bars
input int             InpSmcChochMaxBars  = 20;           // CHoCH must follow the sweep within N bars
input int             InpSmcEntryMaxBars  = 30;           // retest must come within N bars of CHoCH
input double          InpSmcEqTolAtr      = 0.10;         // equal highs/lows tolerance, x ATR
input double          InpSmcSlBufferAtr   = 0.10;         // SL buffer beyond OB/sweep, x ATR (+spread)
input double          InpSmcMinRR         = 2.0;          // minimum R for the liquidity target
input bool            InpSmcRequireDiscount = true;       // buys only in discount, sells only in premium
input bool            InpSmcUseFvgZone    = true;         // accept an FVG retest when no OB retest
input bool            InpSmcRocketOnly    = false;        // variant isolation: run only SMC/Rocket (scalper/trend/fibo off)
input bool            InpMxUseScalperFilters = false;     // also apply the scalper session/ADX/ATR%/M15-H1/consensus gate to SMC/Rocket

bool     g_rt_smc        = false;
datetime g_smc_last_zone = 0;   // one filled entry per OB/FVG zone
datetime g_smc_cand_zone = 0;   // last zone offered (committed once a position is open)
bool DemoSymbolOpen(const string symbol);

struct MxBar
  {
   datetime t;
   double   o;
   double   h;
   double   l;
   double   c;
   long     v;
  };

//--- index 0 = oldest, n-1 = last closed bar
int MxCopyClosed(const string symbol, const ENUM_TIMEFRAMES tf, MxBar &bars[], const int want)
  {
   int avail = iBars(symbol, tf);
   int n = want;
   if(avail - 1 < n)
      n = avail - 1;
   if(n < 30)
      return(0);
   ArrayResize(bars, n);
   for(int i = 0; i < n; i++)
     {
      int sh = n - i;
      bars[i].t = iTime(symbol, tf, sh);
      bars[i].o = iOpen(symbol, tf, sh);
      bars[i].h = iHigh(symbol, tf, sh);
      bars[i].l = iLow(symbol, tf, sh);
      bars[i].c = iClose(symbol, tf, sh);
      bars[i].v = iTickVolume(symbol, tf, sh);
      if(bars[i].o <= 0.0 || bars[i].h <= 0.0 || bars[i].l <= 0.0 || bars[i].c <= 0.0 || bars[i].h < bars[i].l)
         return(0);
     }
   return(n);
  }

double MxAtr(const MxBar &bars[], const int end_exclusive, const int period)
  {
   if(end_exclusive < period + 1)
      return(0.0);
   double sum = 0.0;
   for(int i = end_exclusive - period; i < end_exclusive; i++)
     {
      double prev = bars[i - 1].c;
      sum += MathMax(bars[i].h - bars[i].l, MathMax(MathAbs(bars[i].h - prev), MathAbs(bars[i].l - prev)));
     }
   return(sum / period);
  }

//--- confirmed pivot (k bars each side, strictly unique extreme) - same as backend bars.swings
bool MxSwingHigh(const MxBar &b[], const int n, const int i, const int k)
  {
   if(i < k || i + k >= n) return(false);
   for(int j = i - k; j <= i + k; j++)
      if(j != i && b[j].h >= b[i].h) return(false);
   return(true);
  }
bool MxSwingLow(const MxBar &b[], const int n, const int i, const int k)
  {
   if(i < k || i + k >= n) return(false);
   for(int j = i - k; j <= i + k; j++)
      if(j != i && b[j].l <= b[i].l) return(false);
   return(true);
  }

//--- HTF bias from swing structure: +1 HH+HL, -1 LH+LL, 0 range/unknown (backend SM06 rule)
int SmcHtfBias(const string symbol, string &why)
  {
   MxBar b[];
   int n = MxCopyClosed(symbol, InpSmcHtf, b, 150);
   if(n <= 0) { why = "SMC: missing HTF bars"; return(0); }
   int k = MathMax(1, InpSmcSwingK);
   int h1 = -1, h2 = -1, l1 = -1, l2 = -1;  // h1 = last, h2 = previous
   for(int i = n - 1 - k; i >= k; i--)
     {
      if(h2 < 0 && MxSwingHigh(b, n, i, k)) { if(h1 < 0) h1 = i; else h2 = i; }
      if(l2 < 0 && MxSwingLow(b, n, i, k))  { if(l1 < 0) l1 = i; else l2 = i; }
      if(h2 >= 0 && l2 >= 0) break;
     }
   if(h2 < 0 || l2 < 0) { why = "SMC: HTF has fewer than two swings"; return(0); }
   if(b[h1].h > b[h2].h && b[l1].l > b[l2].l) return(1);
   if(b[h1].h < b[h2].h && b[l1].l < b[l2].l) return(-1);
   why = "SMC: HTF structure is a range (no bias)";
   return(0);
  }

//--- is level a liquidity pool for the sweep side? equal lows/highs or the previous day's low/high
bool SmcIsLiquidity(const MxBar &b[], const int n, const int pivot, const bool lows,
                    const double tol, const double pd_level)
  {
   double lvl = lows ? b[pivot].l : b[pivot].h;
   if(pd_level > 0.0 && MathAbs(lvl - pd_level) <= tol)
      return(true);
   int k = MathMax(1, InpSmcSwingK);
   for(int j = pivot - 1; j >= MathMax(k, pivot - 120); j--)
     {
      if(lows && MxSwingLow(b, n, j, k) && MathAbs(b[j].l - lvl) <= tol) return(true);
      if(!lows && MxSwingHigh(b, n, j, k) && MathAbs(b[j].h - lvl) <= tol) return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Bullish sequence (mirror for bearish):                           |
//| 1 sweep: bar s wicks below a liquidity low (equal lows or PDL)   |
//|   and closes back above it                                       |
//| 2 CHoCH: a later bar c closes above the last swing high before c |
//| 3 zone: OB = last bearish candle in [s, c); else unfilled bull   |
//|   FVG formed in (s, c]                                           |
//| 4 entry: last closed bar trades into the zone and closes above   |
//|   the zone low; price in discount of the sweep-low..CHoCH range  |
//| SL beyond min(OB low, sweep low) - buffer; TP = nearest opposite |
//| liquidity (swing high / PDH) with reward >= MinRR, else MinRR.   |
//+------------------------------------------------------------------+
bool SmcFindSetup(const MxBar &b[], const int n, const bool bull, const double atr,
                  const double pd_level, double &zlo, double &zhi, double &stop_ref,
                  double &range_top, double &range_bot, datetime &zone_t, string &why)
  {
   int k = MathMax(1, InpSmcSwingK);
   double tol = InpSmcEqTolAtr * atr;
   int last = n - 1;
   int smin = MathMax(k + 2, last - InpSmcSweepMaxAge);
   for(int s = last - 1; s >= smin; s--)
     {
      //--- 1 sweep of a confirmed pivot that is a liquidity pool
      int piv = -1;
      for(int j = s - k - 1; j >= MathMax(k, s - 120); j--)
        {
         if(bull && MxSwingLow(b, n, j, k))   { piv = j; break; }
         if(!bull && MxSwingHigh(b, n, j, k)) { piv = j; break; }
        }
      if(piv < 0) continue;
      double lvl = bull ? b[piv].l : b[piv].h;
      bool swept = bull ? (b[s].l < lvl && b[s].c > lvl) : (b[s].h > lvl && b[s].c < lvl);
      if(!swept)
        {
         //--- also accept a sweep of the previous day's level
         if(pd_level > 0.0)
            swept = bull ? (b[s].l < pd_level && b[s].c > pd_level) : (b[s].h > pd_level && b[s].c < pd_level);
         if(!swept) continue;
        }
      else if(!SmcIsLiquidity(b, n, piv, bull, tol, pd_level))
         continue;
      //--- 2 CHoCH after the sweep: close beyond the last opposite swing before c
      int c = -1;
      double broke = 0.0;
      for(int i = s + 1; i <= MathMin(last, s + InpSmcChochMaxBars); i++)
        {
         int sp = -1;
         for(int j = i - k - 1; j >= MathMax(k, s - 60); j--)
           {
            if(bull && MxSwingHigh(b, n, j, k))   { sp = j; break; }
            if(!bull && MxSwingLow(b, n, j, k))   { sp = j; break; }
           }
         if(sp < 0) continue;
         double brk = bull ? b[sp].h : b[sp].l;
         if((bull && b[i].c > brk) || (!bull && b[i].c < brk)) { c = i; broke = brk; break; }
        }
      if(c < 0 || c >= last) continue;
      if(last - c > InpSmcEntryMaxBars) continue;
      //--- 3 zone: order block = last opposite candle in [s, c)
      int ob = -1;
      for(int i = c - 1; i >= s; i--)
         if((bull && b[i].c < b[i].o) || (!bull && b[i].c > b[i].o)) { ob = i; break; }
      zlo = 0.0; zhi = 0.0; zone_t = 0;
      if(ob >= 0) { zlo = b[ob].l; zhi = b[ob].h; zone_t = b[ob].t; }
      //--- mitigation: a close through the far edge after c invalidates the OB
      if(ob >= 0)
         for(int i = c + 1; i < last; i++)
            if((bull && b[i].c < zlo) || (!bull && b[i].c > zhi)) { ob = -1; zone_t = 0; break; }
      bool touched = false;
      if(ob >= 0)
         touched = bull ? (b[last].l <= zhi && b[last].c > zlo) : (b[last].h >= zlo && b[last].c < zhi);
      if(!touched && InpSmcUseFvgZone)
        {
         for(int i = MathMin(c + 1, last - 1); i >= s + 2; i--)
           {
            double glo = 0.0, ghi = 0.0;
            if(bull && b[i - 2].h < b[i].l)  { glo = b[i - 2].h; ghi = b[i].l; }
            if(!bull && b[i - 2].l > b[i].h) { glo = b[i].h;     ghi = b[i - 2].l; }
            if(ghi <= glo) continue;
            bool filled = false;
            for(int j = i + 1; j < last; j++)
               if((bull && b[j].l <= glo) || (!bull && b[j].h >= ghi)) { filled = true; break; }
            if(filled) continue;
            if(bull ? (b[last].l <= ghi && b[last].c > glo) : (b[last].h >= glo && b[last].c < ghi))
              { zlo = glo; zhi = ghi; zone_t = b[i].t; touched = true; break; }
           }
        }
      if(!touched) continue;
      //--- dealing range = sweep extreme .. CHoCH swing (for premium/discount)
      double ext = bull ? b[s].l : b[s].h;
      for(int i = s; i <= c; i++)
        {
         if(bull && b[i].h > broke) broke = b[i].h;
         if(!bull && b[i].l < broke) broke = b[i].l;
        }
      range_bot = bull ? ext : broke;
      range_top = bull ? broke : ext;
      stop_ref = bull ? MathMin(ext, zlo) : MathMax(ext, zhi);
      return(true);
     }
   why = bull ? "SMC: no bullish sweep+CHoCH+OB/FVG retest" : "SMC: no bearish sweep+CHoCH+OB/FVG retest";
   return(false);
  }

bool SmcSignal(const string symbol, string &side, double &entry, double &sl,
               double &tp, double &spread, double &atr, string &why)
  {
   side = ""; entry = sl = tp = spread = atr = 0.0; why = "";
   if(g_smc_cand_zone != 0 && DemoSymbolOpen(symbol))
     { g_smc_last_zone = g_smc_cand_zone; g_smc_cand_zone = 0; }
   ENUM_TIMEFRAMES tf = (InpSmcTF == PERIOD_CURRENT ? (ENUM_TIMEFRAMES)Period() : InpSmcTF);
   MxBar b[];
   int n = MxCopyClosed(symbol, tf, b, MathMax(80, InpSmcLookback));
   if(n <= 0) { why = "SMC: missing closed bars"; return(false); }
   atr = MxAtr(b, n, 14);
   if(atr <= 0.0) { why = "SMC: missing ATR"; return(false); }
   int bias = SmcHtfBias(symbol, why);
   if(bias == 0) return(false);
   bool bull = (bias > 0);
   double pdh = iHigh(symbol, PERIOD_D1, 1), pdl = iLow(symbol, PERIOD_D1, 1);
   double zlo, zhi, stop_ref, rtop, rbot;
   datetime zt;
   if(!SmcFindSetup(b, n, bull, atr, bull ? pdl : pdh, zlo, zhi, stop_ref, rtop, rbot, zt, why))
      return(false);
   if(zt == g_smc_last_zone) { why = "SMC: zone already traded"; return(false); }
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     { why = "missing: bid/ask"; return(false); }
   spread = tick.ask - tick.bid;
   entry = bull ? tick.ask : tick.bid;
   if(InpSmcRequireDiscount && rtop > rbot)
     {
      double pos = (entry - rbot) / (rtop - rbot);
      if(bull && pos > 0.5)  { why = "SMC: buy not in discount"; return(false); }
      if(!bull && pos < 0.5) { why = "SMC: sell not in premium"; return(false); }
     }
   double buf = InpSmcSlBufferAtr * atr + spread;
   sl = bull ? stop_ref - buf : stop_ref + buf;
   double risk = MathAbs(entry - sl);
   if(risk <= 0.0 || (bull && sl >= entry) || (!bull && sl <= entry))
     { why = "SMC: invalid stop"; return(false); }
   //--- TP: nearest opposite liquidity giving >= MinRR (swing pivots + previous day level)
   double need = InpSmcMinRR * risk;
   double best = 0.0;
   int k = MathMax(1, InpSmcSwingK);
   for(int i = n - 1 - k; i >= k; i--)
     {
      if(bull && MxSwingHigh(b, n, i, k) && b[i].h - entry >= need && (best == 0.0 || b[i].h < best)) best = b[i].h;
      if(!bull && MxSwingLow(b, n, i, k) && entry - b[i].l >= need && (best == 0.0 || b[i].l > best)) best = b[i].l;
     }
   double pdo = bull ? pdh : pdl;
   if(pdo > 0.0 && ((bull && pdo - entry >= need) || (!bull && entry - pdo >= need)))
      if(best == 0.0 || (bull && pdo < best) || (!bull && pdo > best)) best = pdo;
   if(best == 0.0)
      best = bull ? entry + need : entry - need;   // no pool far enough: fixed MinRR
   tp = best;
   side = bull ? "buy" : "sell";
   g_smc_cand_zone = zt;
   why = "SMC " + side + ": sweep+CHoCH, zone " + DoubleToString(zlo, _Digits) + "-" + DoubleToString(zhi, _Digits);
   Print("MolidoSMC: ", symbol, " ", why, " sl ", DoubleToString(sl, _Digits), " tp ", DoubleToString(tp, _Digits),
         " R ", DoubleToString(MathAbs(tp - entry) / risk, 2));
   return(true);
  }

void SmcStratInit()
  {
   g_rt_smc = InpUseSmartMoney;
   if(!MQLInfoInteger(MQL_TESTER) && GlobalVariableCheck("Molido.Strat.SMC"))
      g_rt_smc = (GlobalVariableGet("Molido.Strat.SMC") > 0.5);
  }
bool StratUseSmc() { return(g_rt_smc); }
void StratSetSmc(const bool on)
  {
   g_rt_smc = on;
   if(!MQLInfoInteger(MQL_TESTER))
      GlobalVariableSet("Molido.Strat.SMC", on ? 1.0 : 0.0);
  }

#endif

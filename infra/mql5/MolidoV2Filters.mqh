//+------------------------------------------------------------------+
//| MolidoV2Filters.mqh - SP2L + FVG confirmation (Expert 2.30).     |
//| Port of TESTED detection from agents/stage-23-v2-engines.        |
//| Entry/SL/TP rules stay RESEARCH and are not used as entries.     |
//| Closed bars only (no bar 0) so the filters do not repaint.       |
//+------------------------------------------------------------------+
#ifndef MOLIDO_V2_FILTERS_MQH
#define MOLIDO_V2_FILTERS_MQH

#define V2_LOOKBACK          80
#define V2_ATR_PERIOD        14
#define V2_SP2L_MIN_BARS     3
#define V2_SP2L_MIN_ATR      1.8   // RESEARCH default from the Python engine
#define V2_SP2L_BODY_RATIO   0.5   // RESEARCH default
#define V2_SPIKE_ATR_MULT    2.5   // RESEARCH default; detection is TESTED

struct V2Bar
  {
   double o;
   double h;
   double l;
   double c;
  };

int V2CopyClosed(const string symbol, const ENUM_TIMEFRAMES tf, V2Bar &bars[], const int want)
  {
   int avail = iBars(symbol, tf);
   //--- exclude the forming bar (shift 0)
   int n = want;
   if(avail - 1 < n)
      n = avail - 1;
   if(n < V2_SP2L_MIN_BARS + 6)
      return(0);
   ArrayResize(bars, n);
   for(int i = 0; i < n; i++)
     {
      int sh = n - i; //  n..1  (oldest .. last closed)
      bars[i].o = iOpen(symbol, tf, sh);
      bars[i].h = iHigh(symbol, tf, sh);
      bars[i].l = iLow(symbol, tf, sh);
      bars[i].c = iClose(symbol, tf, sh);
      if(bars[i].o <= 0.0 || bars[i].h <= 0.0 || bars[i].l <= 0.0 || bars[i].c <= 0.0 || bars[i].h < bars[i].l)
         return(0);
     }
   return(n);
  }

double V2AtrAt(const V2Bar &bars[], const int end_exclusive, const int period)
  {
   if(end_exclusive < period + 1)
      return(0.0);
   double sum = 0.0;
   int start = end_exclusive - period;
   for(int i = start; i < end_exclusive; i++)
     {
      double prev = bars[i - 1].c;
      double tr = MathMax(bars[i].h - bars[i].l,
                          MathMax(MathAbs(bars[i].h - prev), MathAbs(bars[i].l - prev)));
      sum += tr;
     }
   return(sum / period);
  }

double V2BodyRatio(const V2Bar &bars[], const int start, const int end, const bool bull)
  {
   double signed_b = 0.0, total = 0.0;
   for(int i = start; i <= end; i++)
     {
      double rng = bars[i].h - bars[i].l;
      if(rng < 1e-12)
         rng = 1e-12;
      total += rng;
      double body = bars[i].c - bars[i].o;
      if(bull)
         signed_b += MathMax(body, 0.0);
      else
         signed_b += MathMax(-body, 0.0);
     }
   return(total > 0.0 ? signed_b / total : 0.0);
  }

bool V2PGap(const V2Bar &prev, const V2Bar &bar, const bool bull)
  {
   // RESEARCH default measurement, required by the TESTED "P-Gap required" rule.
   if(bull)
      return(bar.o > prev.h);
   return(bar.o < prev.l);
  }

bool V2DetectSp2l(const V2Bar &bars[], const int n, const string side, string &why)
  {
   why = "";
   if(n < V2_SP2L_MIN_BARS + 2)
     {
      why = "SP2L: not enough closed bars";
      return(false);
     }
   double last_atr = V2AtrAt(bars, n, V2_ATR_PERIOD);
   if(last_atr <= 0.0)
     {
      why = "SP2L: missing ATR";
      return(false);
     }
   int minb = V2_SP2L_MIN_BARS;
   bool want_buy = (side == "buy");
   for(int end = n - 1; end >= minb - 1; end--)
     {
      int start = end - minb + 1;
      double up = bars[end].c - bars[start].o;
      bool bull = (up > 0.0);
      double extreme = (bull ? bars[start].h : bars[start].l);
      for(int i = start; i <= end; i++)
        {
         if(bull && bars[i].h > extreme) extreme = bars[i].h;
         if(!bull && bars[i].l < extreme) extreme = bars[i].l;
        }
      double origin = (bull ? bars[start].l : bars[start].h);
      double length = MathAbs(extreme - origin);
      if(length / last_atr < V2_SP2L_MIN_ATR)
         continue;
      if(V2BodyRatio(bars, start, end, bull) < V2_SP2L_BODY_RATIO)
         continue;
      bool mixed = false;
      for(int i = start; i <= end; i++)
        {
         if(bull && bars[i].c < bars[i].o) { mixed = true; break; }
         if(!bull && bars[i].c > bars[i].o) { mixed = true; break; }
        }
      if(mixed)
         continue;
      int gap_i = -1;
      for(int i = start; i <= end; i++)
        {
         if(i == 0)
            continue;
         if(V2PGap(bars[i - 1], bars[i], bull))
           {
            gap_i = i;
            break;
           }
        }
      if(gap_i < 0)
        {
         why = "SP2L: spike has no P-Gap (invalid)";
         return(false); // newest qualifying run is invalid — do not skip to an older one
        }
      // second-leg correction (TESTED): bull takes prior low, bear takes prior high
      int leg2 = -1;
      for(int i = end + 1; i < n; i++)
        {
         if(bull && bars[i].l < bars[i - 1].l) { leg2 = i; break; }
         if(!bull && bars[i].h > bars[i - 1].h) { leg2 = i; break; }
        }
      if(leg2 < 0)
        {
         why = "SP2L: waiting for second-leg correction";
         return(false);
        }
      // invalidation (TESTED): opposite close through the spike origin
      for(int i = end + 1; i < n; i++)
        {
         if(bull && bars[i].c < origin)
           {
            why = "SP2L: structure invalidated";
            return(false);
           }
         if(!bull && bars[i].c > origin)
           {
            why = "SP2L: structure invalidated";
            return(false);
           }
        }
      if(want_buy != bull)
        {
         why = "SP2L: against HL/LH structure";
         return(false);
        }
      return(true);
     }
   why = "SP2L: no qualifying spike on closed bars";
   return(false);
  }

bool V2FvgReacting(const V2Bar &bars[], const int n, const string side, string &why)
  {
   why = "";
   if(n < 5)
     {
      why = "FVG: not enough closed bars";
      return(false);
     }
   bool want_buy = (side == "buy");
   // last closed bar is n-1 — used for the "reacting from" test
   V2Bar last = bars[n - 1];
   for(int i = n - 1; i >= 2; i--)
     {
      bool bull_gap = (bars[i - 2].h < bars[i].l);
      bool bear_gap = (bars[i - 2].l > bars[i].h);
      if(!bull_gap && !bear_gap)
         continue;
      if(want_buy && !bull_gap)
         continue;
      if(!want_buy && !bear_gap)
         continue;
      double lo, hi;
      if(bull_gap)
        { lo = bars[i - 2].h; hi = bars[i].l; }
      else
        { lo = bars[i].h; hi = bars[i - 2].l; }
      // SM04 mitigation: later closed bars after formed_at trade through the near side
      bool mitigated = false;
      for(int j = i + 1; j < n; j++)
        {
         if(bull_gap && bars[j].l <= lo) { mitigated = true; break; }
         if(bear_gap && bars[j].h >= hi) { mitigated = true; break; }
        }
      if(mitigated)
         continue;
      // reacting: last closed bar overlaps the unmitigated zone
      if(last.l <= hi && last.h >= lo)
         return(true);
     }
   why = "FVG: no unmitigated zone in trade direction";
   return(false);
  }

bool V2Sp2lConfirms(const string symbol, const string side, string &why)
  {
   if(!InpUseSP2LFilter)
      return(true);
   V2Bar bars[];
   int n = V2CopyClosed(symbol, PERIOD_M15, bars, V2_LOOKBACK);
   if(n <= 0)
     {
      why = "SP2L: missing closed M15 bars";
      return(false);
     }
   return(V2DetectSp2l(bars, n, side, why));
  }

bool V2FvgConfirms(const string symbol, const string side, string &why)
  {
   if(!InpUseFVGFilter)
      return(true);
   V2Bar bars[];
   int n = V2CopyClosed(symbol, PERIOD_M15, bars, V2_LOOKBACK);
   if(n <= 0)
     {
      why = "FVG: missing closed M15 bars";
      return(false);
     }
   return(V2FvgReacting(bars, n, side, why));
  }

bool V2ConfirmationAllow(const string symbol, const string side, string &why)
  {
   why = "";
   if(!V2Sp2lConfirms(symbol, side, why))
      return(false);
   if(!V2FvgConfirms(symbol, side, why))
      return(false);
   return(true);
  }

#endif

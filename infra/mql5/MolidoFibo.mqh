//+------------------------------------------------------------------+
//| MolidoFibo.mqh - Fibonacci retracement entries in the H1 trend.  |
//| Swings, 38.2/50/61.8 retracements, SL beyond 78.6 or the swing,  |
//| TP at 127.2/161.8 extensions. Off by default until a walk-forward|
//| out-of-sample test is positive.                                  |
//+------------------------------------------------------------------+
#ifndef MOLIDO_FIBO_MQH
#define MOLIDO_FIBO_MQH

bool FiboLastSwings(const string symbol, const ENUM_TIMEFRAMES tf,
                    const int strength, const int lookback,
                    double &swing_high, double &swing_low)
  {
   swing_high = 0.0;
   swing_low = 0.0;
   int bars = iBars(symbol, tf);
   int str = strength;
   if(str < 2) str = 2;
   if(str > 8) str = 8;
   int depth = lookback;
   if(depth < 20) depth = 20;
   if(depth > 200) depth = 200;
   int last = MathMin(bars - str - 2, depth + str);
   if(last < str + 2)
      return(false);
   bool got_h = false, got_l = false;
   for(int i = str + 1; i <= last; i++)
     {
      double h = iHigh(symbol, tf, i);
      double l = iLow(symbol, tf, i);
      if(h <= 0.0 || l <= 0.0)
         continue;
      bool is_high = true, is_low = true;
      for(int k = 1; k <= str; k++)
        {
         if(iHigh(symbol, tf, i - k) >= h || iHigh(symbol, tf, i + k) > h)
            is_high = false;
         if(iLow(symbol, tf, i - k) <= l || iLow(symbol, tf, i + k) < l)
            is_low = false;
        }
      if(is_high && !got_h)
        {
         swing_high = h;
         got_h = true;
        }
      if(is_low && !got_l)
        {
         swing_low = l;
         got_l = true;
        }
      if(got_h && got_l)
         break;
     }
   return(got_h && got_l && swing_high > swing_low);
  }

int FiboH1Trend(const string symbol)
  {
   double e20 = DemoEma(symbol, PERIOD_H1, 20, 1);
   double e50 = DemoEma(symbol, PERIOD_H1, 50, 1);
   if(e20 <= 0.0 || e50 <= 0.0)
      return(0);
   if(e20 > e50)
      return(1);
   if(e20 < e50)
      return(-1);
   return(0);
  }

bool DemoFiboSignal(const string symbol, string &side, double &entry, double &sl,
                    double &tp, double &spread, double &atr, string &why)
  {
   side = "";
   entry = sl = tp = spread = atr = 0.0;
   why = "";
   int trend = FiboH1Trend(symbol);
   if(trend == 0)
     {
      why = "fibo: no H1 trend";
      return(false);
     }
   double sh, slw;
   if(!FiboLastSwings(symbol, FiboSwingTF, FiboSwingStrength, FiboLookbackBars, sh, slw))
     {
      why = "fibo: no confirmed swing";
      return(false);
     }
   double range = sh - slw;
   if(range <= 0.0)
     {
      why = "fibo: empty swing";
      return(false);
     }
   atr = DemoAtr(symbol, FiboSwingTF, DEMO_ATR_PERIOD);
   if(atr <= 0.0)
      atr = range * 0.1;
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     {
      why = "fibo: missing bid/ask";
      return(false);
     }
   spread = tick.ask - tick.bid;
   double close1 = iClose(symbol, FiboSwingTF, 1);
   double low1 = iLow(symbol, FiboSwingTF, 1);
   double high1 = iHigh(symbol, FiboSwingTF, 1);
   if(close1 <= 0.0 || low1 <= 0.0 || high1 <= 0.0)
     {
      why = "fibo: missing bar";
      return(false);
     }
   double tol = MathMax(spread, 0.12 * atr);
   //--- Retracements measured from the impulsive swing.
   double r382, r50, r618, r786, ext127, ext161, swing_sl;
   if(trend > 0)
     {
      r382 = sh - 0.382 * range;
      r50  = sh - 0.500 * range;
      r618 = sh - 0.618 * range;
      r786 = sh - 0.786 * range;
      ext127 = slw + 1.272 * range;
      ext161 = slw + 1.618 * range;
      swing_sl = slw;
      //--- SL beyond 78.6 or the swing (the further side).
      sl = MathMin(r786, swing_sl) - 0.15 * atr;
      entry = tick.ask;
      bool hit = false;
      string lvl = "";
      if(FiboUse618 && low1 <= r618 + tol && close1 >= r618 - tol && close1 > low1)
        { hit = true; lvl = "61.8"; }
      else if(FiboUse50 && low1 <= r50 + tol && close1 >= r50 - tol && close1 > low1)
        { hit = true; lvl = "50"; }
      else if(FiboUse382 && low1 <= r382 + tol && close1 >= r382 - tol && close1 > low1)
        { hit = true; lvl = "38.2"; }
      if(!hit)
        {
         why = "fibo: no retracement touch in H1 uptrend";
         return(false);
        }
      if(entry <= sl || ext161 <= entry)
        {
         why = "fibo: invalid long levels";
         return(false);
        }
      side = "buy";
      tp = ext161;
      why = "fibo long " + lvl + " -> 161.8 (127.2 mid)";
      return(true);
     }
   r382 = slw + 0.382 * range;
   r50  = slw + 0.500 * range;
   r618 = slw + 0.618 * range;
   r786 = slw + 0.786 * range;
   ext127 = sh - 0.272 * range;
   ext161 = sh - 0.618 * range;
   swing_sl = sh;
   sl = MathMax(r786, swing_sl) + 0.15 * atr;
   entry = tick.bid;
   bool hit = false;
   string lvl = "";
   if(FiboUse618 && high1 >= r618 - tol && close1 <= r618 + tol && close1 < high1)
     { hit = true; lvl = "61.8"; }
   else if(FiboUse50 && high1 >= r50 - tol && close1 <= r50 + tol && close1 < high1)
     { hit = true; lvl = "50"; }
   else if(FiboUse382 && high1 >= r382 - tol && close1 <= r382 + tol && close1 < high1)
     { hit = true; lvl = "38.2"; }
   if(!hit)
     {
      why = "fibo: no retracement touch in H1 downtrend";
      return(false);
     }
   if(sl <= entry || ext161 >= entry)
     {
      why = "fibo: invalid short levels";
      return(false);
     }
   side = "sell";
   tp = ext161;
   why = "fibo short " + lvl + " -> 161.8 (127.2 mid)";
   return(true);
  }

#endif

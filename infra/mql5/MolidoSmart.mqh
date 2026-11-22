//+------------------------------------------------------------------+
//| MolidoSmart.mqh - regime, session, trend, manage, cooldown,      |
//| and server-consensus veto (fail-safe: never loosens a local      |
//| block or a hard cap). Demo scalper only.                         |
//+------------------------------------------------------------------+
#ifndef MOLIDO_SMART_MQH
#define MOLIDO_SMART_MQH

#define SMART_ATR_LOOKBACK  100
#define SMART_ADX_PERIOD_D  14

double   g_smart_atr_pct    = -1.0;
double   g_smart_adx        = -1.0;
int      g_smart_strength   = 0;
int      g_smart_cool_left  = 0;
string   g_smart_session    = "—";
string   g_smart_trend      = "—";
string   g_smart_cons       = "—";
string   g_smart_block      = "";
datetime g_smart_cached_at  = 0;
string   g_smart_cached_sym = "";

double SmartScaleClamp(const double value, const double lo, const double hi)
  {
   if(value < lo)
      return(lo);
   if(value > hi)
      return(hi);
   return(value);
  }

int SmartAtrPctMin()
  {
   return((int)SmartScaleClamp(AtrPctMin, 0, 90));
  }

int SmartAtrPctMax()
  {
   int hi = (int)SmartScaleClamp(AtrPctMax, 10, 100);
   int lo = SmartAtrPctMin();
   if(hi < lo)
      hi = lo;
   return(hi);
  }

int SmartAdxMin()
  {
   return((int)SmartScaleClamp(AdxMin, 0, 50));
  }

int SmartAdxPeriod()
  {
   int p = AdxPeriod;
   if(p < 5)
      p = 5;
   if(p > 50)
      p = 50;
   return(p);
  }

int SmartCooldownMinutes()
  {
   int m = CooldownMinutes;
   if(m < 0)
      m = 0;
   if(m > 240)
      m = 240;
   return(m);
  }

double SmartBeAtr()
  {
   return(SmartScaleClamp(BeAtrMult, 0.3, 5.0));
  }

double SmartTrailStart()
  {
   return(SmartScaleClamp(TrailStartAtr, 0.5, 8.0));
  }

double SmartTrailAtr()
  {
   return(SmartScaleClamp(TrailAtrMult, 0.3, 5.0));
  }

double SmartAtrAt(const string symbol, const ENUM_TIMEFRAMES tf,
                  const int period, const int shift)
  {
   if(period <= 0 || shift < 1)
      return(0.0);
   double sum = 0.0;
   for(int i = shift; i < shift + period; i++)
     {
      double high = iHigh(symbol, tf, i);
      double low  = iLow(symbol, tf, i);
      double prev = iClose(symbol, tf, i + 1);
      if(high <= 0.0 || low <= 0.0 || prev <= 0.0 || high < low)
         return(0.0);
      double tr = high - low;
      double up = MathAbs(high - prev);
      double dn = MathAbs(low - prev);
      if(up > tr)
         tr = up;
      if(dn > tr)
         tr = dn;
      sum += tr;
     }
   return(sum / period);
  }

double SmartAtrPercentile(const string symbol, const ENUM_TIMEFRAMES tf)
  {
   double current = SmartAtrAt(symbol, tf, DEMO_ATR_PERIOD, 1);
   if(current <= 0.0)
      return(-1.0);
   int have = 0;
   int below = 0;
   int max_n = SMART_ATR_LOOKBACK;
   int bars = Bars(symbol, tf);
   if(bars < DEMO_ATR_PERIOD + 32)
      return(-1.0);
   int last = bars - DEMO_ATR_PERIOD - 2;
   if(last > max_n)
      last = max_n;
   for(int sh = 1; sh <= last; sh++)
     {
      double a = SmartAtrAt(symbol, tf, DEMO_ATR_PERIOD, sh);
      if(a <= 0.0)
         continue;
      have++;
      if(a <= current)
         below++;
     }
   if(have < 30)
      return(-1.0);
   return(100.0 * below / have);
  }

double SmartAdx(const string symbol, const ENUM_TIMEFRAMES tf, const int period)
  {
   int need = period * 3;
   int bars = Bars(symbol, tf);
   if(bars < need + 3)
      return(-1.0);

   double atr = 0.0, pdm_s = 0.0, mdm_s = 0.0;
   for(int i = need; i > need - period; i--)
     {
      double h = iHigh(symbol, tf, i);
      double l = iLow(symbol, tf, i);
      double c1 = iClose(symbol, tf, i + 1);
      double ph = iHigh(symbol, tf, i + 1);
      double pl = iLow(symbol, tf, i + 1);
      if(h <= 0.0 || l <= 0.0 || c1 <= 0.0 || ph <= 0.0 || pl <= 0.0)
         return(-1.0);
      double tr = h - l;
      double a = MathAbs(h - c1);
      double b = MathAbs(l - c1);
      if(a > tr) tr = a;
      if(b > tr) tr = b;
      double up = h - ph;
      double dn = pl - l;
      atr   += tr;
      pdm_s += (up > dn && up > 0.0) ? up : 0.0;
      mdm_s += (dn > up && dn > 0.0) ? dn : 0.0;
     }

   double adx = 0.0;
   int adx_n = 0;
   for(int i = need - period; i >= 1; i--)
     {
      double h = iHigh(symbol, tf, i);
      double l = iLow(symbol, tf, i);
      double c1 = iClose(symbol, tf, i + 1);
      double ph = iHigh(symbol, tf, i + 1);
      double pl = iLow(symbol, tf, i + 1);
      if(h <= 0.0 || l <= 0.0 || c1 <= 0.0 || ph <= 0.0 || pl <= 0.0)
         return(-1.0);
      double tr = h - l;
      double a = MathAbs(h - c1);
      double b = MathAbs(l - c1);
      if(a > tr) tr = a;
      if(b > tr) tr = b;
      double up = h - ph;
      double dn = pl - l;
      double pdm = (up > dn && up > 0.0) ? up : 0.0;
      double mdm = (dn > up && dn > 0.0) ? dn : 0.0;
      atr   = atr - atr / period + tr;
      pdm_s = pdm_s - pdm_s / period + pdm;
      mdm_s = mdm_s - mdm_s / period + mdm;
      double pdi = (atr > 0.0) ? 100.0 * pdm_s / atr : 0.0;
      double mdi = (atr > 0.0) ? 100.0 * mdm_s / atr : 0.0;
      double den = pdi + mdi;
      double dx  = (den > 0.0) ? 100.0 * MathAbs(pdi - mdi) / den : 0.0;
      if(adx_n < period)
        {
         adx += dx;
         adx_n++;
         if(adx_n == period)
            adx = adx / period;
        }
      else
         adx = (adx * (period - 1) + dx) / period;
     }
   return(adx);
  }

bool SmartInSession(string &label)
  {
   datetime gmt = TimeGMT();
   MqlDateTime dt;
   TimeToStruct(gmt, dt);
   if(dt.day_of_week == 0 || dt.day_of_week == 6)
     {
      label = "weekend";
      return(false);
     }
   int h = dt.hour;
   int lo_open  = (int)SmartScaleClamp(LondonOpenHourGMT, 0, 23);
   int lo_close = (int)SmartScaleClamp(LondonCloseHourGMT, 1, 24);
   int ny_open  = (int)SmartScaleClamp(NewYorkOpenHourGMT, 0, 23);
   int ny_close = (int)SmartScaleClamp(NewYorkCloseHourGMT, 1, 24);
   bool london = (h >= lo_open && h < lo_close);
   bool ny     = (h >= ny_open && h < ny_close);
   if(london && ny)
      label = "London+NY";
   else if(london)
      label = "London";
   else if(ny)
      label = "New York";
   else
      label = "off-session";
   return(london || ny);
  }

bool SmartTrendAlign(const string symbol, const string side, string &label)
  {
   double m15_e20 = DemoEma(symbol, PERIOD_M15, 20, 1);
   double m15_e50 = DemoEma(symbol, PERIOD_M15, 50, 1);
   double h1_e20  = DemoEma(symbol, PERIOD_H1, 20, 1);
   double h1_e50  = DemoEma(symbol, PERIOD_H1, 50, 1);
   if(m15_e20 <= 0.0 || m15_e50 <= 0.0 || h1_e20 <= 0.0 || h1_e50 <= 0.0)
     {
      label = "trend n/a";
      return(false);
     }
   string m15 = (m15_e20 > m15_e50) ? "M15^" : "M15v";
   string h1  = (h1_e20 > h1_e50) ? "H1^" : "H1v";
   label = m15 + " " + h1;
   if(side == "buy")
      return(m15_e20 > m15_e50 && h1_e20 > h1_e50);
   if(side == "sell")
      return(m15_e20 < m15_e50 && h1_e20 < h1_e50);
   return(false);
  }

datetime SmartLastLossAt()
  {
   static datetime cached = 0;
   static datetime cached_at = 0;
   datetime now = TimeCurrent();
   if(cached_at == now)
      return(cached);
   cached_at = now;
   cached = 0;
   datetime from = now - 5 * 86400;
   if(from < 0)
      from = 0;
   if(!HistorySelect(from, now + 1))
      return(0);
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)HistoryDealGetInteger(ticket, DEAL_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      if((int)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;
      if(HistoryDealGetDouble(ticket, DEAL_PROFIT) >= 0.0)
         continue;
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      if(t > cached)
         cached = t;
     }
   return(cached);
  }

int SmartCooldownLeftSec()
  {
   int minutes = SmartCooldownMinutes();
   if(minutes <= 0)
      return(0);
   datetime loss = SmartLastLossAt();
   if(loss <= 0)
      return(0);
   int left = minutes * 60 - (int)(TimeCurrent() - loss);
   if(left < 0)
      left = 0;
   return(left);
  }

string SmartNormSide(string raw)
  {
   StringToLower(raw);
   StringTrimLeft(raw);
   StringTrimRight(raw);
   return(raw);
  }

bool SmartConsensusRow(const string symbol, string &side, datetime &until)
  {
   side = "";
   until = 0;
   if(StringLen(g_consensus_csv) <= 0)
      return(false);
   string rows[];
   int n = StringSplit(g_consensus_csv, ';', rows);
   string want = symbol;
   StringToUpper(want);
   for(int i = 0; i < n; i++)
     {
      string row = rows[i];
      StringTrimLeft(row);
      StringTrimRight(row);
      if(StringLen(row) <= 0)
         continue;
      int c1 = StringFind(row, ":");
      if(c1 <= 0)
         continue;
      int c2 = StringFind(row, ":", c1 + 1);
      if(c2 <= c1)
         continue;
      string name = StringSubstr(row, 0, c1);
      string dir  = StringSubstr(row, c1 + 1, c2 - c1 - 1);
      string when = StringSubstr(row, c2 + 1);
      StringTrimLeft(name); StringTrimRight(name);
      StringTrimLeft(dir);  StringTrimRight(dir);
      StringTrimRight(when); StringTrimLeft(when);
      StringToUpper(name);
      if(name != want && StringFind(want, name) != 0 && StringFind(name, want) != 0)
         continue;
      dir = SmartNormSide(dir);
      if(dir != "buy" && dir != "sell" && dir != "wait" && dir != "block")
         continue;
      datetime exp = 0;
      bool digits = true;
      for(int k = 0; k < StringLen(when); k++)
        {
         ushort ch = StringGetCharacter(when, k);
         if(ch < '0' || ch > '9')
           {
            digits = false;
            break;
           }
        }
      if(digits && StringLen(when) >= 9)
         exp = (datetime)StringToInteger(when);
      else
         exp = StringToTime(when);
      side = dir;
      until = exp;
      return(true);
     }
   return(false);
  }

bool SmartConsensusAllows(const string symbol, const string side, string &why, string &label)
  {
   why = "";
   string server = "";
   datetime until = 0;
   bool have = SmartConsensusRow(symbol, server, until);
   datetime now = TimeGMT();
   if(!have)
     {
      label = RequireServerConsensus ? "required" : "—";
      if(RequireServerConsensus)
        {
         why = "missing server consensus";
         return(false);
        }
      return(true);
     }
   bool fresh = (until <= 0 || now <= until);
   if(!fresh)
     {
      label = "stale";
      if(RequireServerConsensus)
        {
         why = "stale server consensus";
         return(false);
        }
      return(true);
     }
   if(server == "wait" || server == "block")
     {
      label = "veto";
      why = "server consensus veto";
      return(false);
     }
   if(server != side)
     {
      label = "veto " + server;
      why = "server consensus disagrees (" + server + ")";
      return(false);
     }
   label = server;
   return(true);
  }

void DemoSmartRefresh(const string symbol)
  {
   datetime now = TimeCurrent();
   if(g_smart_cached_sym == symbol && g_smart_cached_at == now && now > 0)
      return;
   g_smart_cached_sym = symbol;
   g_smart_cached_at = now;
   g_smart_block = "";

   string sess = "—";
   bool in_sess = SmartInSession(sess);
   g_smart_session = sess;

   static string   s_bar_sym = "";
   static datetime s_bar = 0;
   static double   s_m15_e20 = 0.0, s_m15_e50 = 0.0, s_h1_e20 = 0.0, s_h1_e50 = 0.0;
   datetime bar = iTime(symbol, ScalperTF, 0);
   if(s_bar_sym != symbol || s_bar != bar || g_smart_atr_pct < 0.0)
     {
      s_bar_sym = symbol;
      s_bar = bar;
      g_smart_atr_pct = SmartAtrPercentile(symbol, ScalperTF);
      g_smart_adx = SmartAdx(symbol, ScalperTF, SmartAdxPeriod());
      s_m15_e20 = DemoEma(symbol, PERIOD_M15, 20, 1);
      s_m15_e50 = DemoEma(symbol, PERIOD_M15, 50, 1);
      s_h1_e20  = DemoEma(symbol, PERIOD_H1, 20, 1);
      s_h1_e50  = DemoEma(symbol, PERIOD_H1, 50, 1);
     }
   double m15_e20 = s_m15_e20;
   double m15_e50 = s_m15_e50;
   double h1_e20  = s_h1_e20;
   double h1_e50  = s_h1_e50;
   string trend = "trend n/a";
   if(m15_e20 > 0.0 && m15_e50 > 0.0 && h1_e20 > 0.0 && h1_e50 > 0.0)
     {
      string m15 = (m15_e20 > m15_e50) ? "M15^" : "M15v";
      string h1  = (h1_e20 > h1_e50) ? "H1^" : "H1v";
      trend = m15 + " " + h1;
     }
   g_smart_trend = trend;

   g_smart_cool_left = SmartCooldownLeftSec();

   string cons_why, cons_label;
   SmartConsensusAllows(symbol, "buy", cons_why, cons_label);
   //--- Label only (side-neutral); the real veto uses the local side at entry.
   string cs = "";
   datetime until = 0;
   if(SmartConsensusRow(symbol, cs, until))
     {
      if(until > 0 && TimeGMT() > until)
         g_smart_cons = "stale";
      else
         g_smart_cons = cs;
     }
   else
      g_smart_cons = RequireServerConsensus ? "required" : "—";

   int pts = 0;
   int maxp = 0;
   if(UseSessionFilter)
     {
      maxp += 20;
      if(in_sess)
         pts += 20;
     }
   if(UseRegimeFilter)
     {
      maxp += 20;
      if(g_smart_atr_pct >= SmartAtrPctMin() && g_smart_atr_pct <= SmartAtrPctMax())
         pts += 10;
      if(g_smart_adx >= SmartAdxMin())
         pts += 10;
     }
   if(UseTrendConfirm)
     {
      maxp += 20;
      if(m15_e20 > 0.0 && h1_e20 > 0.0 &&
         ((m15_e20 > m15_e50 && h1_e20 > h1_e50) ||
          (m15_e20 < m15_e50 && h1_e20 < h1_e50)))
         pts += 20;
     }
   maxp += 20;
   if(g_smart_cool_left <= 0)
      pts += 20;
   maxp += 20;
   if(g_smart_cons != "veto" && g_smart_cons != "stale" && g_smart_cons != "required"
      && g_smart_cons != "wait" && g_smart_cons != "block")
      pts += 20;
   if(maxp <= 0)
      maxp = 1;
   g_smart_strength = (int)MathRound(100.0 * pts / maxp);
   if(g_smart_strength < 0)
      g_smart_strength = 0;
   if(g_smart_strength > 100)
      g_smart_strength = 100;
  }

bool DemoSmartAllowEntry(const string symbol, const string side, string &why)
  {
   why = "";
   DemoSmartRefresh(symbol);

   if(UseSessionFilter)
     {
      string label;
      if(!SmartInSession(label))
        {
         why = "session filter (" + label + ")";
         g_smart_block = why;
         return(false);
        }
     }

   if(UseRegimeFilter)
     {
      if(g_smart_atr_pct < 0.0 || g_smart_adx < 0.0)
        {
         why = "missing: ATR percentile or ADX";
         g_smart_block = why;
         return(false);
        }
      if(g_smart_atr_pct < SmartAtrPctMin() || g_smart_atr_pct > SmartAtrPctMax())
        {
         why = "ATR percentile " + DoubleToString(g_smart_atr_pct, 0) +
               "% outside " + IntegerToString(SmartAtrPctMin()) +
               "-" + IntegerToString(SmartAtrPctMax());
         g_smart_block = why;
         return(false);
        }
      if(g_smart_adx < SmartAdxMin())
        {
         why = "ADX " + DoubleToString(g_smart_adx, 1) +
               " below " + IntegerToString(SmartAdxMin());
         g_smart_block = why;
         return(false);
        }
     }

   if(UseTrendConfirm)
     {
      string label;
      if(!SmartTrendAlign(symbol, side, label))
        {
         why = "M15/H1 trend not confirmed (" + label + ")";
         g_smart_block = why;
         return(false);
        }
     }

   int cool = SmartCooldownLeftSec();
   g_smart_cool_left = cool;
   if(cool > 0)
     {
      why = "cooldown after loss (" + IntegerToString((cool + 59) / 60) + "m left)";
      g_smart_block = why;
      return(false);
     }

   string cons_label;
   if(!SmartConsensusAllows(symbol, side, why, cons_label))
     {
      g_smart_cons = cons_label;
      g_smart_block = why;
      return(false);
     }
   g_smart_cons = cons_label;
   return(true);
  }

bool SmartAmendSl(const string symbol, const ulong ticket,
                  const double new_sl, const double tp)
  {
   if(new_sl <= 0.0)
      return(false);
   if(!DemoAccountOk())
      return(false);
   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action   = TRADE_ACTION_SLTP;
   req.symbol   = symbol;
   req.position = ticket;
   req.sl       = new_sl;
   req.tp       = tp;
   if(!OrderSend(req, res))
      return(false);
   return(res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_PLACED
          || res.retcode == TRADE_RETCODE_NO_CHANGES);
  }

void DemoManagePositions()
  {
   if(!EnableDemoScalper)
      return;
#ifdef MOLIDO_EXPERT_UI
   ExpertManageExits();
   bool allow_be = UseBreakEven && ExpertAllowBreakEven();
   bool allow_tr = UseTrailing && ExpertAllowTrailing();
#else
   bool allow_be = UseBreakEven;
   bool allow_tr = UseTrailing;
#endif
   if(!allow_be && !allow_tr)
      return;
   if(!DemoAccountOk())
      return;
   static uint last_ms = 0;
   uint now = GetTickCount();
   if(last_ms != 0 && (now - last_ms) < 400)
      return;
   last_ms = now;

   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      string symbol = PositionGetString(POSITION_SYMBOL);
      long kind = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      if(open <= 0.0)
         continue;
      double atr = DemoAtr(symbol, ScalperTF, DEMO_ATR_PERIOD);
      if(atr <= 0.0)
         continue;
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      if(bid <= 0.0 || ask <= 0.0)
         continue;
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      int stops  = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      int freeze = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      if(point <= 0.0)
         continue;
      double min_dist = (stops > freeze ? stops : freeze) * point;
      bool is_buy = (kind == POSITION_TYPE_BUY);
      double price = is_buy ? bid : ask;
      double profit = is_buy ? (bid - open) : (open - ask);
      double new_sl = sl;
      if(allow_be && profit >= SmartBeAtr() * atr)
        {
         double be = open;
         if(is_buy)
           {
            if(new_sl <= 0.0 || be > new_sl)
               new_sl = be;
           }
         else
           {
            if(new_sl <= 0.0 || be < new_sl)
               new_sl = be;
           }
        }
      if(allow_tr && profit >= SmartTrailStart() * atr)
        {
         double trail = is_buy ? (bid - SmartTrailAtr() * atr)
                               : (ask + SmartTrailAtr() * atr);
         if(is_buy)
           {
            if(new_sl <= 0.0 || trail > new_sl)
               new_sl = trail;
           }
         else
           {
            if(new_sl <= 0.0 || trail < new_sl)
               new_sl = trail;
           }
        }
      if(is_buy)
        {
         if(price - new_sl < min_dist)
            new_sl = price - min_dist;
         if(new_sl <= sl + point * 0.4)
            continue;
        }
      else
        {
         if(new_sl - price < min_dist)
            new_sl = price + min_dist;
         if(sl > 0.0 && new_sl >= sl - point * 0.4)
            continue;
         if(new_sl <= 0.0)
            continue;
        }
      new_sl = NormalizeDouble(new_sl, digits);
      if(new_sl <= 0.0)
         continue;
      if(MathAbs(new_sl - sl) < point * 0.5)
         continue;
      if(SmartAmendSl(symbol, ticket, new_sl, tp))
         Print("MolidoScalper: managed SL on ", symbol, " ticket ", ticket,
               " -> ", DoubleToString(new_sl, digits));
     }
  }

string DemoSmartLineRegime()
  {
   string atr = (g_smart_atr_pct >= 0.0)
                ? ("ATR " + DoubleToString(g_smart_atr_pct, 0) + "%")
                : "ATR —";
   string adx = (g_smart_adx >= 0.0)
                ? ("ADX " + DoubleToString(g_smart_adx, 0))
                : "ADX —";
   return(atr + "   " + adx + "   " + g_smart_session);
  }

string DemoSmartLineTrend()
  {
   string cool = "cool off";
   if(g_smart_cool_left > 0)
      cool = "cool " + IntegerToString((g_smart_cool_left + 59) / 60) + "m";
   string manage = "";
   if(UseBreakEven)
      manage += "BE";
   if(UseTrailing)
      manage += (StringLen(manage) > 0 ? "+TRL" : "TRL");
   if(StringLen(manage) == 0)
      manage = "manage off";
   return(g_smart_trend + "   " + manage + "   " + cool + "   cons " + g_smart_cons);
  }

int DemoSignalStrength()
  {
   return(g_smart_strength);
  }

#endif

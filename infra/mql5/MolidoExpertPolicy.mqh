//+------------------------------------------------------------------+
//| MolidoExpertPolicy.mqh - Expert 2.30/2.31 safety (demo only).    |
//| Tightens Expert behaviour; never loosens shared Risk Brain caps. |
//| Included only when MOLIDO_EXPERT_UI is defined.                  |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_POLICY_MQH
#define MOLIDO_EXPERT_POLICY_MQH

#define EX_GV_LOCK       "Molido.Expert.LockLogin"
#define EX_GV_LOCK_CHART "Molido.Expert.LockChart"
#define EX_GV_LOCK_HB    "Molido.Expert.LockHb"
#define EX_GV_SAFE_AT    "Molido.Expert.SafeStopAt"

double DemoAtr(const string symbol, const ENUM_TIMEFRAMES tf, const int period);
double DemoEma(const string symbol, const ENUM_TIMEFRAMES tf, const int period, const int shift);
bool   SmartAmendSl(const string symbol, const ulong ticket, const double sl, const double tp);

string   g_ex_lots_symbol = "";
bool     g_ex_lock_owner  = false;
bool     g_ex_standby     = false;
bool     g_ex_hist_ok     = true;

double ExpertSafeModeFactor();
bool   ExpertQualityAllow(const string symbol, const string side, string &why);
bool   V2ConfirmationAllow(const string symbol, const string side, string &why);

void ExpertSetLotsSymbol(const string symbol)
  {
   g_ex_lots_symbol = symbol;
  }

bool ExpertIsMetal(const string symbol)
  {
   string u = symbol;
   StringToUpper(u);
   if(StringFind(u, "XAU") >= 0)
      return(true);
   if(StringFind(u, "XAG") >= 0)
      return(true);
   return(false);
  }

bool ExpertIsIndex(const string symbol)
  {
   string u = symbol;
   StringToUpper(u);
   if(StringFind(u, "CASH") >= 0)
      return(true);
   if(StringFind(u, "US30") >= 0 || StringFind(u, "US500") >= 0 || StringFind(u, "USTECH") >= 0)
      return(true);
   if(StringFind(u, "DE40") >= 0 || StringFind(u, "JP225") >= 0 || StringFind(u, "UK100") >= 0)
      return(true);
   if(StringFind(u, "NAS") >= 0 || StringFind(u, "SPX") >= 0 || StringFind(u, "DAX") >= 0)
      return(true);
   return(false);
  }

bool ExpertAllowPartialTP()
  {
   return(ExpertUsePartialTP);
  }

bool ExpertAllowTrailing()
  {
   return(ExpertUseTrailing);
  }

bool ExpertAllowBreakEven()
  {
   return(ExpertUseBreakEven);
  }

bool ExpertInstanceMayTrade()
  {
   return(!g_ex_standby);
  }

//--- 2.31: in the Strategy Tester TimeGMT() returns simulated server time,
//--- so the London window was applied in server hours there but in GMT live.
//--- With ExpertTesterClockFix the tester derives GMT from server time using
//--- the broker offset and DST rule, so tester and live use the same window.
int ExpertNthSundayMday(const int year, const int mon, const int nth)
  {
   MqlDateTime d;
   d.year = year; d.mon = mon; d.day = 1; d.hour = 0; d.min = 0; d.sec = 0;
   datetime t = StructToTime(d);
   TimeToStruct(t, d);
   int first = 1 + ((7 - d.day_of_week) % 7);
   return(first + 7 * (nth - 1));
  }

int ExpertLastSundayMday(const int year, const int mon)
  {
   int day = ExpertNthSundayMday(year, mon, 1);
   int dim = 31;
   if(mon == 4 || mon == 6 || mon == 9 || mon == 11) dim = 30;
   while(day + 7 <= dim) day += 7;
   return(day);
  }

bool ExpertTesterDstOn(const datetime server_t)
  {
   MqlDateTime d;
   TimeToStruct(server_t, d);
   int key = d.mon * 100 + d.day;
   if(ExpertTesterDstMode == 1)
     {
      int a = 300 + ExpertNthSundayMday(d.year, 3, 2);
      int b = 1100 + ExpertNthSundayMday(d.year, 11, 1);
      return(key >= a && key < b);
     }
   if(ExpertTesterDstMode == 2)
     {
      int a = 300 + ExpertLastSundayMday(d.year, 3);
      int b = 1000 + ExpertLastSundayMday(d.year, 10);
      return(key >= a && key < b);
     }
   return(false);
  }

datetime ExpertGmtNow()
  {
   if(ExpertTesterClockFix && (bool)MQLInfoInteger(MQL_TESTER))
     {
      datetime srv = TimeCurrent();
      int off = ExpertTesterGmtOffset + (ExpertTesterDstOn(srv) ? 1 : 0);
      return(srv - off * 3600);
     }
   return(TimeGMT());
  }

int ExpertGmtHour()
  {
   MqlDateTime g;
   TimeToStruct(ExpertGmtNow(), g);
   return(g.hour);
  }

bool ExpertMetalsInLondon(const string symbol)
  {
   if(!ExpertBlockMetalsInLondon)
      return(false);
   if(!ExpertIsMetal(symbol))
      return(false);
   int h = ExpertGmtHour();
   int open_h = ExpertMetalLondonOpenGMT;
   int close_h = ExpertMetalLondonCloseGMT;
   if(open_h == close_h)
      return(false);
   if(open_h < close_h)
      return(h >= open_h && h < close_h);
   return(h >= open_h || h < close_h);
  }

//--- Tightens risk%; never raises it above the Risk Brain value already chosen.
double ExpertTightenRiskPct(const string symbol, const double risk_pct)
  {
   double v = risk_pct;
   if(v <= 0.0)
      return(v);
   if(ExpertIsMetal(symbol) && ExpertMetalRiskPct > 0.0 && ExpertMetalRiskPct < v)
      v = ExpertMetalRiskPct;
   if(ExpertMaxLossPct > 0.0 && ExpertMaxLossPct < v)
      v = ExpertMaxLossPct;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance > 0.0 && ExpertMaxLossUsd > 0.0)
     {
      double usd_pct = 100.0 * ExpertMaxLossUsd / balance;
      if(usd_pct < v)
         v = usd_pct;
     }
   if(v < 0.01)
      v = 0.01;
   return(NormalizeDouble(v, 4));
  }

double ExpertMaxLotsForSymbol(const string symbol)
  {
   double cap = ExpertMaxLots;
   if(cap <= 0.0)
      cap = 0.50;
   if(ExpertIsMetal(symbol))
     {
      if(ExpertMaxLotsMetal > 0.0 && ExpertMaxLotsMetal < cap)
         cap = ExpertMaxLotsMetal;
     }
   else if(ExpertIsIndex(symbol))
     {
      if(ExpertMaxLotsIndex > 0.0 && ExpertMaxLotsIndex < cap)
         cap = ExpertMaxLotsIndex;
     }
   else
     {
      if(ExpertMaxLotsFx > 0.0 && ExpertMaxLotsFx < cap)
         cap = ExpertMaxLotsFx;
     }
   return(cap);
  }

double ExpertTightenMaxLots(const double shared_cap)
  {
   double cap = shared_cap;
   if(ExpertMaxLots > 0.0 && ExpertMaxLots < cap)
      cap = ExpertMaxLots;
   return(cap);
  }

double ExpertClampLots(const string symbol, const double lots,
                       const double sl_distance,
                       const double tick_size, const double tick_value,
                       const double lot_step, const double min_lot)
  {
   if(lots <= 0.0)
      return(0.0);
   string sym = symbol;
   if(StringLen(sym) == 0)
      sym = g_ex_lots_symbol;
   if(StringLen(sym) == 0)
      sym = _Symbol;
   double out = lots;
   double cap = ExpertMaxLotsForSymbol(sym);
   if(out > cap)
      out = cap;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double money = 0.0;
   if(balance > 0.0)
     {
      money = balance * (ExpertTightenRiskPct(sym, 0.5) / 100.0);
      if(ExpertMaxLossUsd > 0.0 && (money <= 0.0 || ExpertMaxLossUsd < money))
         money = ExpertMaxLossUsd;
     }
   if(money > 0.0 && sl_distance > 0.0 && tick_size > 0.0 && tick_value > 0.0 && lot_step > 0.0)
     {
      double ticks = sl_distance / tick_size;
      if(ticks > 0.0)
        {
         double raw = money / (ticks * tick_value);
         if(raw < out)
            out = raw;
        }
     }
   if(lot_step > 0.0)
      out = MathFloor(out / lot_step + 1e-12) * lot_step;
   out = NormalizeDouble(out, 8);
   if(min_lot > 0.0 && out + 1e-12 < min_lot)
      return(0.0);
   if(out > lots)
      out = lots;
   return(out);
  }

void ExpertEnsureMinTp(const string side, const double entry, const double sl, double &tp)
  {
   if(entry <= 0.0 || sl <= 0.0 || ExpertMinTpR <= 0.0)
      return;
   double risk = MathAbs(entry - sl);
   if(risk <= 0.0)
      return;
   double want = ExpertMinTpR * risk;
   if(side == "sell")
     {
      double need = entry - want;
      if(need > 0.0 && (tp <= 0.0 || tp > need + 1e-12))
         tp = need;
     }
   else
     {
      double need = entry + want;
      if(tp <= 0.0 || tp < need - 1e-12)
         tp = need;
     }
  }


int ExpertDayKey(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return(dt.year * 10000 + dt.mon * 100 + dt.day);
  }

datetime ExpertNextDayStart(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   dt.hour = 0;
   dt.min  = 0;
   dt.sec  = 0;
   return(StructToTime(dt) + 86400);
  }

double ExpertAtrAverage(const string symbol, const ENUM_TIMEFRAMES tf, const int period, const int bars)
  {
   int n = (bars > 2 ? bars : 50);
   int per = (period > 0 ? period : 14);
   double sum = 0.0;
   int got = 0;
   for(int shift = 1; shift <= n; shift++)
     {
      double acc = 0.0;
      bool ok = true;
      for(int i = 0; i < per; i++)
        {
         double h    = iHigh(symbol, tf, shift + i);
         double l    = iLow(symbol, tf, shift + i);
         double prev = iClose(symbol, tf, shift + i + 1);
         if(h <= 0.0 || l <= 0.0 || prev <= 0.0 || h < l)
           {
            ok = false;
            break;
           }
         acc += MathMax(h - l, MathMax(MathAbs(h - prev), MathAbs(l - prev)));
        }
      if(!ok)
         continue;
      sum += acc / per;
      got++;
     }
   if(got <= 0)
      return(0.0);
   return(sum / got);
  }

bool ExpertTrendAligned(const string symbol, const string side, string &why)
  {
   if(!ExpertUseTrendFilter)
      return(true);
   int fast = (ExpertTrendFastEma > 1 ? ExpertTrendFastEma : 50);
   int slow = (ExpertTrendSlowEma > fast ? ExpertTrendSlowEma : 200);
   double h1f = DemoEma(symbol, PERIOD_H1, fast, 1);
   double h1s = DemoEma(symbol, PERIOD_H1, slow, 1);
   double h4f = DemoEma(symbol, PERIOD_H4, fast, 1);
   double h4s = DemoEma(symbol, PERIOD_H4, slow, 1);
   if(h1f <= 0.0 || h1s <= 0.0 || h4f <= 0.0 || h4s <= 0.0)
     {
      why = "missing H1/H4 EMA trend";
      return(false);
     }
   bool h1_up = (h1f > h1s);
   bool h4_up = (h4f > h4s);
   bool want_buy = (side == "buy");
   if(ExpertTrendRequireBoth)
     {
      if(want_buy && !(h1_up && h4_up))
        {
         why = "against H1/H4 EMA" + IntegerToString(fast) + "/" + IntegerToString(slow) + " trend";
         return(false);
        }
      if(!want_buy && (h1_up || h4_up))
        {
         why = "against H1/H4 EMA" + IntegerToString(fast) + "/" + IntegerToString(slow) + " trend";
         return(false);
        }
     }
   else
     {
      // at least one TF must agree, and the other must not contradict if both available
      bool agree = (want_buy && (h1_up || h4_up)) || (!want_buy && (!h1_up || !h4_up));
      if(!agree)
        {
         why = "against H1/H4 EMA trend";
         return(false);
        }
     }
   return(true);
  }

bool ExpertSpreadAtrOk(const string symbol, string &why)
  {
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     {
      why = "missing bid/ask for spread filter";
      return(false);
     }
   double spread = tick.ask - tick.bid;
   double atr = DemoAtr(symbol, PERIOD_M15, 14);
   if(ExpertUseSpreadFilter)
     {
      if(atr > 0.0 && ExpertMaxSpreadAtrFrac > 0.0 && spread > ExpertMaxSpreadAtrFrac * atr)
        {
         why = "spread " + DoubleToString(spread, 5) + " > " +
               DoubleToString(ExpertMaxSpreadAtrFrac * 100.0, 0) + "% ATR";
         return(false);
        }
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      if(ExpertMaxSpreadPts > 0 && point > 0.0 && (spread / point) > ExpertMaxSpreadPts)
        {
         why = "spread wider than " + IntegerToString(ExpertMaxSpreadPts) + " points";
         return(false);
        }
     }
   if(ExpertUseAtrFilter)
     {
      if(atr <= 0.0)
        {
         why = "missing ATR for volatility filter";
         return(false);
        }
      int bars = (ExpertAtrAvgBars > 5 ? ExpertAtrAvgBars : 50);
      double avg = ExpertAtrAverage(symbol, PERIOD_M15, 14, bars);
      if(avg > 0.0)
        {
         if(ExpertAtrMinMult > 0.0 && atr < ExpertAtrMinMult * avg)
           {
            why = "ATR too low vs average";
            return(false);
           }
         if(ExpertAtrMaxMult > 0.0 && atr > ExpertAtrMaxMult * avg)
           {
            why = "ATR too high vs average";
            return(false);
           }
        }
     }
   return(true);
  }

bool ExpertCurrencyMatch(const string symbol, const string currency)
  {
   if(StringLen(currency) == 0)
      return(false);
   string u = currency;
   StringToUpper(u);
   string base = SymbolInfoString(symbol, SYMBOL_CURRENCY_BASE);
   string prof = SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT);
   StringToUpper(base);
   StringToUpper(prof);
   if(u == base || u == prof)
      return(true);
   string sym = symbol;
   StringToUpper(sym);
   if(StringFind(sym, u) >= 0)
      return(true);
   if((StringFind(sym, "XAU") >= 0 || StringFind(sym, "XAG") >= 0) && u == "USD")
      return(true);
   return(false);
  }

bool ExpertNewsBlocked(const string symbol, string &why)
  {
   if(!ExpertUseNewsFilter)
      return(false);
   int before = (ExpertNewsMinsBefore > 0 ? ExpertNewsMinsBefore : 30);
   int after  = (ExpertNewsMinsAfter > 0 ? ExpertNewsMinsAfter : 30);
   datetime now = TimeGMT();
   datetime from = now - after * 60;
   datetime to   = now + before * 60;
   MqlCalendarValue values[];
   int got = CalendarValueHistory(values, from, to, NULL, NULL);
   if(got <= 0)
      return(false); // fail open when the calendar feed is empty or unavailable
   for(int i = 0; i < got; i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      if(ev.importance < CALENDAR_IMPORTANCE_HIGH)
         continue;
      MqlCalendarCountry co;
      string cur = "";
      if(CalendarCountryById(ev.country_id, co))
         cur = co.currency;
      if(!ExpertCurrencyMatch(symbol, cur))
         continue;
      datetime et = values[i].time;
      if(et >= from && et <= to)
        {
         why = "high-impact " + cur + " news within +/- " +
               IntegerToString(MathMax(before, after)) + " min";
         return(true);
        }
     }
   return(false);
  }

bool ExpertQualityAllow(const string symbol, const string side, string &why)
  {
   why = "";
   if(!ExpertSpreadAtrOk(symbol, why))
      return(false);
   if(!ExpertTrendAligned(symbol, side, why))
      return(false);
   if(ExpertNewsBlocked(symbol, why))
      return(false);
   if(!V2ConfirmationAllow(symbol, side, why))
      return(false);
   return(true);
  }

void ExpertManageExits()
  {
   if(!ExpertUseBeAtR && !ExpertUseAtrTrail)
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
      if(ticket == 0 || !PositionSelectByTicket(ticket))
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
      bool is_buy = (kind == POSITION_TYPE_BUY);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      if(bid <= 0.0 || ask <= 0.0)
         continue;
      double price = is_buy ? bid : ask;
      double profit = is_buy ? (bid - open) : (open - ask);
      double risk = 0.0;
      if(is_buy && sl > 0.0 && sl < open)
         risk = open - sl;
      else if(!is_buy && sl > 0.0 && sl > open)
         risk = sl - open;
      else if(tp > 0.0 && ExpertMinTpR > 0.0)
         risk = MathAbs(tp - open) / ExpertMinTpR;
      else
        {
         double atr0 = DemoAtr(symbol, PERIOD_M15, 14);
         if(atr0 > 0.0)
            risk = 1.5 * atr0;
        }
      if(risk <= 0.0)
         continue;
      double r_now = profit / risk;
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      int stops  = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      int freeze = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      if(point <= 0.0)
         continue;
      double min_dist = (stops > freeze ? stops : freeze) * point;
      double new_sl = sl;
      if(ExpertUseBeAtR && ExpertBreakEvenR > 0.0 && r_now >= ExpertBreakEvenR)
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
      if(ExpertUseAtrTrail && ExpertTrailStartR > 0.0 && r_now >= ExpertTrailStartR)
        {
         double atr = DemoAtr(symbol, PERIOD_M15, 14);
         double mult = (ExpertTrailAtrMult > 0.1 ? ExpertTrailAtrMult : 1.0);
         if(atr > 0.0)
           {
            double trail = is_buy ? (bid - mult * atr) : (ask + mult * atr);
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
        }
      // never move SL through / onto the still-active TP
      if(tp > 0.0)
        {
         if(is_buy && new_sl >= tp - point)
            new_sl = sl;
         if(!is_buy && new_sl <= tp + point)
            new_sl = sl;
        }
      if(is_buy)
        {
         if(price - new_sl < min_dist)
            new_sl = price - min_dist;
         if(new_sl <= sl + point * 0.4)
            continue;
         if(tp > 0.0 && new_sl >= tp - point)
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
         if(tp > 0.0 && new_sl <= tp + point)
            continue;
        }
      new_sl = NormalizeDouble(new_sl, digits);
      if(new_sl <= 0.0)
         continue;
      if(MathAbs(new_sl - sl) < point * 0.5)
         continue;
      if(SmartAmendSl(symbol, ticket, new_sl, tp))
         Print("MolidoExpert 2.30: managed SL on ", symbol, " ticket ", ticket,
               " R=", DoubleToString(r_now, 2), " -> ", DoubleToString(new_sl, digits),
               " TP kept ", DoubleToString(tp, digits));
     }
  }

bool ExpertPolicyAllow(const string symbol, const string side,
                       const double entry, const double sl, const double tp,
                       string &why)
  {
   why = "";
   if(g_ex_standby)
     {
      why = "standby: another Molido_Expert instance owns this account";
      return(false);
     }
   if(ExpertMetalsInLondon(symbol))
     {
      why = "metals blocked during London session (GMT " +
            IntegerToString(ExpertMetalLondonOpenGMT) + "-" +
            IntegerToString(ExpertMetalLondonCloseGMT) + ")";
      return(false);
     }
   if(!ExpertQualityAllow(symbol, side, why))
      return(false);
   if(entry > 0.0 && sl > 0.0 && tp > 0.0 && ExpertMinTpR > 0.0)
     {
      double risk = MathAbs(entry - sl);
      double reward = MathAbs(tp - entry);
      if(risk > 0.0 && reward + 1e-12 < ExpertMinTpR * risk)
        {
         why = "Expert min TP " + DoubleToString(reward / risk, 2) +
               "R < " + DoubleToString(ExpertMinTpR, 2) + "R";
         return(false);
        }
     }
   return(true);
  }

//--- Consecutive losses counted only on the current server date, so
//--- safe mode actually lifts at the next trading day.
int ExpertTodayLossStreak()
  {
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);
   dt.hour = 0;
   dt.min  = 0;
   dt.sec  = 0;
   datetime day0 = StructToTime(dt);
   if(!HistorySelect(day0, now + 1))
     {
      g_ex_hist_ok = false;
      return(0);
     }
   g_ex_hist_ok = true;
   int n = 0;
   int total = HistoryDealsTotal();
   for(int i = total - 1; i >= 0; i--)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)HistoryDealGetInteger(ticket, DEAL_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      if((int)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      if(t < day0)
         break;
      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                   + HistoryDealGetDouble(ticket, DEAL_SWAP)
                   + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      if(pnl >= 0.0)
         break;
      n++;
     }
   return(n);
  }

datetime ExpertSafeModeClearsAt()
  {
   datetime now = TimeCurrent();
   datetime next_day = ExpertNextDayStart(now);
   datetime from_cd = 0;
   if(GlobalVariableCheck(EX_GV_SAFE_AT) && ExpertSafeModeCooldownHours > 0)
     {
      datetime at = (datetime)GlobalVariableGet(EX_GV_SAFE_AT);
      if(at > 0)
         from_cd = at + ExpertSafeModeCooldownHours * 3600;
     }
   if(from_cd > now && from_cd < next_day)
      return(from_cd);
   return(next_day);
  }

void ExpertSafeModeClearLock()
  {
   if(GlobalVariableCheck(EX_GV_SAFE_AT))
      GlobalVariableDel(EX_GV_SAFE_AT);
  }

bool ExpertSafeModeStopped()
  {
   int stop_after = SafeModeStopAfter;
   if(stop_after <= 0)
     {
      ExpertSafeModeClearLock();
      return(false);
     }
   datetime now = TimeCurrent();
   int today = ExpertDayKey(now);
   datetime stop_at = 0;
   if(GlobalVariableCheck(EX_GV_SAFE_AT))
      stop_at = (datetime)GlobalVariableGet(EX_GV_SAFE_AT);
   if(stop_at > 0)
     {
      bool expired = (ExpertDayKey(stop_at) < today);
      if(ExpertSafeModeCooldownHours > 0 && now >= stop_at + ExpertSafeModeCooldownHours * 3600)
         expired = true;
      if(expired)
        {
         ExpertSafeModeClearLock();
         stop_at = 0;
        }
     }
   int n = ExpertTodayLossStreak();
   if(n >= stop_after)
     {
      if(stop_at <= 0)
         GlobalVariableSet(EX_GV_SAFE_AT, (double)now);
      return(true);
     }
   // History failed on a day we already engaged: keep the stop rather than silently lifting it.
   if(!g_ex_hist_ok && stop_at > 0 && ExpertDayKey(stop_at) == today)
      return(true);
   if(stop_at > 0)
      ExpertSafeModeClearLock();
   return(false);
  }

int ExpertSafeModeState()
  {
   if(ExpertSafeModeStopped())
      return(2);
   if(ExpertSafeModeFactor() < 1.0)
      return(1);
   return(0);
  }

string ExpertSafeModeText()
  {
   int n = ExpertTodayLossStreak();
   if(ExpertSafeModeStopped())
      return("STOP " + IntegerToString(n) + "L until " +
             TimeToString(ExpertSafeModeClearsAt(), TIME_DATE | TIME_MINUTES));
   if(ExpertSafeModeFactor() < 1.0)
      return("REDUCE " + IntegerToString(n) + "L x" + DoubleToString(ExpertSafeModeFactor(), 2));
   if(n > 0)
      return(IntegerToString(n) + "L today — on");
   return("Safe mode off");
  }

double ExpertSafeModeFactor()
  {
   if(ExpertSafeModeStopped())
      return(0.0);
   int reduce_after = SafeModeReduceAfter;
   if(reduce_after <= 0)
      return(1.0);
   if(ExpertTodayLossStreak() >= reduce_after)
     {
      double f = SafeModeReduceFactor;
      if(f < 0.1) f = 0.1;
      if(f > 1.0) f = 1.0;
      return(f);
     }
   return(1.0);
  }

void ExpertInstanceHeartbeat()
  {
   if(!g_ex_lock_owner)
      return;
   GlobalVariableSet(EX_GV_LOCK_HB, (double)TimeLocal());
  }

void ExpertInstanceRelease()
  {
   if(!g_ex_lock_owner)
      return;
   if(GlobalVariableCheck(EX_GV_LOCK_CHART) &&
      (long)GlobalVariableGet(EX_GV_LOCK_CHART) == ChartID())
     {
      GlobalVariableDel(EX_GV_LOCK);
      GlobalVariableDel(EX_GV_LOCK_CHART);
      GlobalVariableDel(EX_GV_LOCK_HB);
     }
   g_ex_lock_owner = false;
  }

bool ExpertInstanceOnInit()
  {
   g_ex_standby = false;
   g_ex_lock_owner = false;
   if(!ExpertSingleInstance)
      return(true);
   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION))
      return(true);
   long chart = ChartID();
   if(GlobalVariableCheck(EX_GV_LOCK_CHART))
     {
      long other = (long)GlobalVariableGet(EX_GV_LOCK_CHART);
      datetime hb = (datetime)GlobalVariableGet(EX_GV_LOCK_HB);
      if(other != 0 && other != chart && hb > 0 && (TimeLocal() - hb) < 90)
        {
         g_ex_standby = true;
         Print("MolidoExpert 2.30: standby — another instance already owns login ",
               AccountInfoInteger(ACCOUNT_LOGIN), " chart ", other,
               ". This chart will not place orders.");
         return(true);
        }
     }
   GlobalVariableSet(EX_GV_LOCK, (double)AccountInfoInteger(ACCOUNT_LOGIN));
   GlobalVariableSet(EX_GV_LOCK_CHART, (double)chart);
   GlobalVariableSet(EX_GV_LOCK_HB, (double)TimeLocal());
   g_ex_lock_owner = true;
   Print("MolidoExpert 2.30: single-instance lock acquired on chart ", chart,
         " metal risk=", DoubleToString(ExpertMetalRiskPct, 2),
         "% max loss $", DoubleToString(ExpertMaxLossUsd, 0),
         " max lots=", DoubleToString(ExpertMaxLots, 2),
         " partialTP=", (ExpertUsePartialTP ? "on" : "off"),
         " trailing=", (ExpertUseTrailing ? "on" : "off"),
         " minTP=", DoubleToString(ExpertMinTpR, 2), "R",
         " London metal block=", (ExpertBlockMetalsInLondon ? "on" : "off"),
         " trend=", (ExpertUseTrendFilter ? "on" : "off"),
         " spread/ATR=", (ExpertUseSpreadFilter || ExpertUseAtrFilter ? "on" : "off"),
         " news=", (ExpertUseNewsFilter ? "on" : "off"),
         " BE@R=", (ExpertUseBeAtR ? "on" : "off"),
         " trail@R=", (ExpertUseAtrTrail ? "on" : "off"),
         " SP2L=", (InpUseSP2LFilter ? "on" : "off"),
         " FVG=", (InpUseFVGFilter ? "on" : "off"),
         " safe=", ExpertSafeModeText());
   return(true);
  }

void ExpertInstanceOnDeinit()
  {
   ExpertInstanceRelease();
  }

#endif

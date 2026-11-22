//+------------------------------------------------------------------+
//| MolidoNews.mqh - NEWS_AVOID / NEWS_TRADE using the MT5 calendar  |
//| and optional server event list. Demo-only, always through the    |
//| Risk Brain. Cached once a minute to keep CPU low.                |
//+------------------------------------------------------------------+
#ifndef MOLIDO_NEWS_MQH
#define MOLIDO_NEWS_MQH

#define NEWS_MAX_EVENTS   64
#define NEWS_LOOKAHEAD_H  24
#define NEWS_IMP_LOW       1
#define NEWS_IMP_MOD       2
#define NEWS_IMP_HIGH      3

struct MolidoNewsEvent
  {
   datetime time;
   string   name;
   string   currency;
   int      importance;
   ulong    event_id;
  };

MolidoNewsEvent g_news[NEWS_MAX_EVENTS];
int             g_news_n = 0;
datetime        g_news_cache_at = 0;
// g_news_server_csv is declared in MolidoBridge.mq5
ulong           g_news_traded_id = 0;
datetime        g_news_tighten_for = 0;

int NewsMinImportanceValue()
  {
   return(NEWS_IMP_HIGH);
  }

string NewsModeName()
  {
   if(ProfileForceNewsAvoid())
      return("NEWS_AVOID (prop)");
   return(NewsMode == NEWS_TRADE ? "NEWS_TRADE" : "NEWS_AVOID");
  }

bool NewsPush(const datetime t, const string name, const string currency,
              const int importance, const ulong event_id)
  {
   if(t <= 0 || importance < NewsMinImportanceValue())
      return(false);
   if(g_news_n >= NEWS_MAX_EVENTS)
      return(false);
   for(int i = 0; i < g_news_n; i++)
      if(g_news[i].event_id == event_id && event_id != 0)
         return(false);
   int at = g_news_n;
   for(int j = 0; j < g_news_n; j++)
      if(g_news[j].time > t)
        {
         at = j;
         break;
        }
   for(int k = g_news_n; k > at; k--)
      g_news[k] = g_news[k - 1];
   g_news[at].time = t;
   g_news[at].name = name;
   g_news[at].currency = currency;
   g_news[at].importance = importance;
   g_news[at].event_id = event_id;
   g_news_n++;
   return(true);
  }

void NewsParseServerCsv(const string csv)
  {
   //--- "2026.11.14 20:30|USD|HIGH|NFP;2026.11.14 22:00|EUR|HIGH|CPI"
   if(StringLen(csv) == 0)
      return;
   string rows[];
   int n = StringSplit(csv, ';', rows);
   for(int i = 0; i < n; i++)
     {
      string parts[];
      if(StringSplit(rows[i], '|', parts) < 3)
         continue;
      datetime t = StringToTime(parts[0]);
      string cur = parts[1];
      string imp = parts[2];
      string name = (ArraySize(parts) > 3 ? parts[3] : imp);
      int importance = NEWS_IMP_HIGH;
      if(imp == "LOW")
         importance = NEWS_IMP_LOW;
      else if(imp == "MODERATE" || imp == "MED")
         importance = NEWS_IMP_MOD;
      NewsPush(t, name, cur, importance, (ulong)(1000000 + i));
     }
  }

void NewsPullCalendar(const string currency)
  {
   MqlCalendarValue values[];
   datetime from = TimeGMT() - 2 * 3600;
   datetime to   = TimeGMT() + NEWS_LOOKAHEAD_H * 3600;
   int got = CalendarValueHistory(values, from, to, NULL, currency);
   if(got <= 0)
      return;
   for(int i = 0; i < got; i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      NewsPush(values[i].time, ev.name, currency, (int)ev.importance, values[i].event_id);
     }
  }

void NewsRefresh(const bool force=false)
  {
   if(!force && g_news_cache_at != 0 && (TimeGMT() - g_news_cache_at) < 60)
      return;
   g_news_n = 0;
   NewsPullCalendar("USD");
   NewsPullCalendar("EUR");
   NewsPullCalendar("GBP");
   NewsPullCalendar("JPY");
   NewsParseServerCsv(g_news_server_csv);
   g_news_cache_at = TimeGMT();
  }

bool NewsNext(MolidoNewsEvent &out)
  {
   NewsRefresh();
   datetime now = TimeGMT();
   for(int i = 0; i < g_news_n; i++)
     {
      datetime end = g_news[i].time + NewsAvoidMinutes * 60;
      if(NewsMode == NEWS_TRADE)
         end = g_news[i].time + NewsTradeWindowMinutes * 60;
      if(end >= now)
        {
         out = g_news[i];
         return(true);
        }
     }
   return(false);
  }

string DemoNextNewsLine()
  {
   MolidoNewsEvent ev;
   if(!NewsNext(ev))
      return NewsModeName() + "  none soon";
   int mins = (int)((ev.time - TimeGMT()) / 60);
   string when;
   if(mins >= 0)
      when = "in " + IntegerToString(mins) + "m";
   else
      when = IntegerToString(-mins) + "m ago";
   string name = ev.name;
   if(StringLen(name) > 16)
      name = StringSubstr(name, 0, 16);
   return NewsModeName() + "  " + ev.currency + " " + name + "  " + when;
  }

bool NewsInAvoidWindow(MolidoNewsEvent &ev)
  {
   if(!NewsNext(ev))
      return(false);
   datetime now = TimeGMT();
   int pad = NewsAvoidMinutes * 60;
   if(NewsAvoidMinutes <= 0)
      return(false);
   return(now >= ev.time - pad && now < ev.time + pad);
  }

bool NewsInTradeWindow(MolidoNewsEvent &ev)
  {
   if(NewsMode != NEWS_TRADE)
      return(false);
   if(!NewsNext(ev))
      return(false);
   datetime now = TimeGMT();
   if(now < ev.time)
      return(false);
   return(now <= ev.time + NewsTradeWindowMinutes * 60);
  }

void NewsTightenOpenStops()
  {
   if(!NewsTightenSL)
      return;
   if(!AllowTrading || !DemoAccountOk() || !DemoTerminalTradable())
      return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      string symbol = PositionGetString(POSITION_SYMBOL);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      long kind   = PositionGetInteger(POSITION_TYPE);
      double bid  = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask  = SymbolInfoDouble(symbol, SYMBOL_ASK);
      if(bid <= 0.0 || ask <= 0.0 || open <= 0.0)
         continue;
      bool buy = (kind == POSITION_TYPE_BUY);
      double price = buy ? bid : ask;
      //--- Only move to break-even when already in profit, and only if that tightens.
      bool profit = (buy ? price > open : price < open);
      if(!profit)
         continue;
      double new_sl = open;
      if(buy && sl > 0.0 && new_sl <= sl)
         continue;
      if(!buy && sl > 0.0 && new_sl >= sl)
         continue;
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action   = TRADE_ACTION_SLTP;
      req.symbol   = symbol;
      req.position = ticket;
      req.sl       = NormalizeDouble(new_sl, digits);
      req.tp       = NormalizeDouble(tp, digits);
      if(!DemoAccountOk())
         return;
      if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE)
         Print("MolidoNews: tightened SL to break-even on ", symbol, " ticket ", ticket);
     }
  }

bool NewsPreRange(const datetime event_time, double &hi, double &lo)
  {
   hi = 0.0;
   lo = 0.0;
   int bars = NewsAvoidMinutes;
   if(bars < 5)
      bars = 5;
   int shift = iBarShift(_Symbol, PERIOD_M1, event_time, false);
   if(shift < 0)
      shift = 0;
   //--- Use closed M1 bars strictly before the event.
   int start = shift + 1;
   int end   = start + bars - 1;
   if(iBars(_Symbol, PERIOD_M1) <= end)
      return(false);
   hi = iHigh(_Symbol, PERIOD_M1, start);
   lo = iLow(_Symbol, PERIOD_M1, start);
   if(hi <= 0.0 || lo <= 0.0)
      return(false);
   for(int i = start + 1; i <= end; i++)
     {
      double h = iHigh(_Symbol, PERIOD_M1, i);
      double l = iLow(_Symbol, PERIOD_M1, i);
      if(h <= 0.0 || l <= 0.0)
         return(false);
      if(h > hi) hi = h;
      if(l < lo) lo = l;
     }
   return(hi > lo);
  }

bool DemoNewsTradeOnce()
  {
   MolidoNewsEvent ev;
   if(!NewsInTradeWindow(ev))
      return(false);
   if(ev.event_id != 0 && ev.event_id == g_news_traded_id)
      return(true); // already handled this event
   if(!EnableDemoScalper || !AllowTrading)
      return(true);
   if(!DemoAccountOk() || DemoKillEngaged() || !DemoTerminalTradable())
      return(true);

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     {
      DemoLog(_Symbol, "", DEMO_BLOCK, "news trade: missing bid/ask", 0, 0, 0, 0, 0, 0, 0, 0, 0);
      return(true);
     }
   double spread = tick.ask - tick.bid;
   double point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      return(true);
   if(ScalperMaxSpreadPts > 0 && spread > ScalperMaxSpreadPts * point)
     {
      DemoLog(_Symbol, "", DEMO_BLOCK, "news trade: spread too wide after release",
              0, tick.ask, 0, 0, spread, 0, 0, 0, 0);
      return(true);
     }

   double hi, lo;
   if(!NewsPreRange(ev.time, hi, lo))
     {
      DemoLog(_Symbol, "", DEMO_BLOCK, "news trade: missing pre-news range",
              0, 0, 0, 0, spread, 0, 0, 0, 0);
      return(true);
     }

   double close1 = iClose(_Symbol, PERIOD_M1, 1);
   if(close1 <= 0.0)
      return(true);
   string side = "";
   double entry = 0.0, sl = 0.0, tp = 0.0;
   if(close1 > hi)
     {
      side  = "buy";
      entry = tick.ask;
      sl    = lo;
      tp    = entry + 1.5 * (entry - sl);
     }
   else if(close1 < lo)
     {
      side  = "sell";
      entry = tick.bid;
      sl    = hi;
      tp    = entry - 1.5 * (sl - entry);
     }
   else
      return(true); // no breakout yet, keep watching

   if(sl <= 0.0 || MathAbs(entry - sl) <= 0.0)
      return(true);

   double risk_pct = 0.0, size_factor = 0.0, daily_pnl_pct = 0.0;
   string reasons = "";
   ENUM_DEMO_VERDICT verdict = DemoReview(_Symbol, side, entry, sl, tp, spread,
                                          DemoAtr(_Symbol, PERIOD_M5, DEMO_ATR_PERIOD),
                                          risk_pct, size_factor, daily_pnl_pct, reasons);
   //--- News breakouts always take the REDUCE size, even on APPROVE.
   if(verdict != DEMO_BLOCK)
     {
      size_factor = MathMin(size_factor, 0.5);
      if(size_factor <= 0.0)
         size_factor = 0.5;
      risk_pct = NormalizeDouble(DemoActiveRiskPct() * size_factor, 4);
      verdict  = DEMO_REDUCE;
      reasons  = "news breakout reduced size; " + reasons;
     }
   if(verdict == DEMO_BLOCK)
     {
      DemoLog(_Symbol, side, verdict, "news " + reasons, 0, entry, sl, tp, spread, 0,
              daily_pnl_pct, risk_pct, size_factor);
      g_news_traded_id = ev.event_id;
      return(true);
     }

   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double lot_step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
#ifdef MOLIDO_EXPERT_UI
   ExpertSetLotsSymbol(_Symbol);
#endif
   double lots = DemoSizeLots(AccountInfoDouble(ACCOUNT_BALANCE), risk_pct, MathAbs(entry - sl),
                              tick_size, tick_value, lot_step, min_lot, max_lot);
   if(lots <= 0.0)
     {
      DemoLog(_Symbol, side, DEMO_BLOCK, "news trade: size failed",
              0, entry, sl, tp, spread, 0, daily_pnl_pct, risk_pct, size_factor);
      g_news_traded_id = ev.event_id;
      return(true);
     }
   if(!DemoTradingAllowed() || !DemoTerminalTradable() || DemoKillEngaged())
     {
      DemoLog(_Symbol, side, DEMO_BLOCK, "news trade: pre-send gate refused",
              lots, entry, sl, tp, spread, 0, daily_pnl_pct, risk_pct, size_factor);
      return(true);
     }
   DemoLog(_Symbol, side, verdict, reasons, lots, entry, sl, tp, spread, 0,
           daily_pnl_pct, risk_pct, size_factor);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(DemoSend(_Symbol, side, lots, NormalizeDouble(sl, digits), NormalizeDouble(tp, digits)))
      g_news_traded_id = ev.event_id;
   return(true);
  }

//--- Returns true when the regular scalper must skip new entries this cycle.
bool DemoNewsGateNewEntries()
  {
   NewsRefresh();
   MolidoNewsEvent ev;
   if(NewsInAvoidWindow(ev))
     {
      if(NewsTightenSL && g_news_tighten_for != ev.time)
        {
         NewsTightenOpenStops();
         g_news_tighten_for = ev.time;
        }
      //--- NEWS_TRADE still avoids new regular entries until the release.
      if(NewsMode == NEWS_TRADE && !ProfileForceNewsAvoid() && TimeGMT() >= ev.time)
         return(false);
      static datetime last_logged = 0;
      if(last_logged != ev.time)
        {
         DemoLog(_Symbol, "", DEMO_BLOCK,
                 "NEWS_AVOID window for " + ev.currency + " " + ev.name,
                 0, 0, 0, 0, 0, 0, 0, 0, 0);
         last_logged = ev.time;
        }
      return(true);
     }
   return(false);
  }

bool DemoNewsTradeActive()
  {
   if(NewsMode != NEWS_TRADE || ProfileForceNewsAvoid())
      return(false);
   if(!DemoNewsTradeOnce())
      return(false);
   MolidoNewsEvent ev;
   return(NewsInTradeWindow(ev));
  }

#endif // MOLIDO_NEWS_MQH

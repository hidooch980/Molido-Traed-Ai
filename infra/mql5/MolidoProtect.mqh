//+------------------------------------------------------------------+
//| MolidoProtect.mqh - safe mode, partial TP, correlation guard,    |
//| trade journal screenshots, weekly stats. Demo/prop scalper only. |
//+------------------------------------------------------------------+
#ifndef MOLIDO_PROTECT_MQH
#define MOLIDO_PROTECT_MQH

#define JOURNAL_DIR          "molido_journal"
#define WEEKLY_STATS_FILE    "molido_weekly_stats.txt"
#define PARTIAL_MAX          32
#define WEEKLY_HOURS         24
#define WEEKLY_SYMS          24

ulong    g_partial_done[PARTIAL_MAX];
int      g_partial_n = 0;
string   g_watch_tickets = "";
int      g_safe_losses = 0;
bool     g_safe_stop = false;
string   g_weekly_line = "Week n/a";
string   g_weekly_best_hours = "";
datetime g_weekly_cached_at = 0;
double   g_weekly_hour_pnl[WEEKLY_HOURS];
int      g_weekly_hour_n[WEEKLY_HOURS];
double   g_weekly_pnl = 0.0;
int      g_weekly_trades = 0;
string   g_weekly_sym_name[WEEKLY_SYMS];
double   g_weekly_sym_pnl[WEEKLY_SYMS];
int      g_weekly_sym_count = 0;

string SymbolCore(const string symbol)
  {
   string u = symbol;
   StringToUpper(u);
   static string cores[16] = {"XAUUSD","XAGUSD","EURUSD","GBPUSD","AUDUSD","NZDUSD",
                              "USDJPY","USDCHF","USDCAD","EURJPY","GBPJPY","AUDJPY",
                              "EURGBP","EURCHF","GBPCHF","CADJPY"};
   for(int i = 0; i < 16; i++)
      if(StringFind(u, cores[i]) == 0)
         return(cores[i]);
   return(u);
  }

int CorrelationGroup(const string core)
  {
   if(core == "EURUSD" || core == "GBPUSD" || core == "AUDUSD" || core == "NZDUSD")
      return(1);
   if(core == "USDJPY" || core == "USDCHF" || core == "USDCAD")
      return(2);
   if(core == "EURJPY" || core == "GBPJPY" || core == "AUDJPY" || core == "CADJPY")
      return(3);
   if(core == "XAUUSD" || core == "XAGUSD")
      return(4);
   return(0);
  }

int ProtectConsecutiveLosses()
  {
   static int cached = 0;
   static datetime cached_at = 0;
   datetime now = TimeCurrent();
   if(cached_at == now)
      return(cached);
   cached_at = now;
   cached = 0;
   if(!HistorySelect(now - 21 * 86400, now + 1))
      return(0);
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
      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                   + HistoryDealGetDouble(ticket, DEAL_SWAP)
                   + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      if(pnl >= 0.0)
         break;
      cached++;
     }
   g_safe_losses = cached;
   return(cached);
  }

bool DemoSafeModeStopped()
  {
   int stop_after = SafeModeStopAfter;
   if(stop_after <= 0)
     {
      g_safe_stop = false;
      return(false);
     }
   if(ProtectConsecutiveLosses() >= stop_after)
     {
      g_safe_stop = true;
      return(true);
     }
   g_safe_stop = false;
   return(false);
  }

double DemoSafeModeFactor()
  {
   if(DemoSafeModeStopped())
      return(0.0);
   int reduce_after = SafeModeReduceAfter;
   if(reduce_after <= 0)
      return(1.0);
   if(ProtectConsecutiveLosses() >= reduce_after)
     {
      double f = SafeModeReduceFactor;
      if(f < 0.1) f = 0.1;
      if(f > 1.0) f = 1.0;
      return(f);
     }
   return(1.0);
  }

string DemoSafeModeLine()
  {
   int n = ProtectConsecutiveLosses();
   if(DemoSafeModeStopped())
      return("STOP " + IntegerToString(n) + "L until tomorrow");
   if(DemoSafeModeFactor() < 1.0)
      return("REDUCE " + IntegerToString(n) + "L x" + DoubleToString(DemoSafeModeFactor(), 2));
   if(n > 0)
      return(IntegerToString(n) + " losing");
   return("off");
  }

bool CorrelationConflict(const string symbol, const string side, string &why)
  {
   why = "";
   if(!UseCorrelationGuard)
      return(false);
   string core = SymbolCore(symbol);
   int group = CorrelationGroup(core);
   if(group <= 0)
      return(false);
   bool want_buy = (side == "buy");
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(!IsMolidoMagic((long)PositionGetInteger(POSITION_MAGIC)))
         continue;
      string other = PositionGetString(POSITION_SYMBOL);
      string oc = SymbolCore(other);
      if(oc == core)
         continue;
      if(CorrelationGroup(oc) != group)
         continue;
      bool other_buy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      if(other_buy == want_buy)
        {
         why = "correlation: " + oc + " already " + (other_buy ? "buy" : "sell");
         return(true);
        }
     }
   return(false);
  }

void WeeklyResetBuckets()
  {
   for(int h = 0; h < WEEKLY_HOURS; h++)
     {
      g_weekly_hour_pnl[h] = 0.0;
      g_weekly_hour_n[h] = 0;
     }
   g_weekly_pnl = 0.0;
   g_weekly_trades = 0;
  }

datetime WeekStartGmt()
  {
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   int back = dt.day_of_week;
   if(back == 0)
      back = 7;
   back -= 1; // Monday = start
   datetime day = TimeGMT() - (datetime)(back * 86400)
                  - (datetime)(dt.hour * 3600 + dt.min * 60 + dt.sec);
   return(day);
  }

void DemoWeeklyRefresh()
  {
   datetime now = TimeCurrent();
   if(g_weekly_cached_at != 0 && (now - g_weekly_cached_at) < 60)
      return;
   g_weekly_cached_at = now;
   WeeklyResetBuckets();
   g_weekly_sym_count = 0;
   datetime from = WeekStartGmt();
   if(!HistorySelect(from, now + 1))
     {
      g_weekly_line = "Week n/a";
      return;
     }
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
      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                   + HistoryDealGetDouble(ticket, DEAL_SWAP)
                   + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      MqlDateTime dt;
      TimeToStruct(t, dt);
      if(dt.hour >= 0 && dt.hour < WEEKLY_HOURS)
        {
         g_weekly_hour_pnl[dt.hour] += pnl;
         g_weekly_hour_n[dt.hour]++;
        }
      string core = SymbolCore(HistoryDealGetString(ticket, DEAL_SYMBOL));
      int at = -1;
      for(int s = 0; s < g_weekly_sym_count; s++)
         if(g_weekly_sym_name[s] == core)
           {
            at = s;
            break;
           }
      if(at < 0 && g_weekly_sym_count < WEEKLY_SYMS)
        {
         at = g_weekly_sym_count;
         g_weekly_sym_name[at] = core;
         g_weekly_sym_pnl[at] = 0.0;
         g_weekly_sym_count++;
        }
      if(at >= 0)
         g_weekly_sym_pnl[at] += pnl;
      g_weekly_pnl += pnl;
      g_weekly_trades++;
     }

   int best_h = -1;
   double best_hp = 0.0;
   string hours = "";
   for(int h = 0; h < WEEKLY_HOURS; h++)
     {
      if(g_weekly_hour_n[h] <= 0)
         continue;
      if(hours != "")
         hours += ",";
      hours += IntegerToString(h) + ":" + DoubleToString(g_weekly_hour_pnl[h], 1);
      if(best_h < 0 || g_weekly_hour_pnl[h] > best_hp)
        {
         best_h = h;
         best_hp = g_weekly_hour_pnl[h];
        }
     }
   g_weekly_best_hours = hours;
   int best_s = -1;
   double best_sp = 0.0;
   string symbols = "";
   for(int s = 0; s < g_weekly_sym_count; s++)
     {
      if(symbols != "")
         symbols += ",";
      symbols += g_weekly_sym_name[s] + ":" + DoubleToString(g_weekly_sym_pnl[s], 1);
      if(best_s < 0 || g_weekly_sym_pnl[s] > best_sp)
        {
         best_s = s;
         best_sp = g_weekly_sym_pnl[s];
        }
     }

   string sign = (g_weekly_pnl >= 0.0 ? "+" : "");
   string bh = (best_h >= 0 ? (IntegerToString(best_h) + "h") : "--");
   string bs = (best_s >= 0 ? g_weekly_sym_name[best_s] : "--");
   g_weekly_line = "Week " + sign + DoubleToString(g_weekly_pnl, 0) +
                   "  " + IntegerToString(g_weekly_trades) + "t  best " + bh + " " + bs;

   static string last_written = "";
   if(last_written == g_weekly_line)
      return;
   last_written = g_weekly_line;
   int hnd = FileOpen(WEEKLY_STATS_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(hnd == INVALID_HANDLE)
      return;
   FileWriteString(hnd, "week_start=" + TimeToString(from, TIME_DATE) + "\n");
   FileWriteString(hnd, "pnl=" + DoubleToString(g_weekly_pnl, 2) + "\n");
   FileWriteString(hnd, "trades=" + IntegerToString(g_weekly_trades) + "\n");
   FileWriteString(hnd, "best_hour=" + IntegerToString(best_h) + "\n");
   FileWriteString(hnd, "best_symbol=" + (best_s >= 0 ? g_weekly_sym_name[best_s] : "") + "\n");
   FileWriteString(hnd, "hours=" + hours + "\n");
   FileWriteString(hnd, "symbols=" + symbols + "\n");
   FileClose(hnd);
  }

string DemoWeeklyStatsLine()
  {
   DemoWeeklyRefresh();
   return(g_weekly_line);
  }

bool WeeklyHourIsFocused(string &why)
  {
   why = "";
   if(!UseWeeklySessionFocus)
      return(true);
   DemoWeeklyRefresh();
   if(g_weekly_trades < WeeklyFocusMinTrades)
      return(true); // not enough data: do not invent a block
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   if(dt.hour < 0 || dt.hour >= WEEKLY_HOURS)
      return(true);
   if(g_weekly_hour_n[dt.hour] <= 0)
     {
      why = "weekly focus: no edge at hour " + IntegerToString(dt.hour);
      return(false);
     }
   if(g_weekly_hour_pnl[dt.hour] <= 0.0)
     {
      why = "weekly focus: hour " + IntegerToString(dt.hour) + " is not profitable this week";
      return(false);
     }
   return(true);
  }

bool DemoProtectAllowEntry(const string symbol, const string side, string &why)
  {
   why = "";
   if(DemoSafeModeStopped())
     {
      why = "safe mode: stop until next day after consecutive losses";
      return(false);
     }
   if(CorrelationConflict(symbol, side, why))
      return(false);
   if(!WeeklyHourIsFocused(why))
      return(false);
   return(true);
  }

bool PartialAlready(const ulong ticket)
  {
   for(int i = 0; i < g_partial_n; i++)
      if(g_partial_done[i] == ticket)
         return(true);
   return(false);
  }

void PartialMark(const ulong ticket)
  {
   if(PartialAlready(ticket) || g_partial_n >= PARTIAL_MAX)
      return;
   g_partial_done[g_partial_n++] = ticket;
  }

void DemoPartialTakeProfit()
  {
   if(!UsePartialTP)
      return;
   if(!DemoAccountOk() || !DemoTerminalTradable())
      return;
   double pct = PartialTpClosePct;
   if(pct < 10.0) pct = 10.0;
   if(pct > 90.0) pct = 90.0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      if(PartialAlready(ticket))
         continue;
      string symbol = PositionGetString(POSITION_SYMBOL);
      long kind = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double tp = PositionGetDouble(POSITION_TP);
      double sl = PositionGetDouble(POSITION_SL);
      double vol = PositionGetDouble(POSITION_VOLUME);
      if(open <= 0.0 || vol <= 0.0)
         continue;
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      bool is_buy = (kind == POSITION_TYPE_BUY);
      double price = is_buy ? bid : ask;
      double tp_dist = 0.0;
      if(tp > 0.0)
         tp_dist = MathAbs(tp - open) * 0.5;
      else
        {
         double atr = DemoAtr(symbol, ScalperTF, DEMO_ATR_PERIOD);
         if(atr <= 0.0)
            continue;
         tp_dist = atr * 0.75;
        }
      if(tp_dist <= 0.0)
         continue;
      double moved = is_buy ? (price - open) : (open - price);
      if(moved < tp_dist)
         continue;
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      double minv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      if(step <= 0.0 || minv <= 0.0)
         continue;
      double close_v = MathFloor((vol * pct / 100.0) / step) * step;
      if(close_v < minv)
         continue;
      if((vol - close_v) < minv)
         continue;
      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_DEAL;
      req.symbol = symbol;
      req.volume = close_v;
      req.position = ticket;
      req.deviation = MaxSlippagePts;
      req.magic = DEMO_SCALPER_MAGIC;
      req.comment = "molido-tp1";
      req.type_filling = MolidoFilling(symbol);
      if(is_buy)
        {
         req.type = ORDER_TYPE_SELL;
         req.price = bid;
        }
      else
        {
         req.type = ORDER_TYPE_BUY;
         req.price = ask;
        }
      if(req.price <= 0.0)
         continue;
      if(!OrderSend(req, res))
         continue;
      if(res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_PLACED)
         continue;
      PartialMark(ticket);
      Print("MolidoScalper: partial TP ", DoubleToString(close_v, 2), " of ", symbol,
            " ticket ", ticket);
      DemoJournalShot("partial", symbol, ticket);
      //--- Protect the remainder at break-even, then the trailing stop takes over.
      if(UseBreakEven && sl > 0.0)
        {
         double be = open;
         bool tighten = is_buy ? (be > sl) : (be < sl || sl <= 0.0);
         if(tighten && be > 0.0)
           {
            MqlTradeRequest req2;
            MqlTradeResult  res2;
            ZeroMemory(req2);
            ZeroMemory(res2);
            req2.action = TRADE_ACTION_SLTP;
            req2.symbol = symbol;
            req2.position = ticket;
            req2.sl = NormalizeDouble(be, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
            req2.tp = tp;
            OrderSend(req2, res2);
           }
        }
     }
  }

long ChartIdForSymbol(const string symbol)
  {
   if(_Symbol == symbol)
      return(ChartID());
   long id = ChartFirst();
   while(id >= 0)
     {
      if(ChartSymbol(id) == symbol)
         return(id);
      id = ChartNext(id);
     }
   return(ChartID());
  }

void DemoJournalShot(const string kind, const string symbol, const ulong ticket)
  {
   FolderCreate(JOURNAL_DIR);
   MqlDateTime dt;
   TimeToStruct(TimeLocal(), dt);
   string stamp = IntegerToString(dt.year) +
                  StringFormat("%02d", dt.mon) +
                  StringFormat("%02d", dt.day) + "_" +
                  StringFormat("%02d", dt.hour) +
                  StringFormat("%02d", dt.min);
   string name = JOURNAL_DIR + "\\" + kind + "_" + IntegerToString((long)ticket) + "_" +
                 SymbolCore(symbol) + "_" + stamp + ".png";
   long id = ChartIdForSymbol(symbol);
   if(!ChartScreenShot(id, name, 1280, 720))
      Print("MolidoScalper: journal screenshot failed for ", name, " err ", GetLastError());
  }

string ProtectOpenSig()
  {
   string sig = "";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      sig += IntegerToString((long)ticket) + ":" + PositionGetString(POSITION_SYMBOL) + ";";
     }
   return(sig);
  }

void DemoJournalWatchCloses()
  {
   string now = ProtectOpenSig();
   if(g_watch_tickets == "")
     {
      g_watch_tickets = now;
      return;
     }
   if(now == g_watch_tickets)
      return;
   string prev[];
   int n = StringSplit(g_watch_tickets, ';', prev);
   for(int i = 0; i < n; i++)
     {
      if(StringLen(prev[i]) <= 0)
         continue;
      int c = StringFind(prev[i], ":");
      if(c <= 0)
         continue;
      string tk = StringSubstr(prev[i], 0, c);
      string sym = StringSubstr(prev[i], c + 1);
      if(StringFind(now, tk + ":") >= 0)
         continue;
      DemoJournalShot("close", sym, (ulong)StringToInteger(tk));
     }
   g_watch_tickets = now;
  }

void DemoProtectOnTick()
  {
   static uint last_ms = 0;
   uint now = GetTickCount();
   if(last_ms != 0 && (now - last_ms) < 400)
      return;
   last_ms = now;
   DemoPartialTakeProfit();
   DemoJournalWatchCloses();
   DemoWeeklyRefresh();
  }

double WeeklyCorePnl(const string core, bool &have)
  {
   have = false;
   DemoWeeklyRefresh();
   for(int s = 0; s < g_weekly_sym_count; s++)
      if(g_weekly_sym_name[s] == core)
        {
         have = true;
         return(g_weekly_sym_pnl[s]);
        }
   return(0.0);
  }

#endif

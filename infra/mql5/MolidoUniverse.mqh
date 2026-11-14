//+------------------------------------------------------------------+
//| MolidoUniverse.mqh - account-wide AutoSymbolMode.                |
//| Scores Market Watch / tradable symbols and trades the top N.     |
//| Ranking from the server is a bonus only, never a loose override. |
//+------------------------------------------------------------------+
#ifndef MOLIDO_UNIVERSE_MQH
#define MOLIDO_UNIVERSE_MQH

#define AUTO_MAX_RANK  8
#define AUTO_PREFILTER 20

string   g_auto_sym[AUTO_MAX_RANK];
double   g_auto_score[AUTO_MAX_RANK];
int      g_auto_n = 0;
string   g_auto_line = "Auto off";
datetime g_auto_bar = 0;

int AutoTopN()
  {
   int n = AutoSymbolTopN;
   if(n < 1) n = 1;
   if(n > AUTO_MAX_RANK) n = AUTO_MAX_RANK;
   if(n > DEMO_MAX_SYMS) n = DEMO_MAX_SYMS;
   return(n);
  }

int AutoMaxScan()
  {
   int n = AutoSymbolMaxScan;
   if(n < 8) n = 8;
   if(n > 120) n = 120;
   return(n);
  }

bool AutoTradable(const string symbol)
  {
   long mode = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   if(mode != SYMBOL_TRADE_MODE_FULL)
      return(false);
   if(SymbolInfoDouble(symbol, SYMBOL_BID) <= 0.0)
      return(false);
   if(SymbolInfoDouble(symbol, SYMBOL_ASK) <= 0.0)
      return(false);
   if(SymbolInfoDouble(symbol, SYMBOL_POINT) <= 0.0)
      return(false);
   if(SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE) <= 0.0)
      return(false);
   return(true);
  }

double AutoRocketScore(const string symbol)
  {
   if(StringLen(g_ranking_csv) <= 0)
      return(-1.0);
   string core = SymbolCore(symbol);
   string rows[];
   int n = StringSplit(g_ranking_csv, ';', rows);
   for(int i = 0; i < n; i++)
     {
      string row = rows[i];
      StringTrimLeft(row);
      StringTrimRight(row);
      int c = StringFind(row, ":");
      if(c <= 0)
         continue;
      string name = StringSubstr(row, 0, c);
      string val  = StringSubstr(row, c + 1);
      StringTrimLeft(name); StringTrimRight(name);
      StringToUpper(name);
      if(name != core && StringFind(symbol, name) != 0 && StringFind(name, core) != 0)
         continue;
      double s = StringToDouble(val);
      if(s < 0.0) s = 0.0;
      if(s > 100.0) s = 100.0;
      return(s);
     }
   return(-1.0);
  }

double AutoCheapScore(const string symbol, double &spread, double &atr)
  {
   spread = 0.0;
   atr = 0.0;
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
      return(-1.0);
   spread = tick.ask - tick.bid;
   atr = DemoAtr(symbol, ScalperTF, DEMO_ATR_PERIOD);
   if(atr <= 0.0)
      return(-1.0);
   double ratio = spread / atr;
   //--- 0 at the existing 15% ATR spread cap, 25 at a tight spread.
   double spread_pts = 25.0 * (1.0 - ratio / DEMO_SPREAD_ATR_FRAC);
   if(spread_pts < 0.0)
      spread_pts = 0.0;
   if(spread_pts > 25.0)
      spread_pts = 25.0;
   //--- Volatility: prefer a living but not chaotic ATR vs price.
   double mid = (tick.ask + tick.bid) * 0.5;
   double vol = (mid > 0.0) ? (atr / mid) : 0.0;
   double vol_pts = 0.0;
   if(vol >= 0.0002 && vol <= 0.02)
      vol_pts = 15.0;
   else if(vol > 0.0)
      vol_pts = 6.0;
   string sess = "";
   double sess_pts = SmartInSession(sess) ? 10.0 : 2.0;
   return(spread_pts + vol_pts + sess_pts);
  }

double AutoFullScore(const string symbol, const double cheap)
  {
   double score = cheap;
   double adx = SmartAdx(symbol, ScalperTF, SmartAdxPeriod());
   if(adx >= SmartAdxMin() && adx <= 45.0)
      score += 15.0;
   else if(adx >= SmartAdxMin())
      score += 8.0;
   double m15_e20 = DemoEma(symbol, PERIOD_M15, 20, 1);
   double m15_e50 = DemoEma(symbol, PERIOD_M15, 50, 1);
   double h1_e20  = DemoEma(symbol, PERIOD_H1, 20, 1);
   double h1_e50  = DemoEma(symbol, PERIOD_H1, 50, 1);
   if(m15_e20 > 0.0 && h1_e20 > 0.0 &&
      ((m15_e20 > m15_e50 && h1_e20 > h1_e50) ||
       (m15_e20 < m15_e50 && h1_e20 < h1_e50)))
      score += 10.0;
   bool have = false;
   double wp = WeeklyCorePnl(SymbolCore(symbol), have);
   if(have)
      score += (wp > 0.0 ? 10.0 : 0.0);
   else
      score += 5.0; // no history: neutral, not a bonus
   double rocket = AutoRocketScore(symbol);
   if(rocket >= 0.0)
      score += 0.10 * rocket; // at most +10, never overrides a local fail
   if(score < 0.0) score = 0.0;
   if(score > 100.0) score = 100.0;
   return(score);
  }

void AutoInsertRank(const string symbol, const double score, string &names[],
                    double &scores[], int &n, const int cap)
  {
   if(score < 0.0 || StringLen(symbol) == 0)
      return;
   for(int i = 0; i < n; i++)
      if(SymbolCore(names[i]) == SymbolCore(symbol))
        {
         if(score > scores[i])
            scores[i] = score;
         return;
        }
   int at = n;
   if(n < cap)
      n++;
   else
     {
      at = cap - 1;
      if(score <= scores[at])
         return;
     }
   names[at] = symbol;
   scores[at] = score;
   //--- Keep descending.
   for(int j = at; j > 0; j--)
      if(scores[j] > scores[j - 1])
        {
         double ts = scores[j];
         scores[j] = scores[j - 1];
         scores[j - 1] = ts;
         string tn = names[j];
         names[j] = names[j - 1];
         names[j - 1] = tn;
        }
      else
         break;
  }

bool AutoAlreadyOpen(const string symbol)
  {
   string core = SymbolCore(symbol);
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(!IsMolidoMagic((long)PositionGetInteger(POSITION_MAGIC)))
         continue;
      if(SymbolCore(PositionGetString(POSITION_SYMBOL)) == core)
         return(true);
     }
   return(false);
  }

void AutoApplyList(string &names[], double &scores[], const int n)
  {
   string old_sym[DEMO_MAX_SYMS];
   datetime old_bar[DEMO_MAX_SYMS];
   bool old_primed[DEMO_MAX_SYMS];
   int old_n = g_demo_n;
   for(int i = 0; i < old_n && i < DEMO_MAX_SYMS; i++)
     {
      old_sym[i] = g_demo_syms[i];
      old_bar[i] = g_demo_seen_bar[i];
      old_primed[i] = g_demo_primed[i];
     }

   g_auto_n = 0;
   g_demo_n = 0;
   int top = AutoTopN();
   for(int i = 0; i < n && g_auto_n < AUTO_MAX_RANK; i++)
     {
      if(!SymbolSelect(names[i], true))
         continue;
      g_auto_sym[g_auto_n] = names[i];
      g_auto_score[g_auto_n] = scores[i];
      g_auto_n++;
     }
   //--- Always keep symbols that already have our positions, even if they
   //--- dropped out of the top N, so management and limits stay consistent.
   int total = PositionsTotal();
   for(int p = 0; p < total; p++)
     {
      ulong ticket = PositionGetTicket(p);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(!IsMolidoMagic((long)PositionGetInteger(POSITION_MAGIC)))
         continue;
      string pos = PositionGetString(POSITION_SYMBOL);
      bool have = false;
      for(int i = 0; i < g_auto_n; i++)
         if(SymbolCore(g_auto_sym[i]) == SymbolCore(pos))
           {
            have = true;
            break;
           }
      if(!have && g_auto_n < AUTO_MAX_RANK)
        {
         g_auto_sym[g_auto_n] = pos;
         g_auto_score[g_auto_n] = 0.0;
         g_auto_n++;
        }
     }
   int use = g_auto_n;
   if(use > top)
     {
      //--- Trim unused ranks, but never drop an open symbol.
      int keep = 0;
      string ks[AUTO_MAX_RANK];
      double sc[AUTO_MAX_RANK];
      for(int i = 0; i < g_auto_n; i++)
        {
         if(keep >= top && !AutoAlreadyOpen(g_auto_sym[i]))
            continue;
         ks[keep] = g_auto_sym[i];
         sc[keep] = g_auto_score[i];
         keep++;
         if(keep >= AUTO_MAX_RANK)
            break;
        }
      g_auto_n = keep;
      for(int i = 0; i < keep; i++)
        {
         g_auto_sym[i] = ks[i];
         g_auto_score[i] = sc[i];
        }
     }

   for(int i = 0; i < g_auto_n && g_demo_n < DEMO_MAX_SYMS; i++)
     {
      g_demo_syms[g_demo_n] = g_auto_sym[i];
      g_demo_seen_bar[g_demo_n] = 0;
      g_demo_primed[g_demo_n] = false;
      for(int k = 0; k < old_n; k++)
         if(old_sym[k] == g_auto_sym[i])
           {
            g_demo_seen_bar[g_demo_n] = old_bar[k];
            g_demo_primed[g_demo_n] = old_primed[k];
            break;
           }
      g_demo_n++;
     }

   string line = "Auto";
   int show = (g_auto_n < top ? g_auto_n : top);
   for(int i = 0; i < show; i++)
      line += "  " + IntegerToString(i + 1) + " " + SymbolCore(g_auto_sym[i]) +
              " " + DoubleToString(g_auto_score[i], 0);
   if(show == 0)
      line = "Auto  none";
   g_auto_line = line;
  }

bool AutoModeOn()
  {
   return(AutoSymbolMode || StrategyMode == STRAT_AUTO);
  }

bool AutoRescan()
  {
   if(!AutoModeOn())
      return(false);
   DemoWeeklyRefresh();
   int cap = AutoMaxScan();
   string cheap_n[];
   double cheap_s[];
   ArrayResize(cheap_n, cap);
   ArrayResize(cheap_s, cap);
   int cheap_c = 0;

   //--- Pass 1: Market Watch first, then the rest of the terminal.
   for(int pass = 0; pass < 2; pass++)
     {
      bool watch_only = (pass == 0);
      int total = SymbolsTotal(watch_only);
      for(int i = 0; i < total && cheap_c < cap; i++)
        {
         string name = SymbolName(i, watch_only);
         if(StringLen(name) == 0)
            continue;
         if(!watch_only && !SymbolSelect(name, true))
            continue;
         if(!AutoTradable(name))
            continue;
         double spread, atr;
         double sc = AutoCheapScore(name, spread, atr);
         if(sc < 0.0)
            continue;
         AutoInsertRank(name, sc, cheap_n, cheap_s, cheap_c, cap);
        }
     }

   int pre = cheap_c;
   if(pre > AUTO_PREFILTER)
      pre = AUTO_PREFILTER;
   string full_n[];
   double full_s[];
   ArrayResize(full_n, AUTO_MAX_RANK + 4);
   ArrayResize(full_s, AUTO_MAX_RANK + 4);
   int full_c = 0;
   for(int i = 0; i < pre; i++)
     {
      double sc = AutoFullScore(cheap_n[i], cheap_s[i]);
      AutoInsertRank(cheap_n[i], sc, full_n, full_s, full_c, AUTO_MAX_RANK + 2);
     }
   if(full_c <= 0)
      return(false);
   AutoApplyList(full_n, full_s, full_c);
   return(g_demo_n > 0);
  }

void AutoRefreshIfDue()
  {
   if(!AutoModeOn())
      return;
   datetime bar = iTime(_Symbol, ScalperTF, 0);
   if(bar != 0 && bar == g_auto_bar && g_demo_n > 0)
      return;
   if(!AutoRescan())
      return;
   g_auto_bar = bar;
   Print("MolidoScalper: AutoSymbolMode top ", g_auto_line);
  }

string DemoAutoRankLine()
  {
   if(!AutoModeOn())
      return("Auto off");
   return(g_auto_line);
  }

#endif

//+------------------------------------------------------------------+
//| MolidoExpertExec.mqh - manual trade controls through Risk Brain. |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_EXEC_MQH
#define MOLIDO_EXPERT_EXEC_MQH

#define EX_GV_AUTO    "Molido.Expert.Auto"
#define EX_GV_STOP    "Molido.Expert.StopNew"

double g_ex_lot      = 0.01;
double g_ex_risk_ui  = 0.5;
double g_ex_sl_pts   = 0;     // 0 = Smart TP/SL (ATR)
double g_ex_tp_pts   = 0;
int    g_ex_max_pos  = 2;
bool   g_ex_smart_sl = true;  // implemented (ATR 1.5 / 2.5)
string g_ex_last_msg = "";
string g_ex_last_side = "";
double g_ex_last_entry = 0, g_ex_last_sl = 0, g_ex_last_tp = 0;
int    g_ex_last_strength = 0;

bool ExpertAutoOn()
  {
   if(!GlobalVariableCheck(EX_GV_AUTO))
      return(true);  // default AUTO
   return(GlobalVariableGet(EX_GV_AUTO) > 0.5);
  }

void ExpertSetAuto(const bool on)
  {
   GlobalVariableSet(EX_GV_AUTO, on ? 1.0 : 0.0);
  }

bool ExpertStopNew()
  {
   if(GlobalVariableCheck(EX_GV_STOP) && GlobalVariableGet(EX_GV_STOP) > 0.5)
      return(true);
   return(false);
  }

void ExpertSetStopNew(const bool on)
  {
   GlobalVariableSet(EX_GV_STOP, on ? 1.0 : 0.0);
  }

bool ExpertLevels(const string symbol, const string side,
                  double &entry, double &sl, double &tp, double &spread, double &atr, string &why)
  {
   why = "";
   if(!SymbolSelect(symbol, true))
     { why = "symbol not available"; return(false); }
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0)
     { why = "missing bid/ask"; return(false); }
   spread = tick.ask - tick.bid;
   entry = (side == "sell") ? tick.bid : tick.ask;
   atr = DemoAtr(symbol, PERIOD_M15, 14);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0)
     { why = "missing point"; return(false); }
   double sl_dist = 0.0, tp_dist = 0.0;
   if(g_ex_smart_sl || g_ex_sl_pts <= 0.0)
     {
      if(atr <= 0.0)
        { why = "missing ATR for Smart TP/SL"; return(false); }
      sl_dist = 1.5 * atr;
      tp_dist = 2.5 * atr;
     }
   else
     {
      sl_dist = g_ex_sl_pts * point;
      tp_dist = (g_ex_tp_pts > 0.0 ? g_ex_tp_pts * point : 1.6 * sl_dist);
     }
   if(side == "sell")
     { sl = entry + sl_dist; tp = entry - tp_dist; }
   else
     { sl = entry - sl_dist; tp = entry + tp_dist; }
   ExpertEnsureMinTp(side, entry, sl, tp);
   if(sl <= 0.0 || tp <= 0.0)
     { why = "invalid SL/TP"; return(false); }
   return(true);
  }

bool ExpertManualTrade(const string side)
  {
   g_ex_last_msg = "";
   g_ex_last_side = side;
   if(MolidoRealBlocked())
     { g_ex_last_msg = "real account not supported"; return(false); }
   if(ExpertStopNew())
     { g_ex_last_msg = "stop new trades is on"; return(false); }
   if(!ExpertInstanceMayTrade())
     { g_ex_last_msg = "standby: another instance owns this account"; return(false); }
   if(!DemoAccountOk() || !DemoTradingAllowed() || !DemoTerminalTradable())
     { g_ex_last_msg = "trading not allowed"; return(false); }

   string symbol = _Symbol;
   double entry, sl, tp, spread, atr;
   string why;
   if(!ExpertLevels(symbol, side, entry, sl, tp, spread, atr, why))
     { g_ex_last_msg = why; return(false); }

   //--- optional tighter concurrent cap from the UI, never above the hard cap
   if(DemoOpenCount() >= ExpertMaxPosCap(g_ex_max_pos))
     { g_ex_last_msg = "max concurrent reached"; return(false); }

   double risk_pct = 0.0, size_factor = 0.0, daily_pnl_pct = 0.0;
   string reasons = "";
   ENUM_DEMO_VERDICT verdict = DemoReview(symbol, side, entry, sl, tp, spread, atr,
                                          risk_pct, size_factor, daily_pnl_pct, reasons);
   if(verdict == DEMO_BLOCK)
     {
      DemoLog(symbol, side, verdict, reasons, 0, entry, sl, tp, spread, atr,
              daily_pnl_pct, risk_pct, size_factor);
      g_ex_last_msg = reasons;
      return(false);
     }

   double want = ExpertRiskPctCap(g_ex_risk_ui);
   if(want < risk_pct)
      risk_pct = want;
   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double lot_step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double sl_dist    = MathAbs(entry - sl);
   ExpertSetLotsSymbol(symbol);
   double lots = DemoSizeLots(AccountInfoDouble(ACCOUNT_BALANCE), risk_pct, sl_dist,
                              tick_size, tick_value, lot_step, min_lot, max_lot);
   //--- a smaller requested lot is safer; a larger one is clamped
   if(g_ex_lot > 0.0 && g_ex_lot < lots)
      lots = g_ex_lot;
   lots = MathMin(lots, DemoEffectiveMaxLots());
   if(lots <= 0.0)
     { g_ex_last_msg = "lot size is zero after caps"; return(false); }

   g_ex_last_entry = entry;
   g_ex_last_sl = sl;
   g_ex_last_tp = tp;
   g_ex_last_strength = DemoSignalStrength();
   DemoLog(symbol, side, verdict, reasons, lots, entry, sl, tp, spread, atr,
           daily_pnl_pct, risk_pct, size_factor);
   if(!DemoSend(symbol, side, lots, sl, tp))
     { g_ex_last_msg = "OrderSend failed"; return(false); }
   g_ex_last_msg = side + " " + DoubleToString(lots, 2) + " " + symbol;
   return(true);
  }

int ExpertCloseTicket(const ulong ticket)
  {
   CloseOne("expert-ui", ticket);
   return(1);
  }

int ExpertCloseChart()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(!ExpertIsOurs(PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_COMMENT)))
         continue;
      CloseOne("expert-ui", ticket);
      n++;
     }
   g_ex_last_msg = "closed " + IntegerToString(n) + " on " + _Symbol;
   return(n);
  }

int ExpertCloseAll()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!ExpertIsOurs(PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_COMMENT)))
         continue;
      CloseOne("expert-ui", ticket);
      n++;
     }
   g_ex_last_msg = "closed all " + IntegerToString(n);
   return(n);
  }

#endif

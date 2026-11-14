//+------------------------------------------------------------------+
//| MolidoDemoScalper.mqh - demo-only scalper gated by a Risk Brain. |
//|                                                                  |
//| Hard account gate: ACCOUNT_TRADE_MODE_DEMO and login 68531270.   |
//| Sized for a 200,000 USD demo:                                    |
//|   risk per trade  <= 0.5%   (~$1,000)                            |
//|   daily loss cap      2%    (~$4,000)                            |
//|   max lots            2.00  (still bounded by 0.5% stop size)    |
//|   max open positions  2                                          |
//| Stop-loss is mandatory. A missing quote, ATR, history, tick      |
//| value or any other input is a BLOCK, never a guess. BLOCK from   |
//| the Risk Brain is final. Every decision is logged.               |
//|                                                                  |
//| Mirrors backend/app/agents/demo_scalper.py. Does not run on a    |
//| real or contest account, even if AllowRealAccount is later set.  |
//+------------------------------------------------------------------+
#ifndef MOLIDO_DEMO_SCALPER_MQH
#define MOLIDO_DEMO_SCALPER_MQH

#define DEMO_SCALPER_LOGIN      68531270
#define DEMO_SCALPER_MAGIC      685317
#define DEMO_HARD_MAX_LOTS      2.0
#define DEMO_RISK_PCT           0.5
#define DEMO_DAILY_LOSS_PCT     2.0
#define DEMO_REDUCE_FRACTION    0.5
#define DEMO_REDUCE_FACTOR      0.5
#define DEMO_MAX_POSITIONS      2
#define DEMO_MIN_RR             1.2
#define DEMO_SPREAD_ATR_FRAC    0.15
#define DEMO_SL_ATR             1.0
#define DEMO_TP_ATR             1.5
#define DEMO_ATR_PERIOD         14
#define DEMO_MAX_ENTRIES_DAY    8
#define DEMO_STALE_SECONDS      60
#define DEMO_MAX_SYMS           16
#define DEMO_KILL_FILE          "molido_kill_switch"
#define DEMO_LOG_FILE           "molido_scalper_log.jsonl"
#define DEMO_LAST_FILE          "molido_scalper_last.json"

//--- Scalper inputs live in MolidoBridge.mq5 so remote config cannot see them.

enum ENUM_DEMO_VERDICT
  {
   DEMO_APPROVE = 0,
   DEMO_REDUCE  = 1,
   DEMO_BLOCK   = 2
  };

string   g_demo_syms[DEMO_MAX_SYMS];
datetime g_demo_seen_bar[DEMO_MAX_SYMS];
bool     g_demo_primed[DEMO_MAX_SYMS];
int      g_demo_n = 0;
int      g_demo_entries_today = 0;
datetime g_demo_entries_day = 0;


#define HARD_MAX_RISK_PCT     0.5
#define HARD_MAX_DAILY_PCT    5.0
#define HARD_MAX_DD_PCT       10.0
#define FTMO_DAILY_LOSS_PCT   5.0
#define FTMO_MAX_DD_PCT       10.0
#define DEMO_MAX_ACCOUNTS     16
#define DEMO_START_FILE       "molido_start_equity_"

bool DemoNewsGateNewEntries();
bool DemoNewsTradeActive();

string g_last_verdict        = "—";
string g_last_reason         = "";
string g_last_verdict_symbol = "";
datetime g_last_verdict_at   = 0;

struct DemoCaps
  {
   long   login;
   double risk_pct;
   double daily_pct;
   double max_dd_pct;
   double max_lots;
   int    max_positions;
   int    preset; // 0 scalper, 1 ftmo
  };

DemoCaps g_caps[DEMO_MAX_ACCOUNTS];
int      g_caps_n = 0;
double   g_start_equity = 0.0;

double ClampLimit(const double value, const double lo, const double hi)
  {
   if(value < lo) return(lo);
   if(value > hi) return(hi);
   return(value);
  }

bool DemoCapsFor(const long login, DemoCaps &out)
  {
   for(int i = 0; i < g_caps_n; i++)
      if(g_caps[i].login == login)
        {
         out = g_caps[i];
         return(true);
        }
   return(false);
  }

void ApplyDemoRiskCaps(const string csv)
  {
   g_caps_n = 0;
   if(StringLen(csv) == 0)
      return;
   string rows[];
   int n = StringSplit(csv, ';', rows);
   for(int i = 0; i < n && g_caps_n < DEMO_MAX_ACCOUNTS; i++)
     {
      string p[];
      int c = StringSplit(rows[i], ':', p);
      if(c < 6)
         continue;
      long login = StringToInteger(p[0]);
      if(login <= 0)
         continue;
      DemoCaps cap;
      cap.login = login;
      cap.risk_pct = ClampLimit(StringToDouble(p[1]), 0.01, HARD_MAX_RISK_PCT);
      cap.daily_pct = ClampLimit(StringToDouble(p[2]), 0.1, HARD_MAX_DAILY_PCT);
      cap.max_dd_pct = ClampLimit(StringToDouble(p[3]), 0.0, HARD_MAX_DD_PCT);
      cap.max_lots = ClampLimit(StringToDouble(p[4]), 0.01, DEMO_HARD_MAX_LOTS);
      cap.max_positions = (int)ClampLimit((double)StringToInteger(p[5]), 1, DEMO_MAX_POSITIONS);
      cap.preset = (c > 6 && (p[6] == "ftmo" || p[6] == "FTMO" || p[6] == "1")) ? 1 : 0;
      g_caps[g_caps_n++] = cap;
      Print("MolidoScalper: caps for demo ", login,
            " risk=", DoubleToString(cap.risk_pct, 2),
            "% daily=", DoubleToString(cap.daily_pct, 2),
            "% dd=", DoubleToString(cap.max_dd_pct, 2),
            "% lots=", DoubleToString(cap.max_lots, 2));
     }
  }

double DemoActiveRiskPct()
  {
   DemoCaps cap;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
      return(MathMin(cap.risk_pct, HARD_MAX_RISK_PCT));
   return(MathMin(DEMO_RISK_PCT, HARD_MAX_RISK_PCT));
  }

double DemoActiveDailyPct()
  {
   DemoCaps cap;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
      return(MathMin(cap.daily_pct, HARD_MAX_DAILY_PCT));
   if(RiskPreset == RISK_PRESET_FTMO)
      return(MathMin(FTMO_DAILY_LOSS_PCT, HARD_MAX_DAILY_PCT));
   return(MathMin(DEMO_DAILY_LOSS_PCT, HARD_MAX_DAILY_PCT));
  }

double DemoActiveMaxDdPct()
  {
   DemoCaps cap;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
      return(MathMin(cap.max_dd_pct, HARD_MAX_DD_PCT));
   if(RiskPreset == RISK_PRESET_FTMO)
      return(MathMin(FTMO_MAX_DD_PCT, HARD_MAX_DD_PCT));
   return(0.0);
  }

double DemoActiveMaxLotsCap()
  {
   DemoCaps cap;
   double capv = DEMO_HARD_MAX_LOTS;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap) && cap.max_lots > 0.0)
      capv = MathMin(capv, cap.max_lots);
   if(MaxLots > 0.0 && MaxLots < capv)
      capv = MaxLots;
   return(capv);
  }

int DemoActiveMaxPositions()
  {
   DemoCaps cap;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
      return(cap.max_positions);
   return(DEMO_MAX_POSITIONS);
  }

bool DemoLoadStartEquity(double &start)
  {
   start = 0.0;
   if(FtmoInitialBalance > 0.0)
     {
      start = FtmoInitialBalance;
      g_start_equity = start;
      return(true);
     }
   if(g_start_equity > 0.0)
     {
      start = g_start_equity;
      return(true);
     }
   string path = DEMO_START_FILE + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ".txt";
   int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h != INVALID_HANDLE)
     {
      string raw = FileReadString(h);
      FileClose(h);
      start = StringToDouble(raw);
      if(start > 0.0)
        {
         g_start_equity = start;
         return(true);
        }
     }
   start = AccountInfoDouble(ACCOUNT_EQUITY);
   if(start <= 0.0)
      start = AccountInfoDouble(ACCOUNT_BALANCE);
   if(start <= 0.0)
      return(false);
   h = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h != INVALID_HANDLE)
     {
      FileWriteString(h, DoubleToString(start, 2));
      FileClose(h);
     }
   g_start_equity = start;
   return(true);
  }

bool DemoMaxDdPct(double &dd_pct, double &start_eq)
  {
   dd_pct = 0.0;
   start_eq = 0.0;
   if(DemoActiveMaxDdPct() <= 0.0)
      return(true);
   if(!DemoLoadStartEquity(start_eq))
      return(false);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq <= 0.0 || start_eq <= 0.0)
      return(false);
   dd_pct = 100.0 * (start_eq - eq) / start_eq;
   if(dd_pct < 0.0)
      dd_pct = 0.0;
   return(true);
  }

void DemoScalperStatus(string &status, string &reason)
  {
   status = "ARMED";
   reason = "";
   if(!EnableDemoScalper)
     {
      status = "off";
      reason = "EnableDemoScalper is false";
      return;
     }
   if(!AllowTrading)
     {
      status = "blocked";
      reason = "AllowTrading is off";
      return;
     }
   if(!DemoAccountOk())
     {
      status = "blocked";
      reason = "not an allowed demo login";
      return;
     }
   if(DemoKillEngaged())
     {
      status = "blocked";
      reason = "kill switch";
      return;
     }
   if(!DemoTerminalTradable())
     {
      status = "blocked";
      reason = "AutoTrading or connection";
      return;
     }
   double daily = 0.0;
   if(!DemoDailyPnlPct(daily))
     {
      status = "blocked";
      reason = "missing daily P/L";
      return;
     }
   double loss = -MathMin(0.0, daily);
   if(loss >= DemoActiveDailyPct())
     {
      status = "blocked";
      reason = "daily loss cap";
      return;
     }
   double dd = 0.0, start = 0.0;
   if(DemoActiveMaxDdPct() > 0.0)
     {
      if(!DemoMaxDdPct(dd, start))
        {
         status = "blocked";
         reason = "missing drawdown data";
         return;
        }
      if(dd >= DemoActiveMaxDdPct())
        {
         status = "blocked";
         reason = "max drawdown cap";
         return;
        }
     }
  }


//+------------------------------------------------------------------+
void DemoLog(const string symbol, const string side, const ENUM_DEMO_VERDICT verdict,
             const string reasons, const double lots, const double entry,
             const double sl, const double tp, const double spread, const double atr,
             const double daily_pnl_pct, const double risk_pct, const double size_factor)
  {
   string line = "{";
   line += "\"at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   line += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   line += "\"trade_mode\":" + IntegerToString(AccountInfoInteger(ACCOUNT_TRADE_MODE)) + ",";
   line += "\"symbol\":\"" + symbol + "\",";
   line += "\"side\":\"" + side + "\",";
   line += "\"verdict\":\"" + (verdict == DEMO_APPROVE ? "APPROVE" : verdict == DEMO_REDUCE ? "REDUCE" : "BLOCK") + "\",";
   line += "\"reasons\":\"" + Escape(reasons) + "\",";
   line += "\"lots\":" + DoubleToString(lots, 2) + ",";
   line += "\"entry\":" + DoubleToString(entry, 5) + ",";
   line += "\"sl\":" + DoubleToString(sl, 5) + ",";
   line += "\"tp\":" + DoubleToString(tp, 5) + ",";
   line += "\"spread\":" + DoubleToString(spread, 5) + ",";
   line += "\"atr\":" + DoubleToString(atr, 5) + ",";
   line += "\"daily_pnl_pct\":" + DoubleToString(daily_pnl_pct, 4) + ",";
   line += "\"risk_pct\":" + DoubleToString(risk_pct, 4) + ",";
   line += "\"size_factor\":" + DoubleToString(size_factor, 4) + ",";
   line += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   line += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2);
   line += "}";

   int handle = FileOpen(DEMO_LOG_FILE, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
      handle = FileOpen(DEMO_LOG_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("MolidoScalper: cannot write log (", GetLastError(), ")");
     }
   else
     {
      FileSeek(handle, 0, SEEK_END);
      FileWriteString(handle, line + "\n");
      FileClose(handle);
     }

   int last = FileOpen(DEMO_LAST_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(last != INVALID_HANDLE)
     {
      FileWriteString(last, line);
      FileClose(last);
     }

   g_last_verdict = (verdict == DEMO_APPROVE ? "APPROVE" : verdict == DEMO_REDUCE ? "REDUCE" : "BLOCK");
   g_last_reason = reasons;
   g_last_verdict_symbol = symbol;
   g_last_verdict_at = TimeGMT();

   Print("MolidoScalper: ", g_last_verdict,
         " ", side, " ", symbol, " lots=", DoubleToString(lots, 2),
         " risk=", DoubleToString(risk_pct, 2), "% ", reasons);
  }

//+------------------------------------------------------------------+
bool DemoAccountOk()
  {
   long mode  = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   if(mode != ACCOUNT_TRADE_MODE_DEMO)
      return(false);
   if(login == DEMO_SCALPER_LOGIN)
      return(true);
   DemoCaps cap;
   //--- Other demos are allowed only when the server config listed them.
   return(DemoCapsFor(login, cap));
  }

//+------------------------------------------------------------------+
bool DemoKillEngaged()
  {
   if(ScalperKillSwitch)
      return(true);
   if(FileIsExist(DEMO_KILL_FILE, FILE_COMMON))
      return(true);
   return(false);
  }

//+------------------------------------------------------------------+
bool DemoTerminalTradable()
  {
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
      return(false);
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return(false);
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
      return(false);
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
      return(false);
   return(true);
  }

//+------------------------------------------------------------------+
//| True when this expert may send a new opening deal.               |
//+------------------------------------------------------------------+
bool DemoTradingAllowed()
  {
   if(!AllowTrading)
      return(false);
   if(!DemoAccountOk())
      return(false);
   if(DemoKillEngaged())
      return(false);
   return(true);
  }

//+------------------------------------------------------------------+
double DemoEffectiveMaxLots()
  {
   return(DemoActiveMaxLotsCap());
  }

//+------------------------------------------------------------------+
datetime DemoDayStart()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0;
   dt.min  = 0;
   dt.sec  = 0;
   return(StructToTime(dt));
  }

//+------------------------------------------------------------------+
//| Realized + floating P&L for the current broker day, as a percent |
//| of the implied start-of-day equity. false = data missing.        |
//+------------------------------------------------------------------+
bool DemoDailyPnlPct(double &pnl_pct)
  {
   pnl_pct = 0.0;
   datetime start = DemoDayStart();
   if(start <= 0)
      return(false);
   if(!HistorySelect(start, TimeCurrent()))
      return(false);

   double realized = 0.0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         return(false);
      long typ = HistoryDealGetInteger(ticket, DEAL_TYPE);
      if(typ != DEAL_TYPE_BUY && typ != DEAL_TYPE_SELL)
         continue;
      realized += HistoryDealGetDouble(ticket, DEAL_PROFIT);
      realized += HistoryDealGetDouble(ticket, DEAL_SWAP);
      realized += HistoryDealGetDouble(ticket, DEAL_COMMISSION);
     }

   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(equity <= 0.0 || balance <= 0.0)
      return(false);
   double floating   = equity - balance;
   double daily_pnl  = realized + floating;
   double start_eq   = equity - daily_pnl;
   if(start_eq <= 0.0)
      return(false);
   pnl_pct = 100.0 * daily_pnl / start_eq;
   return(true);
  }

//+------------------------------------------------------------------+
int DemoOpenCount()
  {
   return(PositionsTotal());
  }

//+------------------------------------------------------------------+
bool DemoSymbolOpen(const string symbol)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         return(true); // fail-safe: treat as open / unknown
      if(PositionGetString(POSITION_SYMBOL) == symbol)
         return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
void DemoResetDailyCounter()
  {
   datetime start = DemoDayStart();
   if(g_demo_entries_day != start)
     {
      g_demo_entries_day    = start;
      g_demo_entries_today  = 0;
     }
  }

//+------------------------------------------------------------------+
double DemoAtr(const string symbol, const ENUM_TIMEFRAMES tf, const int period)
  {
   if(period <= 0)
      return(0.0);
   double sum = 0.0;
   for(int i = 1; i <= period; i++)
     {
      double h    = iHigh(symbol, tf, i);
      double l    = iLow(symbol, tf, i);
      double prev = iClose(symbol, tf, i + 1);
      if(h <= 0.0 || l <= 0.0 || prev <= 0.0 || h < l)
         return(0.0);
      double tr = MathMax(h - l, MathMax(MathAbs(h - prev), MathAbs(l - prev)));
      sum += tr;
     }
   return(sum / period);
  }

//+------------------------------------------------------------------+
double DemoEma(const string symbol, const ENUM_TIMEFRAMES tf, const int period, const int shift)
  {
   if(period <= 0 || shift < 0)
      return(0.0);
   int bars = iBars(symbol, tf);
   int need = period * 4 + shift + 2;
   if(bars < need)
      return(0.0);
   int seed_end = shift + period * 3;
   double sum = 0.0;
   for(int i = seed_end + period - 1; i >= seed_end; i--)
     {
      double c = iClose(symbol, tf, i);
      if(c <= 0.0)
         return(0.0);
      sum += c;
     }
   double ema = sum / period;
   double k = 2.0 / (period + 1.0);
   for(int i = seed_end - 1; i >= shift; i--)
     {
      double c = iClose(symbol, tf, i);
      if(c <= 0.0)
         return(0.0);
      ema = c * k + ema * (1.0 - k);
     }
   return(ema);
  }

//+------------------------------------------------------------------+
double DemoSizeLots(const double balance, const double risk_pct, const double sl_distance,
                    const double tick_size, const double tick_value,
                    const double lot_step, const double min_lot, const double symbol_max)
  {
   if(balance <= 0.0 || risk_pct <= 0.0 || sl_distance <= 0.0)
      return(0.0);
   if(tick_size <= 0.0 || tick_value <= 0.0 || lot_step <= 0.0 || min_lot <= 0.0)
      return(0.0);
   double cap = DemoEffectiveMaxLots();
   if(symbol_max > 0.0 && symbol_max < cap)
      cap = symbol_max;
   double risk_money = balance * (risk_pct / 100.0);
   double ticks = sl_distance / tick_size;
   if(ticks <= 0.0)
      return(0.0);
   double raw = risk_money / (ticks * tick_value);
   if(raw > cap)
      raw = cap;
   double lots = MathFloor(raw / lot_step + 1e-12) * lot_step;
   lots = NormalizeDouble(lots, 8);
   while(lots >= min_lot - 1e-12)
     {
      double actual = lots * ticks * tick_value;
      if(actual <= risk_money + 1e-8)
         return(NormalizeDouble(lots, 8));
      lots = NormalizeDouble(lots - lot_step, 8);
     }
   return(0.0);
  }

//+------------------------------------------------------------------+
//| Risk Brain: APPROVE / REDUCE / BLOCK. BLOCK is final.            |
//+------------------------------------------------------------------+
ENUM_DEMO_VERDICT DemoReview(const string symbol, const string side,
                             const double entry, const double sl, const double tp,
                             const double spread, const double atr,
                             double &risk_pct, double &size_factor,
                             double &daily_pnl_pct, string &reasons)
  {
   risk_pct = 0.0;
   size_factor = 0.0;
   daily_pnl_pct = 0.0;
   reasons = "";

   if(!DemoAccountOk())
     {
      reasons = "not an allowed demo account";
      return(DEMO_BLOCK);
     }
   if(DemoKillEngaged())
     {
      reasons = "kill switch is engaged";
      return(DEMO_BLOCK);
     }
   if(!DemoTerminalTradable())
     {
      reasons = "terminal not tradable (AutoTrading, connection or account trade flag)";
      return(DEMO_BLOCK);
     }

   DemoResetDailyCounter();
   if(g_demo_entries_today >= DEMO_MAX_ENTRIES_DAY)
     {
      reasons = "daily entry cap reached";
      return(DEMO_BLOCK);
     }

   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(equity <= 0.0 || balance <= 0.0)
     {
      reasons = "missing: account equity/balance";
      return(DEMO_BLOCK);
     }
   if(entry <= 0.0 || sl <= 0.0 || tp <= 0.0)
     {
      reasons = "missing: entry, stop or target (stop-loss is mandatory)";
      return(DEMO_BLOCK);
     }
   if(side != "buy" && side != "sell")
     {
      reasons = "missing: direction";
      return(DEMO_BLOCK);
     }
   if(!DemoDailyPnlPct(daily_pnl_pct))
     {
      reasons = "missing: daily P&L";
      return(DEMO_BLOCK);
     }

   datetime tick_t = (datetime)SymbolInfoInteger(symbol, SYMBOL_TIME);
   if(tick_t == 0 || (TimeCurrent() - tick_t) > DEMO_STALE_SECONDS)
     {
      reasons = "missing: fresh market data";
      return(DEMO_BLOCK);
     }

   int sign = (side == "buy") ? 1 : -1;
   double risk_dist   = sign * (entry - sl);
   double reward_dist = sign * (tp - entry);
   if(risk_dist <= 0.0 || reward_dist <= 0.0)
     {
      reasons = "stop or target on the wrong side of entry";
      return(DEMO_BLOCK);
     }

   double slip = 0.0;
   double rr = (reward_dist - spread - slip) / (risk_dist + spread + slip);
   if(rr < DEMO_MIN_RR)
     {
      reasons = "net R:R " + DoubleToString(rr, 2) + " < " + DoubleToString(DEMO_MIN_RR, 2);
      return(DEMO_BLOCK);
     }

   if(atr <= 0.0)
     {
      reasons = "missing: ATR";
      return(DEMO_BLOCK);
     }
   if(spread < 0.0)
     {
      reasons = "missing: spread";
      return(DEMO_BLOCK);
     }
   if(spread > DEMO_SPREAD_ATR_FRAC * atr)
     {
      reasons = "spread " + DoubleToString(spread, 5) + " > " +
                DoubleToString(DEMO_SPREAD_ATR_FRAC * 100.0, 0) + "% ATR";
      return(DEMO_BLOCK);
     }
   if(ScalperMaxSpreadPts > 0)
     {
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      if(point <= 0.0)
        {
         reasons = "missing: symbol point size";
         return(DEMO_BLOCK);
        }
      if(spread > ScalperMaxSpreadPts * point)
        {
         reasons = "spread wider than " + IntegerToString(ScalperMaxSpreadPts) + " points";
         return(DEMO_BLOCK);
        }
     }

   double loss = -MathMin(0.0, daily_pnl_pct);
   double daily_cap = DemoActiveDailyPct();
   if(loss >= daily_cap)
     {
      reasons = "daily loss " + DoubleToString(loss, 2) + "% reached limit " +
                DoubleToString(daily_cap, 2) + "%";
      return(DEMO_BLOCK);
     }

   double dd_pct = 0.0, start_eq = 0.0;
   if(DemoActiveMaxDdPct() > 0.0)
     {
      if(!DemoMaxDdPct(dd_pct, start_eq))
        {
         reasons = "missing: overall drawdown";
         return(DEMO_BLOCK);
        }
      if(dd_pct >= DemoActiveMaxDdPct())
        {
         reasons = "max drawdown " + DoubleToString(dd_pct, 2) + "% reached limit " +
                   DoubleToString(DemoActiveMaxDdPct(), 2) + "%";
         return(DEMO_BLOCK);
        }
     }

   size_factor = 1.0;
   if(loss >= DEMO_REDUCE_FRACTION * daily_cap)
     {
      size_factor *= DEMO_REDUCE_FACTOR;
      reasons = "daily loss " + DoubleToString(loss, 2) + "% past reduce threshold";
     }

   if(DemoSymbolOpen(symbol))
     {
      reasons = symbol + " already has an open position";
      return(DEMO_BLOCK);
     }
   int open_n = DemoOpenCount();
   if(open_n < 0)
     {
      reasons = "missing: open positions";
      return(DEMO_BLOCK);
     }
   if(open_n >= DemoActiveMaxPositions())
     {
      reasons = IntegerToString(open_n) + " positions open (cap " + IntegerToString(DemoActiveMaxPositions()) + ")";
      return(DEMO_BLOCK);
     }

   long stops = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0)
     {
      reasons = "missing: symbol point size";
      return(DEMO_BLOCK);
     }
   if(stops > 0 && risk_dist < stops * point)
     {
      reasons = "stop inside the broker minimum; not widened";
      return(DEMO_BLOCK);
     }

   risk_pct = NormalizeDouble(DemoActiveRiskPct() * size_factor, 4);
   if(size_factor < 1.0)
      return(DEMO_REDUCE);
   reasons = (reasons == "" ? "all checks passed" : reasons);
   return(DEMO_APPROVE);
  }

//+------------------------------------------------------------------+
bool DemoParseSymbols()
  {
   g_demo_n = 0;
   string names[];
   int count = StringSplit(ScalperSymbols, ',', names);
   for(int i = 0; i < count && g_demo_n < DEMO_MAX_SYMS; i++)
     {
      string name = names[i];
      StringTrimLeft(name);
      StringTrimRight(name);
      if(StringLen(name) == 0)
         continue;
      g_demo_syms[g_demo_n] = name;
      g_demo_seen_bar[g_demo_n] = 0;
      g_demo_primed[g_demo_n] = false;
      g_demo_n++;
     }
   return(g_demo_n > 0);
  }

//+------------------------------------------------------------------+
bool DemoScalperOnInit()
  {
   if(EnableDemoScalper || AllowTrading)
     {
      if(!DemoAccountOk())
        {
         Print("MolidoScalper: refusing to start trading - not an allowed DEMO account ",
               "(mode=", AccountInfoInteger(ACCOUNT_TRADE_MODE),
               " login=", AccountInfoInteger(ACCOUNT_LOGIN), ")");
         return(false);
        }
     }
   if(EnableDemoScalper)
     {
      if(!DemoParseSymbols())
        {
         Print("MolidoScalper: EnableDemoScalper is on but ScalperSymbols is empty");
         return(false);
        }
      for(int i = 0; i < g_demo_n; i++)
        {
         if(!SymbolSelect(g_demo_syms[i], true))
            Print("MolidoScalper: ", g_demo_syms[i], " not offered by this broker (", GetLastError(), ")");
        }
      Print("MolidoScalper: armed on demo ", DEMO_SCALPER_LOGIN,
            " risk=", DoubleToString(DEMO_RISK_PCT, 2), "% max lots=",
            DoubleToString(DemoEffectiveMaxLots(), 2),
            " daily cap=", DoubleToString(DEMO_DAILY_LOSS_PCT, 2),
            "% max positions=", DEMO_MAX_POSITIONS,
            " AllowTrading=", (AllowTrading ? "true" : "false"),
            " (false = no new orders until you set it)");
      if(DemoKillEngaged())
         Print("MolidoScalper: kill switch is ON - no new orders will be sent");
     }
   return(true);
  }

//+------------------------------------------------------------------+
bool DemoResolveSymbol(const string name, string &resolved)
  {
   resolved = name;
   if(SymbolSelect(resolved, true))
      return(true);
   //--- Some brokers suffix the name (EURUSD. / EURUSDm). Try a short scan.
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++)
     {
      string candidate = SymbolName(i, false);
      if(StringFind(candidate, name) == 0)
        {
         if(SymbolSelect(candidate, true))
           {
            resolved = candidate;
            return(true);
           }
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
bool DemoSignal(const string symbol, string &side, double &entry, double &sl,
                double &tp, double &spread, double &atr, string &why)
  {
   side = "";
   entry = sl = tp = spread = atr = 0.0;
   why = "";

   atr = DemoAtr(symbol, ScalperTF, DEMO_ATR_PERIOD);
   if(atr <= 0.0)
     {
      why = "missing: ATR";
      return(false);
     }
   double e20 = DemoEma(symbol, ScalperTF, 20, 1);
   double e50 = DemoEma(symbol, ScalperTF, 50, 1);
   double close1 = iClose(symbol, ScalperTF, 1);
   double open1  = iOpen(symbol, ScalperTF, 1);
   double close6 = iClose(symbol, ScalperTF, 6);
   if(e20 <= 0.0 || e50 <= 0.0 || close1 <= 0.0 || open1 <= 0.0 || close6 <= 0.0)
     {
      why = "missing: EMA or closed bars";
      return(false);
     }

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     {
      why = "missing: bid/ask";
      return(false);
     }
   spread = tick.ask - tick.bid;

   double mom = (close1 - close6) / atr;
   bool near = MathAbs(close1 - e20) <= 0.5 * atr;
   bool buy  = (e20 > e50 && near && close1 > open1 && mom >= 0.3);
   bool sell = (e20 < e50 && near && close1 < open1 && mom <= -0.3);
   if(buy == sell)
     {
      why = "no scalping consensus (EMA pullback + momentum)";
      return(false);
     }
   side  = buy ? "buy" : "sell";
   entry = buy ? tick.ask : tick.bid;
   sl    = buy ? entry - DEMO_SL_ATR * atr : entry + DEMO_SL_ATR * atr;
   tp    = buy ? entry + DEMO_TP_ATR * atr : entry - DEMO_TP_ATR * atr;
   if(sl <= 0.0 || tp <= 0.0)
     {
      why = "computed stop or target invalid";
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
bool DemoSend(const string symbol, const string side, const double lots,
              const double sl, const double tp)
  {
   if(lots <= 0.0 || sl <= 0.0)
      return(false);
   MqlTradeRequest request;
   MqlTradeResult  result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action       = TRADE_ACTION_DEAL;
   request.symbol       = symbol;
   request.volume       = lots;
   request.type         = (side == "sell") ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price        = (side == "sell") ? SymbolInfoDouble(symbol, SYMBOL_BID)
                                           : SymbolInfoDouble(symbol, SYMBOL_ASK);
   request.sl           = sl;
   request.tp           = tp;
   request.deviation    = MaxSlippagePts;
   request.type_filling = MolidoFilling(symbol);
   request.magic        = DEMO_SCALPER_MAGIC;
   request.comment      = "molido-scalp";

   if(request.price <= 0.0 || request.sl <= 0.0)
      return(false);
   if(!DemoAccountOk() || !DemoTradingAllowed() || !DemoTerminalTradable())
      return(false);

   bool sent = OrderSend(request, result);
   if(!sent || (result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED))
     {
      Print("MolidoScalper: OrderSend failed retcode ", result.retcode, " ", result.comment);
      return(false);
     }

   double sl_gap = MathAbs(request.price - sl);
   double tp_gap = MathAbs(tp - request.price);
   if(sl_gap > 0.0 && result.price > 0.0)
      Reanchor(symbol, side, result.order, result.price, sl_gap, tp_gap);
   Print("MolidoScalper: filled ", side, " ", DoubleToString(lots, 2), " ", symbol,
         " ticket ", result.order);
   g_demo_entries_today++;
   return(true);
  }

//+------------------------------------------------------------------+
void DemoEvaluateSymbol(const string raw_name)
  {
   string symbol;
   if(!DemoResolveSymbol(raw_name, symbol))
     {
      DemoLog(raw_name, "", DEMO_BLOCK, "symbol not available", 0, 0, 0, 0, 0, 0, 0, 0, 0);
      return;
     }

   string side, why;
   double entry, sl, tp, spread, atr;
   if(!DemoSignal(symbol, side, entry, sl, tp, spread, atr, why))
     {
      DemoLog(symbol, side, DEMO_BLOCK, why, 0, entry, sl, tp, spread, atr, 0, 0, 0);
      return;
     }

   double risk_pct = 0.0, size_factor = 0.0, daily_pnl_pct = 0.0;
   string reasons = "";
   ENUM_DEMO_VERDICT verdict = DemoReview(symbol, side, entry, sl, tp, spread, atr,
                                          risk_pct, size_factor, daily_pnl_pct, reasons);
   if(verdict == DEMO_BLOCK)
     {
      DemoLog(symbol, side, verdict, reasons, 0, entry, sl, tp, spread, atr,
              daily_pnl_pct, risk_pct, size_factor);
      return;
     }

   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double lot_step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double sl_dist    = MathAbs(entry - sl);
   double lots = DemoSizeLots(AccountInfoDouble(ACCOUNT_BALANCE), risk_pct, sl_dist,
                              tick_size, tick_value, lot_step, min_lot, max_lot);
   if(lots <= 0.0)
     {
      DemoLog(symbol, side, DEMO_BLOCK, "size failed (missing tick value or budget too small)",
              0, entry, sl, tp, spread, atr, daily_pnl_pct, risk_pct, size_factor);
      return;
     }
   if(lots > DemoEffectiveMaxLots() + 1e-12)
     {
      DemoLog(symbol, side, DEMO_BLOCK, "size exceeds hard max lots",
              lots, entry, sl, tp, spread, atr, daily_pnl_pct, risk_pct, size_factor);
      return;
     }

   //--- Re-check the account and kill switch immediately before the send.
   if(!DemoTradingAllowed() || !DemoTerminalTradable())
     {
      DemoLog(symbol, side, DEMO_BLOCK, "pre-send gate refused (AllowTrading, account, kill or AutoTrading)",
              lots, entry, sl, tp, spread, atr, daily_pnl_pct, risk_pct, size_factor);
      return;
     }

   DemoLog(symbol, side, verdict, reasons, lots, entry, sl, tp, spread, atr,
           daily_pnl_pct, risk_pct, size_factor);

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(!DemoSend(symbol, side, lots, NormalizeDouble(sl, digits), NormalizeDouble(tp, digits)))
      DemoLog(symbol, side, DEMO_BLOCK, "OrderSend failed or was rejected by the broker",
              lots, entry, sl, tp, spread, atr, daily_pnl_pct, risk_pct, size_factor);
  }

//+------------------------------------------------------------------+
void DemoScalperOnTick()
  {
   if(!EnableDemoScalper)
      return;
   if(!AllowTrading)
      return;
   if(!DemoAccountOk())
      return;
   if(DemoNewsGateNewEntries())
      return;
   if(DemoNewsTradeActive())
      return;

   if(g_demo_n <= 0 && !DemoParseSymbols())
      return;

   for(int i = 0; i < g_demo_n; i++)
     {
      string symbol = g_demo_syms[i];
      string resolved;
      if(!DemoResolveSymbol(symbol, resolved))
         continue;
      datetime bar = iTime(resolved, ScalperTF, 0);
      if(bar == 0)
         continue;
      if(!g_demo_primed[i])
        {
         g_demo_seen_bar[i] = bar;
         g_demo_primed[i] = true;
         continue; // wait for the next closed bar after attach
        }
      if(bar == g_demo_seen_bar[i])
         continue;
      g_demo_seen_bar[i] = bar;
      DemoEvaluateSymbol(resolved);
     }
  }

//+------------------------------------------------------------------+
void DemoScalperOnTimer()
  {
   DemoScalperOnTick();
  }

//+------------------------------------------------------------------+
//| Used by the command-file path so a server order cannot bypass    |
//| the demo login, kill switch, mandatory stop, or Risk Brain.      |
//| true = already refused and a result file has been written.       |
//+------------------------------------------------------------------+
bool DemoRefuseUnsafeOpen(const string id, const string symbol, const string side,
                          const double lots, const double sl, const double tp,
                          const double sl_gap)
  {
   if(!DemoAccountOk())
     {
      WriteResult(id, false, 0, 0.0, "refused - not an allowed demo account");
      DemoLog(symbol, side, DEMO_BLOCK, "command refused: not an allowed demo account",
              lots, 0, sl, tp, 0, 0, 0, 0, 0);
      return(true);
     }
   if(DemoKillEngaged())
     {
      WriteResult(id, false, 0, 0.0, "refused - kill switch is engaged");
      DemoLog(symbol, side, DEMO_BLOCK, "command refused: kill switch",
              lots, 0, sl, tp, 0, 0, 0, 0, 0);
      return(true);
     }
   if(!DemoTerminalTradable())
     {
      WriteResult(id, false, 0, 0.0, "refused - terminal not tradable");
      return(true);
     }

   double entry = (side == "sell") ? SymbolInfoDouble(symbol, SYMBOL_BID)
                                   : SymbolInfoDouble(symbol, SYMBOL_ASK);
   double stop = sl;
   double target = tp;
   if(stop <= 0.0 && sl_gap > 0.0 && entry > 0.0)
      stop = (side == "sell") ? entry + sl_gap : entry - sl_gap;
   if(target <= 0.0 && sl_gap > 0.0 && entry > 0.0)
     {
      //--- A command without a target still needs a stop. Target is optional
      //--- for the send, but the Risk Brain needs an R:R, so refuse rather
      //--- than invent one.
     }
   if(stop <= 0.0)
     {
      WriteResult(id, false, 0, 0.0, "refused - stop loss is mandatory");
      DemoLog(symbol, side, DEMO_BLOCK, "command refused: stop loss is mandatory",
              lots, entry, sl, tp, 0, 0, 0, 0, 0);
      return(true);
     }
   if(target <= 0.0)
     {
      WriteResult(id, false, 0, 0.0, "refused - take profit is required for Risk Brain review");
      DemoLog(symbol, side, DEMO_BLOCK, "command refused: missing take profit",
              lots, entry, stop, tp, 0, 0, 0, 0, 0);
      return(true);
     }
   if(lots > DemoEffectiveMaxLots())
     {
      WriteResult(id, false, 0, 0.0,
                  "size " + DoubleToString(lots, 2) + " exceeds hard max lots " +
                  DoubleToString(DemoEffectiveMaxLots(), 2));
      return(true);
     }

   MqlTick tick;
   double spread = 0.0, atr = 0.0;
   if(SymbolInfoTick(symbol, tick) && tick.ask > tick.bid)
      spread = tick.ask - tick.bid;
   atr = DemoAtr(symbol, ScalperTF, DEMO_ATR_PERIOD);

   double risk_pct = 0.0, size_factor = 0.0, daily_pnl_pct = 0.0;
   string reasons = "";
   string review_side = (side == "sell") ? "sell" : "buy";
   ENUM_DEMO_VERDICT verdict = DemoReview(symbol, review_side, entry, stop, target,
                                          spread, atr, risk_pct, size_factor,
                                          daily_pnl_pct, reasons);
   if(verdict == DEMO_BLOCK)
     {
      WriteResult(id, false, 0, 0.0, "Risk Brain BLOCK: " + reasons);
      DemoLog(symbol, review_side, DEMO_BLOCK, "command BLOCK: " + reasons,
              lots, entry, stop, target, spread, atr, daily_pnl_pct, risk_pct, size_factor);
      return(true);
     }

   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double lot_step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double allowed = DemoSizeLots(AccountInfoDouble(ACCOUNT_BALANCE), risk_pct,
                                 MathAbs(entry - stop), tick_size, tick_value,
                                 lot_step, min_lot, max_lot);
   if(allowed <= 0.0 || lots > allowed + 1e-8)
     {
      WriteResult(id, false, 0, 0.0,
                  "refused - lots " + DoubleToString(lots, 2) +
                  " exceed risk-sized cap " + DoubleToString(allowed, 2) +
                  " at " + DoubleToString(risk_pct, 2) + "%");
      DemoLog(symbol, review_side, DEMO_BLOCK, "command size exceeds risk cap",
              lots, entry, stop, target, spread, atr, daily_pnl_pct, risk_pct, size_factor);
      return(true);
     }

   DemoLog(symbol, review_side, verdict, "command " + reasons,
           lots, entry, stop, target, spread, atr, daily_pnl_pct, risk_pct, size_factor);
   return(false);
  }

#endif // MOLIDO_DEMO_SCALPER_MQH

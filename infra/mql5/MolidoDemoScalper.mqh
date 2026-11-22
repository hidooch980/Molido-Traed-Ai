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
//| real account unless LIVE_REAL is explicitly unlocked (allowlist  |
//| AllowedRealLogins, default empty, plus AllowRealAccount=true).   |
//+------------------------------------------------------------------+
#ifndef MOLIDO_DEMO_SCALPER_MQH
#define MOLIDO_DEMO_SCALPER_MQH

#include "MolidoShared.mqh"

#define DEMO_SCALPER_LOGIN      68531270
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
bool DemoDailyPnlPct(double &pnl_pct);
bool ProfileIsProp();
bool ProfileTargetReached();
double ProfileProfitPct(double &start_eq);
double PropClampedRiskPct();
bool DemoSmartAllowEntry(const string symbol, const string side, string &why);
void DemoManagePositions();
bool DemoProtectAllowEntry(const string symbol, const string side, string &why);
void DemoProtectOnTick();
bool AutoRescan();
void AutoRefreshIfDue();
void DemoJournalShot(const string kind, const string symbol, const ulong ticket);
double DemoSafeModeFactor();
bool DemoSafeModeStopped();

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
   double hard = HARD_MAX_RISK_PCT;
   double base = DEMO_RISK_PCT;
   if(ProfileIsProp())
      base = PropClampedRiskPct();
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
     {
      double v = MathMin(cap.risk_pct, hard);
      if(ProfileIsProp())
         v = MathMin(v, base);
      return(v);
     }
   return(MathMin(base, hard));
  }

bool ProfileIsFtmo()
  {
   return(ActiveProfile() == PROFILE_PROP_FTMO);
  }


bool g_rt_scalper = true;
bool g_rt_news    = false;
bool g_rt_trend   = false;
bool g_rt_auto    = false;
bool g_rt_fibo    = false;

void MolidoStratInit()
  {
   g_rt_scalper = UseScalper || (StrategyMode == STRAT_SCALPER);
   g_rt_news    = UseNews || (StrategyMode == STRAT_NEWS);
   g_rt_trend   = UseTrend || (StrategyMode == STRAT_TREND);
   g_rt_auto    = UseAutoSymbol || AutoSymbolMode || (StrategyMode == STRAT_AUTO);
   g_rt_fibo    = UseFibo;
   if(GlobalVariableCheck("Molido.Strat.Scalper"))
      g_rt_scalper = (GlobalVariableGet("Molido.Strat.Scalper") > 0.5);
   if(GlobalVariableCheck("Molido.Strat.News"))
      g_rt_news = (GlobalVariableGet("Molido.Strat.News") > 0.5);
   if(GlobalVariableCheck("Molido.Strat.Trend"))
      g_rt_trend = (GlobalVariableGet("Molido.Strat.Trend") > 0.5);
   if(GlobalVariableCheck("Molido.Strat.Auto"))
      g_rt_auto = (GlobalVariableGet("Molido.Strat.Auto") > 0.5);
   if(GlobalVariableCheck("Molido.Strat.Fibo"))
      g_rt_fibo = (GlobalVariableGet("Molido.Strat.Fibo") > 0.5);
   //--- Profile applies the strategy stack for Master-style use:
   //--- PROP keeps news trading off (avoid-only) even if the toggle is later re-enabled
   //--- via Advanced inputs; the dashboard can still turn legs on/off.
  }

bool StratUseScalper() { return(g_rt_scalper); }
bool StratUseNews()    { return(g_rt_news); }
bool StratUseTrend()   { return(g_rt_trend); }
bool StratUseAuto()    { return(g_rt_auto); }
bool StratUseFibo()    { return(g_rt_fibo); }

void StratSet(const string which, const bool on)
  {
   if(which == "scalper") g_rt_scalper = on;
   if(which == "news")    g_rt_news = on;
   if(which == "trend")   g_rt_trend = on;
   if(which == "auto")    g_rt_auto = on;
   if(which == "fibo")    g_rt_fibo = on;
   if(which == "scalper") GlobalVariableSet("Molido.Strat.Scalper", on ? 1.0 : 0.0);
   if(which == "news")    GlobalVariableSet("Molido.Strat.News", on ? 1.0 : 0.0);
   if(which == "trend")   GlobalVariableSet("Molido.Strat.Trend", on ? 1.0 : 0.0);
   if(which == "auto")    GlobalVariableSet("Molido.Strat.Auto", on ? 1.0 : 0.0);
   if(which == "fibo")    GlobalVariableSet("Molido.Strat.Fibo", on ? 1.0 : 0.0);
  }

bool ProfileIsProp()
  {
   return(ActiveProfile() == PROFILE_PROP_FTMO || ActiveProfile() == PROFILE_PROP_GENERIC);
  }

bool ProfileForceNewsAvoid()
  {
   return(ProfileIsProp() && PropForceNewsAvoid);
  }

bool ProfileUsesWeekendHold()
  {
   return(ProfileIsProp() && PropNoWeekendHold);
  }

string ProfileLabelOf(const ENUM_ACCOUNT_PROFILE p)
  {
   if(p == PROFILE_PROP_FTMO)
      return("FTMO");
   if(p == PROFILE_PROP_GENERIC)
      return("PROP");
   if(p == PROFILE_LIVE_REAL)
      return("LIVE");
   if(p == PROFILE_AUTO)
      return("AUTO");
   if(RiskPreset == RISK_PRESET_FTMO)
      return("Demo/FTMO");
   return("DEMO");
  }

string ProfileName()
  {
   if(MolidoRealBlocked())
      return(Tr("real_unsupported"));
   string name = ProfileLabelOf(ActiveProfile());
   if(RehearsalMode && ProfileIsProp())
      name = name + " " + Tr("rehearsal");
   if(AccountProfile == PROFILE_AUTO)
      name = name + " " + Tr("auto_tag");
   else if(AccountProfile != ActiveProfile())
      name = name + " " + Tr("manual_tag");
   return(name);
  }

string DemoDetectedLine()
  {
   if(MolidoRealBlocked())
      return(Tr("real_unsupported"));
   string line = Tr("detected") + " " + ProfileLabelOf(DetectedProfile());
   string srv = AccountInfoString(ACCOUNT_SERVER);
   if(StringLen(srv) > 0)
      line = line + "  " + srv;
   if(AccountProfile != PROFILE_AUTO && AccountProfile != ActiveProfile())
      line = line + "  (" + Tr("manual_override") + ")";
   return(line);
  }

double ProfileProfitTargetPct()
  {
   if(ActiveProfile() == PROFILE_PROP_FTMO)
     {
      double v = PropProfitTargetPct;
      if(v < 0.0) v = 0.0;
      if(v > 30.0) v = 30.0;
      return(v);
     }
   if(ActiveProfile() == PROFILE_PROP_GENERIC)
     {
      double v = PropGenericProfitTargetPct;
      if(v < 0.0) v = 0.0;
      if(v > 50.0) v = 50.0;
      return(v);
     }
   return(0.0);
  }

int ProfileMinTradingDays()
  {
   if(ActiveProfile() == PROFILE_PROP_FTMO)
     {
      int v = PropMinTradingDays;
      if(v < 0) v = 0;
      if(v > 30) v = 30;
      return(v);
     }
   if(ActiveProfile() == PROFILE_PROP_GENERIC)
     {
      int v = PropGenericMinTradingDays;
      if(v < 0) v = 0;
      if(v > 30) v = 30;
      return(v);
     }
   return(0);
  }

double DemoActiveDailyPct()
  {
   DemoCaps cap;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
      return(MathMin(cap.daily_pct, HARD_MAX_DAILY_PCT));
   if(ActiveProfile() == PROFILE_PROP_FTMO || RiskPreset == RISK_PRESET_FTMO)
      return(MathMin(FTMO_DAILY_LOSS_PCT, HARD_MAX_DAILY_PCT));
   if(ActiveProfile() == PROFILE_PROP_GENERIC)
     {
      double v = PropGenericDailyLossPct;
      if(v < 0.1) v = 0.1;
      if(v > HARD_MAX_DAILY_PCT) v = HARD_MAX_DAILY_PCT;
      return(v);
     }
   return(MathMin(DEMO_DAILY_LOSS_PCT, HARD_MAX_DAILY_PCT));
  }

double DemoActiveMaxDdPct()
  {
   DemoCaps cap;
   if(DemoCapsFor(AccountInfoInteger(ACCOUNT_LOGIN), cap))
      return(MathMin(cap.max_dd_pct, HARD_MAX_DD_PCT));
   if(ActiveProfile() == PROFILE_PROP_FTMO || RiskPreset == RISK_PRESET_FTMO)
      return(MathMin(FTMO_MAX_DD_PCT, HARD_MAX_DD_PCT));
   if(ActiveProfile() == PROFILE_PROP_GENERIC)
     {
      double v = PropGenericMaxDdPct;
      if(v < 0.0) v = 0.0;
      if(v > HARD_MAX_DD_PCT) v = HARD_MAX_DD_PCT;
      return(v);
     }
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
   string prefix = DEMO_START_FILE;
   if(RehearsalMode && ProfileIsProp())
      prefix = "molido_rehearsal_start_";
   string path = prefix + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ".txt";
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

double ProfileProfitPct(double &start_eq)
  {
   start_eq = 0.0;
   if(!DemoLoadStartEquity(start_eq) || start_eq <= 0.0)
      return(0.0);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   return(100.0 * (eq - start_eq) / start_eq);
  }

bool ProfileTargetReached()
  {
   double target = ProfileProfitTargetPct();
   if(target <= 0.0)
      return(false);
   double start_eq = 0.0;
   return(ProfileProfitPct(start_eq) >= target);
  }

double PropClampedRiskPct()
  {
   double v = PropRiskPct;
   if(v < 0.05) v = 0.05;
   if(v > HARD_MAX_RISK_PCT) v = HARD_MAX_RISK_PCT;
   return(v);
  }

double PropDailyBufferFracClamped()
  {
   double v = PropDailyBufferFrac;
   if(v < 0.50) v = 0.50;
   if(v > 1.0) v = 1.0;
   return(v);
  }

double PropDdBufferFracClamped()
  {
   double v = PropDdBufferFrac;
   if(v < 0.50) v = 0.50;
   if(v > 1.0) v = 1.0;
   return(v);
  }

double DemoEffectiveDailyStopPct()
  {
   double cap = DemoActiveDailyPct();
   if(ProfileIsProp())
      return(cap * PropDailyBufferFracClamped());
   return(cap);
  }

double DemoEffectiveDdStopPct()
  {
   double cap = DemoActiveMaxDdPct();
   if(cap <= 0.0)
      return(0.0);
   if(ProfileIsProp())
      return(cap * PropDdBufferFracClamped());
   return(cap);
  }

double ProfileTargetProgress()
  {
   double target = ProfileProfitTargetPct();
   if(target <= 0.0)
      return(0.0);
   double start_eq = 0.0;
   return(ProfileProfitPct(start_eq) / target);
  }

double ProfilePaceFactor()
  {
   if(!ProfileIsProp())
      return(1.0);
   if(ProfileTargetReached())
      return(0.0);
   double p = ProfileTargetProgress();
   double tight = PropPaceTightFrac;
   double start = PropPaceStartFrac;
   if(tight < 0.55) tight = 0.55;
   if(tight > 0.99) tight = 0.99;
   if(start < 0.40) start = 0.40;
   if(start > tight) start = tight;
   if(p >= tight)
      return(0.25);
   if(p >= start)
      return(0.50);
   return(1.0);
  }

bool ProfileConsistencyBlocked(string &why)
  {
   why = "";
   if(!ProfileIsProp())
      return(false);
   double target = ProfileProfitTargetPct();
   double share = PropConsistencyDayShare;
   if(target <= 0.0 || share <= 0.0)
      return(false);
   if(share > 100.0) share = 100.0;
   double day_pct = 0.0;
   if(!DemoDailyPnlPct(day_pct))
      return(false);
   if(day_pct <= 0.0)
      return(false);
   double cap_today = target * (share / 100.0);
   if(day_pct >= cap_today)
     {
      why = "consistency: today's profit " + DoubleToString(day_pct, 2) +
            "% reached " + DoubleToString(share, 0) + "% of the target";
      return(true);
     }
   return(false);
  }

bool ProfileNearDdBreach(const double planned_risk_pct, string &why)
  {
   why = "";
   if(!ProfileIsProp())
      return(false);
   double daily = 0.0;
   if(!DemoDailyPnlPct(daily))
     {
      why = "missing daily P/L near DD check";
      return(true);
     }
   double loss = -MathMin(0.0, daily);
   double daily_stop = DemoEffectiveDailyStopPct();
   if(loss >= daily_stop)
     {
      why = "daily DD buffer reached (" +
            DoubleToString(PropDailyBufferFracClamped() * 100.0, 0) + "% of the daily limit)";
      return(true);
     }
   double dd = 0.0, start_eq = 0.0;
   double dd_stop = DemoEffectiveDdStopPct();
   if(dd_stop > 0.0)
     {
      if(!DemoMaxDdPct(dd, start_eq))
        {
         why = "missing drawdown near DD check";
         return(true);
        }
      if(dd >= dd_stop)
        {
         why = "overall DD buffer reached (" +
               DoubleToString(PropDdBufferFracClamped() * 100.0, 0) + "% of max DD)";
         return(true);
        }
     }
   double room = daily_stop - loss;
   if(dd_stop > 0.0)
     {
      double dd_room = dd_stop - dd;
      if(dd_room < room)
         room = dd_room;
     }
   if(planned_risk_pct > 0.0 && room <= planned_risk_pct * 1.25)
     {
      why = "too close to a DD breach for this risk";
      return(true);
     }
   return(false);
  }

string ProfileChallengeState()
  {
   if(!ProfileIsProp())
      return(ProfileName());
   if(ProfileTargetReached())
      return("TARGET HIT");
   string why;
   if(ProfileNearDdBreach(PropClampedRiskPct(), why))
      return("NEAR DD");
   if(ProfileConsistencyBlocked(why))
      return("CONSISTENCY");
   if(ProfilePaceFactor() < 1.0)
      return("PACING");
   return("ON TRACK");
  }

int ProfileTradingDays()
  {
   double start_eq = 0.0;
   datetime from = 0;
   if(DemoLoadStartEquity(start_eq))
      from = TimeCurrent() - 120 * 86400;
   //--- Fall back to a 120-day window if the start file has no timestamp.
   if(!HistorySelect(from, TimeCurrent() + 1))
      return(0);
   int days[];
   ArrayResize(days, 0);
   int n = 0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)HistoryDealGetInteger(ticket, DEAL_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      MqlDateTime dt;
      TimeToStruct(t, dt);
      int key = dt.year * 1000 + dt.day_of_year;
      bool seen = false;
      for(int k = 0; k < n; k++)
         if(days[k] == key)
           {
            seen = true;
            break;
           }
      if(seen)
         continue;
      ArrayResize(days, n + 1);
      days[n] = key;
      n++;
     }
   return(n);
  }

bool ProfileInWeekendHoldWindow()
  {
   if(!ProfileUsesWeekendHold())
      return(false);
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   if(dt.day_of_week == 6)
      return(true);
   if(dt.day_of_week == 0 && dt.hour < 22)
      return(true);
   if(dt.day_of_week == 5 && dt.hour >= 21)
      return(true);
   return(false);
  }

void ProfileWeekendFlatten()
  {
   if(!ProfileInWeekendHoldWindow())
      return;
   if(!DemoAccountOk())
      return;
   if(!DemoTerminalTradable())
      return;
   static uint last_ms = 0;
   uint now = GetTickCount();
   if(last_ms != 0 && (now - last_ms) < 5000)
      return;
   last_ms = now;
   int total = PositionsTotal();
   for(int i = total - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      string symbol = PositionGetString(POSITION_SYMBOL);
      long kind = PositionGetInteger(POSITION_TYPE);
      double volume = PositionGetDouble(POSITION_VOLUME);
      if(volume <= 0.0)
         continue;
      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_DEAL;
      req.symbol = symbol;
      req.volume = volume;
      req.position = ticket;
      req.deviation = MaxSlippagePts;
      req.magic = DEMO_SCALPER_MAGIC;
      req.comment = "molido-weekend";
      if(kind == POSITION_TYPE_BUY)
        {
         req.type = ORDER_TYPE_SELL;
         req.price = SymbolInfoDouble(symbol, SYMBOL_BID);
        }
      else
        {
         req.type = ORDER_TYPE_BUY;
         req.price = SymbolInfoDouble(symbol, SYMBOL_ASK);
        }
      req.type_filling = MolidoFilling(symbol);
      if(req.price <= 0.0)
         continue;
      if(OrderSend(req, res))
         Print("MolidoScalper: weekend flatten ", symbol, " ticket ", ticket,
               " retcode ", res.retcode);
     }
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
      reason = (ActiveProfile() == PROFILE_LIVE_REAL
                ? "LIVE_REAL hard-locked"
                : "login not in allowlist");
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
   if(loss >= DemoEffectiveDailyStopPct())
     {
      status = "blocked";
      reason = (ProfileIsProp() ? "daily DD buffer" : "daily loss cap");
      return;
     }
   double dd = 0.0, start = 0.0;
   if(DemoEffectiveDdStopPct() > 0.0)
     {
      if(!DemoMaxDdPct(dd, start))
        {
         status = "blocked";
         reason = "missing drawdown data";
         return;
        }
      if(dd >= DemoEffectiveDdStopPct())
        {
         status = "blocked";
         reason = (ProfileIsProp() ? "overall DD buffer" : "max drawdown cap");
         return;
        }
     }
   string cwhy = "";
   if(ProfileConsistencyBlocked(cwhy))
     {
      status = "blocked";
      reason = cwhy;
      return;
     }
   if(ProfileTargetReached())
     {
      status = "blocked";
      reason = "profit target reached";
      return;
     }
   if(ProfileInWeekendHoldWindow())
     {
      status = "blocked";
      reason = "weekend hold window";
      return;
     }
   if(DemoSafeModeStopped())
     {
      status = "blocked";
      reason = "safe mode until tomorrow";
      return;
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
   if(MolidoRealBlocked() || (mode == ACCOUNT_TRADE_MODE_REAL && !MOLIDO_REAL_SUPPORTED))
      return(false);
   if(MolidoIsTester())
     {
      if(ActiveProfile() == PROFILE_LIVE_REAL)
         return(false);
      if(mode == ACCOUNT_TRADE_MODE_REAL)
         return(false);
      return(true);
     }
   if(login <= 0)
      return(false);
   if(ActiveProfile() == PROFILE_LIVE_REAL)
     {
      //--- Hard lock: never trade a real account unless every unlock is set.
      if(mode != ACCOUNT_TRADE_MODE_REAL)
         return(false);
      if(!AllowRealAccount)
         return(false);
      return(LoginInRealAllowlist(login));
     }
   //--- DEMO and PROP profiles never trade a real-money account.
   if(mode == ACCOUNT_TRADE_MODE_REAL)
      return(false);
   if(ActiveProfile() == PROFILE_DEMO)
     {
      if(mode != ACCOUNT_TRADE_MODE_DEMO)
         return(false);
      return(LoginInAllowlist(login));
     }
   //--- Prop challenges are demo or contest, never real.
   if(mode != ACCOUNT_TRADE_MODE_DEMO && mode != ACCOUNT_TRADE_MODE_CONTEST)
      return(false);
   return(LoginInAllowlist(login));
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

void DemoKillSet(const bool on)
  {
   if(on)
     {
      int handle = FileOpen(DEMO_KILL_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
      if(handle == INVALID_HANDLE)
        {
         Print("MolidoScalper: cannot write kill switch file (", GetLastError(), ")");
         return;
        }
      FileWriteString(handle, "kill\n");
      FileClose(handle);
      Print("MolidoScalper: kill switch file engaged from the dashboard");
      return;
     }
   if(ScalperKillSwitch)
     {
      Print("MolidoScalper: cannot clear kill; ScalperKillSwitch input is on");
      return;
     }
   if(FileIsExist(DEMO_KILL_FILE, FILE_COMMON))
     {
      if(!FileDelete(DEMO_KILL_FILE, FILE_COMMON))
         Print("MolidoScalper: could not delete kill switch file (", GetLastError(), ")");
      else
         Print("MolidoScalper: kill switch file cleared from the dashboard");
     }
  }

//+------------------------------------------------------------------+
bool DemoTerminalTradable()
  {
   if(!MolidoIsTester() && !TerminalInfoInteger(TERMINAL_CONNECTED))
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
   if(!MolidoLinkHealthy())
      return(false);
   return(true);
  }

//+------------------------------------------------------------------+
double DemoEffectiveMaxLots()
  {
   double cap = DemoActiveMaxLotsCap();
#ifdef MOLIDO_EXPERT_UI
   cap = ExpertTightenMaxLots(cap);
#endif
   return(cap);
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
   return(CoordOpenCount());
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
        {
#ifdef MOLIDO_EXPERT_UI
         lots = ExpertClampLots(g_ex_lots_symbol, lots, sl_distance,
                                tick_size, tick_value, lot_step, min_lot);
#endif
         return(NormalizeDouble(lots, 8));
        }
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
      reasons = (ActiveProfile() == PROFILE_LIVE_REAL
                 ? "LIVE_REAL hard-locked (AllowRealAccount + AllowedRealLogins)"
                 : "login not in allowlist or wrong trade mode");
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
   if(ScalperMaxSpreadPts > 0 || SpreadSpikeMult > 1.0)
     {
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      if(point <= 0.0)
        {
         reasons = "missing: symbol point size";
         return(DEMO_BLOCK);
        }
      double pts = spread / point;
      if(ScalperMaxSpreadPts > 0 && pts > ScalperMaxSpreadPts)
        {
         reasons = "spread wider than " + IntegerToString(ScalperMaxSpreadPts) + " points";
         return(DEMO_BLOCK);
        }
      if(SpreadSpikeLookback >= 3 && SpreadSpikeMult > 1.0)
        {
         static string spike_sym = "";
         static double spike_avg = 0.0;
         static int    spike_n = 0;
         if(spike_sym != symbol)
           {
            spike_sym = symbol;
            spike_avg = pts;
            spike_n = 1;
           }
         else
           {
            int n = SpreadSpikeLookback;
            if(n > 80) n = 80;
            if(spike_n < n) spike_n++;
            spike_avg += (pts - spike_avg) / spike_n;
           }
         if(spike_avg > 0.0 && pts > spike_avg * SpreadSpikeMult && pts > spike_avg + 2.0)
           {
            reasons = "spread spike " + DoubleToString(pts, 1) + " vs avg " + DoubleToString(spike_avg, 1);
            return(DEMO_BLOCK);
           }
        }
     }

   if(ProfileTargetReached())
     {
      reasons = "profit target reached - new entries blocked";
      return(DEMO_BLOCK);
     }
   if(ProfileInWeekendHoldWindow())
     {
      reasons = "weekend hold window - no new entries";
      return(DEMO_BLOCK);
     }

   double loss = -MathMin(0.0, daily_pnl_pct);
   double daily_cap = DemoActiveDailyPct();
   double daily_stop = DemoEffectiveDailyStopPct();
   if(loss >= daily_stop)
     {
      reasons = "daily loss " + DoubleToString(loss, 2) + "% reached buffer " +
                DoubleToString(daily_stop, 2) + "% (limit " + DoubleToString(daily_cap, 2) + "%)";
      return(DEMO_BLOCK);
     }

   double dd_pct = 0.0, start_eq = 0.0;
   double dd_stop = DemoEffectiveDdStopPct();
   if(dd_stop > 0.0)
     {
      if(!DemoMaxDdPct(dd_pct, start_eq))
        {
         reasons = "missing: overall drawdown";
         return(DEMO_BLOCK);
        }
      if(dd_pct >= dd_stop)
        {
         reasons = "drawdown " + DoubleToString(dd_pct, 2) + "% reached buffer " +
                   DoubleToString(dd_stop, 2) + "% (limit " +
                   DoubleToString(DemoActiveMaxDdPct(), 2) + "%)";
         return(DEMO_BLOCK);
        }
     }

   string cwhy = "";
   if(ProfileConsistencyBlocked(cwhy))
     {
      reasons = cwhy;
      return(DEMO_BLOCK);
     }

   size_factor = 1.0;
   size_factor *= ProfilePaceFactor();
   if(size_factor <= 0.0)
     {
      reasons = "profit target reached - new entries blocked";
      return(DEMO_BLOCK);
     }
   if(size_factor < 1.0)
      reasons = "profit-target pacing x" + DoubleToString(size_factor, 2);
   if(loss >= DEMO_REDUCE_FRACTION * daily_stop)
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

   double safe = DemoSafeModeFactor();
   if(safe <= 0.0 || DemoSafeModeStopped())
     {
      reasons = "safe mode: stop until next day after consecutive losses";
      return(DEMO_BLOCK);
     }
   size_factor *= safe;
   if(size_factor <= 0.0)
     {
      reasons = "safe mode reduced size to zero";
      return(DEMO_BLOCK);
     }
   risk_pct = NormalizeDouble(DemoActiveRiskPct() * size_factor, 4);
   string ddwhy = "";
   if(ProfileNearDdBreach(risk_pct, ddwhy))
     {
      reasons = ddwhy;
      return(DEMO_BLOCK);
     }
   if(!CoordCanOpen(DemoActiveMaxPositions()))
     {
      reasons = "account-wide position cap reached (coordinator)";
      return(DEMO_BLOCK);
     }
#ifdef MOLIDO_EXPERT_UI
   string ewhy0 = "";
   if(!ExpertPolicyAllow(symbol, side, entry, sl, tp, ewhy0))
     {
      reasons = ewhy0;
      return(DEMO_BLOCK);
     }
   risk_pct = ExpertTightenRiskPct(symbol, risk_pct);
#endif
   if(size_factor < 1.0)
      return(DEMO_REDUCE);
   reasons = (reasons == "" ? "all checks passed" : reasons);
   return(DEMO_APPROVE);
  }

//+------------------------------------------------------------------+
bool DemoParseSymbols()
  {
   if(MolidoIsTester())
     {
      g_demo_n = 1;
      g_demo_syms[0] = _Symbol;
      g_demo_seen_bar[0] = 0;
      g_demo_primed[0] = false;
      return(true);
     }
   if(StratUseAuto() && AutoRescan())
      return(true);
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
   MolidoStratInit();
   if(EnableDemoScalper || AllowTrading)
     {
      if(!DemoAccountOk())
        {
         Print("MolidoScalper: trading locked - profile=", ProfileName(),
               " mode=", AccountInfoInteger(ACCOUNT_TRADE_MODE),
               " login=", AccountInfoInteger(ACCOUNT_LOGIN),
               (ActiveProfile() == PROFILE_LIVE_REAL
                ? " (LIVE_REAL stays hard-locked until AllowRealAccount=true and the login is in AllowedRealLogins)"
                : " (login must be in AllowedLogins; real accounts are refused)"));
         //--- Keep the expert running so the dashboard can show the lock.
        }
      else
         Print("MolidoScalper: profile ", ProfileName(),
               " login ", AccountInfoInteger(ACCOUNT_LOGIN), " allowed");
     }
   if(EnableDemoScalper)
     {
      if(!DemoParseSymbols())
        {
         Print("MolidoScalper: EnableDemoScalper is on but no symbols were selected ",
               "(AutoSymbolMode found none and ScalperSymbols is empty)");
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

bool DemoTrendSignal(const string symbol, string &side, double &entry, double &sl,
                     double &tp, double &spread, double &atr, string &why)
  {
   side = "";
   entry = sl = tp = spread = atr = 0.0;
   why = "";
   atr = DemoAtr(symbol, PERIOD_M15, DEMO_ATR_PERIOD);
   if(atr <= 0.0)
     {
      why = "missing: M15 ATR";
      return(false);
     }
   double m15_e20 = DemoEma(symbol, PERIOD_M15, 20, 1);
   double m15_e50 = DemoEma(symbol, PERIOD_M15, 50, 1);
   double h1_e20  = DemoEma(symbol, PERIOD_H1, 20, 1);
   double h1_e50  = DemoEma(symbol, PERIOD_H1, 50, 1);
   double close1  = iClose(symbol, PERIOD_M15, 1);
   double open1   = iOpen(symbol, PERIOD_M15, 1);
   if(m15_e20 <= 0.0 || m15_e50 <= 0.0 || h1_e20 <= 0.0 || h1_e50 <= 0.0 || close1 <= 0.0)
     {
      why = "missing: M15/H1 trend EMAs";
      return(false);
     }
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
     {
      why = "missing: bid/ask";
      return(false);
     }
   spread = tick.ask - tick.bid;
   bool up = (h1_e20 > h1_e50 && m15_e20 > m15_e50 && close1 > m15_e20 && close1 > open1);
   bool dn = (h1_e20 < h1_e50 && m15_e20 < m15_e50 && close1 < m15_e20 && close1 < open1);
   if(up == dn)
     {
      why = "no M15/H1 trend alignment";
      return(false);
     }
   side  = up ? "buy" : "sell";
   entry = up ? tick.ask : tick.bid;
   sl    = up ? entry - 1.5 * atr : entry + 1.5 * atr;
   tp    = up ? entry + 2.5 * atr : entry - 2.5 * atr;
#ifdef MOLIDO_EXPERT_UI
   ExpertEnsureMinTp(side, entry, sl, tp);
#endif
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
   if(!CoordCanOpen(DemoActiveMaxPositions()))
      return(false);
   if(!CoordLock())
      return(false);

   bool sent = OrderSend(request, result);
   CoordUnlock();
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
   DemoJournalShot("open", symbol, result.order);
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
   bool got = false;
   if(StratUseTrend())
      got = DemoTrendSignal(symbol, side, entry, sl, tp, spread, atr, why);
   if(!got && StratUseFibo())
      got = DemoFiboSignal(symbol, side, entry, sl, tp, spread, atr, why);
   if(!got && StratUseScalper())
      got = DemoSignal(symbol, side, entry, sl, tp, spread, atr, why);
   if(!got && !StratUseTrend() && !StratUseFibo() && !StratUseScalper())
      why = "no entry strategy enabled";
   if(!got)
     {
      DemoLog(symbol, side, DEMO_BLOCK, why, 0, entry, sl, tp, spread, atr, 0, 0, 0);
      return;
     }

   if(!DemoSmartAllowEntry(symbol, side, why))
     {
      DemoLog(symbol, side, DEMO_BLOCK, why, 0, entry, sl, tp, spread, atr, 0, 0, 0);
      return;
     }
   if(!DemoProtectAllowEntry(symbol, side, why))
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
#ifdef MOLIDO_EXPERT_UI
   ExpertSetLotsSymbol(symbol);
#endif
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
   if(DemoAccountOk())
     {
      DemoManagePositions();
      ProfileWeekendFlatten();
      DemoProtectOnTick();
     }
   else
      DemoProtectOnTick();
   if(!AllowTrading)
      return;
#ifdef MOLIDO_EXPERT_UI
   if(ExpertStopNew() || !ExpertAutoOn() || !ExpertInstanceMayTrade()) return;
      return;
#endif
   if(!DemoAccountOk())
      return;
   if(DemoNewsGateNewEntries())
      return;
   if(StratUseNews())
      DemoNewsTradeActive();
   if(StratUseNews() && !StratUseScalper() && !StratUseTrend() && !StratUseFibo() && !StratUseAuto())
      return;
   if(DemoNewsTradeActive() && !StratUseScalper() && !StratUseTrend() && !StratUseFibo())
      return;

   if(StratUseAuto())
      AutoRefreshIfDue();
   if(g_demo_n <= 0 && !DemoParseSymbols())
      return;

   for(int i = 0; i < g_demo_n; i++)
     {
      string symbol = g_demo_syms[i];
      string resolved;
      if(!DemoResolveSymbol(symbol, resolved))
         continue;
      ENUM_TIMEFRAMES tf = ((StratUseTrend() || StratUseFibo()) && !StratUseScalper() ? PERIOD_M15 : ScalperTF);
      datetime bar = iTime(resolved, tf, 0);
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
#ifdef MOLIDO_EXPERT_UI
   ExpertSetLotsSymbol(symbol);
#endif
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

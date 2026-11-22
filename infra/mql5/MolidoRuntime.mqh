//+------------------------------------------------------------------+
//| MolidoRuntime.mqh - shared expert body compiled into every EA.   |
//| Do not attach this file; attach one of the Molido_*.mq5 files.   |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| MolidoBridge.mq5 - publish account, symbols and bars as files.    |
//|                                                                  |
//| MetaTrader's Python package is Windows-only and this terminal     |
//| runs under Wine, so the obvious path - import MetaTrader5 and     |
//| call initialize() - returns IPC timeout. The named-pipe transport |
//| it relies on is not something Wine implements well enough, and no |
//| amount of arguing with initialize() changes that.                 |
//|                                                                  |
//| A file is a transport Wine implements perfectly. This service     |
//| runs inside the terminal, where the data already is, and writes   |
//| it to the common Files folder on a timer. The Linux side reads    |
//| that directory directly. It is slower than an in-process call and |
//| completely reliable, which is the correct trade for hourly bars.  |
//|                                                                  |
//| Demo scalper (v1.43): may place orders ONLY on ACCOUNT_TRADE_     |
//| MODE_DEMO login 68531270. Defaults are armed (AllowTrading and    |
//| EnableDemoScalper on) for this demo. Every new order is gated by a|
//| Risk Brain (APPROVE/REDUCE/BLOCK) with hard limits: 0.5% risk,    |
//| 2% daily loss, 2.0 lots, 2 positions, mandatory stop. Missing     |
//| data, a kill switch, or a BLOCK means no trade. Real accounts     |
//| are refused even if AllowRealAccount is later flipped.            |
//| v1.43 adds regime/session/trend filters, BE+trailing, loss        |
//| cooldown, ConfigUrl consensus veto (never looser), and a larger   |
//| sectioned dashboard with font scale, kill button, and trade marks.|
//+------------------------------------------------------------------+
//--- An expert rather than a service. A service starts only from the
//--- Navigator panel, and that panel does not render its expanders under
//--- Wine, so there is no way to click the thing. An expert can be named
//--- in a startup config file, which the terminal reads from the command
//--- line - no window, no click, and it survives every restart.

//--- Written to the common folder rather than the terminal's own, so the path
//--- does not move when the terminal is reinstalled or run portable.
#define FLAGS (FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON)

enum ENUM_ACCOUNT_PROFILE
  {
   PROFILE_DEMO         = 0,  // personal demo: 0.5% risk, 2% daily
   PROFILE_PROP_FTMO    = 1,  // 5% daily / 10% max DD, target, days, weekend
   PROFILE_PROP_GENERIC = 2,  // configurable DD / profit target
   PROFILE_LIVE_REAL    = 3,  // real money (blocked on Master; Live EA still locked)
   PROFILE_AUTO         = 4   // detect from trade mode, broker name, allowlist
  };

input group "Advanced (no need to change)"
input ENUM_ACCOUNT_PROFILE AccountProfile = MOLIDO_DEFAULT_PROFILE;  // AUTO = detect; manual override only

enum ENUM_MOLIDO_LANG
  {
   LANG_FA = 0,  // Persian (default)
   LANG_EN = 1,
   LANG_AR = 2,
   LANG_TR = 3
  };
input ENUM_MOLIDO_LANG Language = LANG_FA;  // dashboard language; falls back to English if the font cannot render

//--- How often to republish. Hourly bars do not reward a tighter loop, and a
//--- service rewriting the same files every second would keep a disk busy for
//--- nothing.
input int RefreshSeconds = 20;
//--- How many closed bars to publish per symbol and timeframe.
input int BarCount = 500;
//--- The same, for the minute timeframes, which are published so the rule can
//--- be *measured* at speed before it is ever traded at speed.
//---
//--- Deliberately smaller. Four timeframes across every Market Watch symbol is
//--- 176 files a cycle, and this expert shares four cores with the platform it
//--- feeds - a full 500 bars of M1 per symbol is disk work for history the
//--- rule never looks back that far into. 240 M1 bars is four hours, which is
//--- more than the lookback needs and bounded.
input int IntradayBarCount = 240;

//--- Symbols to add to Market Watch on start, comma separated.
//---
//--- Taken from `molido_available.json`, which the expert writes on start -
//--- not guessed. Three of the first six names guessed from outside did not
//--- exist here: this broker has no XAGEUR at all, and its oil is BRENT and
//--- WTI rather than the XTIUSD/XBRUSD other brokers use. Each wrong guess
//--- fails silently, and silence looks exactly like a broker that lacks the
//--- instrument.
//---
//--- The expert publishes what Market Watch shows, and Market Watch shows
//--- whatever the terminal shipped with - ten majors on this deployment, no
//--- metals and no energy. The broker offers far more; nothing was asking for
//--- it. `SymbolSelect` asks, and a symbol the broker does not have is
//--- reported by name rather than failing the start: a typo and an instrument
//--- the broker genuinely lacks need different fixes.
//---
//--- The crosses below are not decoration. The rule ranks an instrument
//--- against its peers at one instant and refuses to rank fewer than twenty -
//--- below that the "most extended" member is just the shape of a small
//--- sample. The bridge was publishing nine of the ranked universe, so the
//--- broker-price arm of the forward measurement could never rank anything
//--- and would have reported "recorded: 0" every cycle for months, which
//--- reads as a quiet system rather than a measurement that cannot run.
//---
//--- These twenty-eight are the intersection of the ranked universe with what
//--- `molido_available.json` says this broker actually offers. Read from the
//--- file, not guessed - the last round of guessing cost three silent
//--- failures.
//---
//--- Narrowed on 13 September 2026 to the twenty traded instruments
//--- (docs/TRADED-UNIVERSE.md) plus four crosses. Every symbol in Market Watch
//--- costs the terminal a history thread that polls at about 1% of a core
//--- under Wine even with the market shut; at forty-one symbols five terminals
//--- held the host's run queue near sixty on eight cores, and the collector
//--- took 260 seconds to write two bars.
//---
//--- The four crosses are the margin, not decoration. `record_cycle` narrows
//--- the public snapshot to what the terminals publish only when at least
//--- twenty remain, and gold is ranked there as GCFUT rather than XAUUSD - so
//--- the twenty traded alone would leave nineteen, and the narrowing would
//--- quietly switch itself off.
input string ExtraSymbols = "XAUUSD,EURUSD,GBPUSD,USDJPY,GBPJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,EURJPY,AUDJPY,EURGBP,CADJPY,CHFJPY,EURCHF,EURAUD,EURCAD,GBPCHF,GBPAUD,AUDNZD,NZDJPY,EURNZD,GBPCAD,AUDCAD";

//--- Hide Market Watch symbols that are not in ExtraSymbols. Selecting only
//--- ever adds, so without this a running terminal keeps every symbol it was
//--- ever given. The terminal refuses to hide a symbol with an open position
//--- or a chart, and that refusal is logged and left alone.
input bool HideUnlistedSymbols = true;

//--- Runtime copies of the tunable inputs. They start as the inputs and may be
//--- replaced by the platform's remote config (symbols, refresh, bar counts).
//--- The safety inputs - AllowTrading, AllowRealAccount, AllowedLogins,
//--- AllowedRealLogins, AccountProfile, EnableDemoScalper and
//--- ScalperKillSwitch, RehearsalMode, AutoUpdateEnabled - have no runtime
//--- copy, so no remote message can change them.
#include "MolidoShared.mqh"
#ifndef MOLIDO_EA_VERSION
#define MOLIDO_EA_VERSION "1.46"
#endif
int    g_RefreshSeconds   = 20;
int    g_BarCount         = 500;
int    g_IntradayBarCount = 240;
string g_Symbols          = "";
int    g_TickCount        = 0;   // 0 = no tick files; the platform may turn it on

//--- Demo scalper hooks. Defined in MolidoDemoScalper.mqh, included at the
//--- end of this file so they can call helpers declared above them.
bool DemoTradingAllowed();
bool DemoScalperOnInit();
void DemoScalperOnTick();
void DemoScalperOnTimer();
bool DemoRefuseUnsafeOpen(const string id, const string symbol, const string side,
                          const double lots, const double sl, const double tp,
                          const double sl_gap);
void ApplyDemoRiskCaps(const string csv);
void MolidoDashOnInit();
void MolidoDashOnTick();
void MolidoDashOnTimer();
void MolidoDashOnDeinit();
void MolidoDashOnChartEvent(const int id, const long &lparam,
                            const double &dparam, const string &sparam);
bool MolidoLinkHealthy();
ENUM_ACCOUNT_PROFILE ActiveProfile();
ENUM_ACCOUNT_PROFILE DetectedProfile();
void RefreshActiveProfile();
bool MolidoRealBlocked();
#ifdef MOLIDO_EXPERT_UI
bool ExpertAutoOn();
bool ExpertStopNew();
void ExpertBridgeOnTimer();
bool ExpertInstanceOnInit();
void ExpertInstanceOnDeinit();
void ExpertInstanceHeartbeat();
bool ExpertInstanceMayTrade();
#endif
void MolidoI18nInit();
string Tr(const string key);
bool MolidoRequestUpdate();
void MolidoWriteSettingsSnapshot();

int      g_publish_status = 0;   // 0 idle, 1 ok, -1 fail
int      g_config_status  = 0;
datetime g_initTime       = 0;
ENUM_ACCOUNT_PROFILE g_detected_profile  = PROFILE_DEMO;
ENUM_ACCOUNT_PROFILE g_effective_profile = PROFILE_DEMO;
bool     g_real_unsupported = false;
datetime g_lastServerOk   = 0;
string   g_update_version = "";
string   g_update_sha256  = "";
string   g_update_gate    = "";
bool     g_update_ready   = false;
bool     g_update_pending = false;
datetime g_last_publish_at = 0;
string   g_news_server_csv = "";
string   g_consensus_csv   = "";
string   g_ranking_csv     = "";

string TimeframeName(ENUM_TIMEFRAMES period)
  {
   switch(period)
     {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      default:         return "UNKNOWN";
     }
  }

//+------------------------------------------------------------------+
//| Escape a string for JSON. Symbol descriptions carry quotes and     |
//| backslashes often enough that skipping this produces a file the    |
//| reader rejects, which looks like a connection fault rather than a  |
//| formatting one.                                                    |
//+------------------------------------------------------------------+
string Escape(string text)
  {
   string out = "";
   for(int i = 0; i < StringLen(text); i++)
     {
      ushort c = StringGetCharacter(text, i);
      if(c == '"' || c == '\\')
        {
         out += "\\";
         out += ShortToString(c);
        }
      else if(c >= 32)
         out += ShortToString(c);
     }
   return out;
  }

//+------------------------------------------------------------------+
//| The account, as the broker's server currently sees it.             |
//|                                                                    |
//| Balance and equity are both published because the difference is    |
//| the open book, and a challenge is failed on equity. Publishing     |
//| only balance would hide the drawdown that ends the account.        |
//+------------------------------------------------------------------+
//--- Built rather than written, so the file and the HTTP publish carry
//--- byte-identical content. Two builders for one payload is two payloads
//--- that agree today and disagree after the next field is added to one.
string AccountJson()
  {
   string json = "{";
   json += "\"published_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   json += "\"server\":\"" + Escape(AccountInfoString(ACCOUNT_SERVER)) + "\",";
   json += "\"company\":\"" + Escape(AccountInfoString(ACCOUNT_COMPANY)) + "\",";
   json += "\"currency\":\"" + Escape(AccountInfoString(ACCOUNT_CURRENCY)) + "\",";
   json += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   json += "\"margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN), 2) + ",";
   json += "\"free_margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + ",";
   json += "\"leverage\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)) + ",";
   //--- Reported rather than assumed. An account the broker has set to
   //--- read-only looks identical to a live one until an order is refused.
   json += "\"trade_allowed\":" + (AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) ? "true" : "false") + ",";
   json += "\"trade_mode\":" + IntegerToString(AccountInfoInteger(ACCOUNT_TRADE_MODE)) + ",";
   json += "\"connected\":" + (TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false");
   json += "}";
   return json;
  }

void WriteAccount()
  {
   int handle = FileOpen("molido_account.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;
   FileWriteString(handle, AccountJson());
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| Symbol specifications for everything in Market Watch.              |
//|                                                                    |
//| Contract size and tick value are the two numbers that turn a risk  |
//| in R into a position size. Getting them from the broker rather     |
//| than assuming the textbook values is the difference between a 1%   |
//| risk and a 10% one on any instrument that is not a standard lot.   |
//+------------------------------------------------------------------+
void WriteSymbols()
  {
   int handle = FileOpen("molido_symbols.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;

   string json = "{\"published_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"symbols\":[";

   int total = SymbolsTotal(true);
   for(int i = 0; i < total; i++)
     {
      string name = SymbolName(i, true);
      if(i > 0)
         json += ",";
      json += "{";
      json += "\"name\":\"" + Escape(name) + "\",";
      json += "\"description\":\"" + Escape(SymbolInfoString(name, SYMBOL_DESCRIPTION)) + "\",";
      json += "\"digits\":" + IntegerToString(SymbolInfoInteger(name, SYMBOL_DIGITS)) + ",";
      json += "\"point\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_POINT), 8) + ",";
      json += "\"contract_size\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_TRADE_CONTRACT_SIZE), 2) + ",";
      json += "\"tick_value\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_TRADE_TICK_VALUE), 8) + ",";
      json += "\"tick_size\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_TRADE_TICK_SIZE), 8) + ",";
      json += "\"volume_min\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_VOLUME_MIN), 4) + ",";
      json += "\"volume_max\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_VOLUME_MAX), 4) + ",";
      json += "\"volume_step\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_VOLUME_STEP), 4) + ",";
      json += "\"bid\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_BID), 8) + ",";
      json += "\"ask\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_ASK), 8) + ",";
      //--- The nearest a stop may sit, as this broker allows it. A request
      //--- inside this distance is rejected outright, which reads downstream
      //--- as a broken order rather than as a stop the venue will not hold.
      json += "\"stops_level\":" + IntegerToString(SymbolInfoInteger(name, SYMBOL_TRADE_STOPS_LEVEL)) + ",";
      //--- What this expert will let a fill wander from the quote. The
      //--- backend charges it against the stop distance before deciding a
      //--- trade is affordable, so publishing it keeps that arithmetic true
      //--- when somebody changes the input here.
      json += "\"slippage_points\":" + IntegerToString(MaxSlippagePts);
      json += "}";
     }
   json += "]}";

   FileWriteString(handle, json);
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| Closed bars for one symbol and timeframe, oldest first.            |
//|                                                                    |
//| Index 0 is skipped. That bar has not closed, so its high, low and  |
//| close are provisional, and a provisional bar stored beside settled |
//| ones is exactly how a backtest reads a price that was never        |
//| available at that moment.                                          |
//+------------------------------------------------------------------+
void WriteBars(string symbol, ENUM_TIMEFRAMES period)
  {
   //--- Only what the terminal already holds. CopyRates on a series that
   //--- has not synchronised yet triggers a download and waits for it, and
   //--- on this host that wait was fourteen minutes with the timer held the
   //--- whole way: the heartbeat stopped, the account went stale, and a
   //--- funded, trading terminal read as absent. A symbol that is not ready
   //--- is skipped this pass and picked up on a later one, once it is.
   if(!SeriesInfoInteger(symbol, period, SERIES_SYNCHRONIZED))
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int wanted = (period <= PERIOD_M5) ? g_IntradayBarCount : g_BarCount;
   int copied = CopyRates(symbol, period, 1, wanted, rates);
   if(copied <= 0)
      return;

   string file = "molido_bars_" + symbol + "_" + TimeframeName(period) + ".csv";
   int handle = FileOpen(file, FLAGS | FILE_CSV, ',');
   if(handle == INVALID_HANDLE)
      return;

   FileWrite(handle, "event_time", "open", "high", "low", "close", "volume");
   for(int i = copied - 1; i >= 0; i--)
     {
      FileWrite(handle,
                TimeToString(rates[i].time, TIME_DATE | TIME_SECONDS),
                DoubleToString(rates[i].open, 8),
                DoubleToString(rates[i].high, 8),
                DoubleToString(rates[i].low, 8),
                DoubleToString(rates[i].close, 8),
                IntegerToString(rates[i].tick_volume));
     }
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| Open positions, so the guardian can compare what the broker holds  |
//| with what this system believes it holds. A position at the broker  |
//| that the system did not open is the louder finding: every risk     |
//| figure is understated until it is explained.                       |
//+------------------------------------------------------------------+
//--- The array alone, without the envelope. The file wants a wrapper with a
//--- timestamp; the HTTP publish carries its own, and nesting one inside the
//--- other would make the backend unwrap a field it did not ask for.
string PositionsArray()
  {
   string json = "[";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(i > 0)
         json += ",";
      json += "{";
      json += "\"ticket\":" + IntegerToString((long)ticket) + ",";
      json += "\"symbol\":\"" + Escape(PositionGetString(POSITION_SYMBOL)) + "\",";
      json += "\"side\":\"" + (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "buy" : "sell") + "\",";
      json += "\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 4) + ",";
      json += "\"price_open\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), 8) + ",";
      json += "\"stop\":" + DoubleToString(PositionGetDouble(POSITION_SL), 8) + ",";
      json += "\"target\":" + DoubleToString(PositionGetDouble(POSITION_TP), 8) + ",";
      json += "\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2);
      json += "}";
     }
   json += "]";
   return json;
  }

void WritePositions()
  {
   int handle = FileOpen("molido_positions.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;
   string json = "{\"published_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"positions\":" + PositionsArray() + "}";
   FileWriteString(handle, json);
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| A heartbeat with a timestamp, written last.                        |
//|                                                                    |
//| Written last on purpose: a reader that trusts it knows every other |
//| file in this cycle finished. Its absence or staleness is also the  |
//| only way the Linux side can tell "the service is publishing zeros" |
//| from "the service stopped an hour ago", and those are opposite     |
//| facts about a feed.                                                |
//+------------------------------------------------------------------+
void WriteDailySummary()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0;
   dt.min  = 0;
   dt.sec  = 0;
   datetime start = StructToTime(dt);
   HistorySelect(start, TimeCurrent());
   int trades = 0, wins = 0, losses = 0;
   double gross_win = 0.0, gross_loss = 0.0, daily_pnl = 0.0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if(!IsMolidoMagic((long)HistoryDealGetInteger(ticket, DEAL_MAGIC)))
         continue;
      int entry = (int)HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;
      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                 + HistoryDealGetDouble(ticket, DEAL_SWAP)
                 + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      daily_pnl += pnl;
      trades++;
      if(pnl >= 0.0) { wins++; gross_win += pnl; }
      else { losses++; gross_loss += -pnl; }
     }
   double pf = (gross_loss > 0.0 ? gross_win / gross_loss : (gross_win > 0.0 ? 99.0 : 0.0));
   double wr = (trades > 0 ? 100.0 * wins / trades : 0.0);
   string json = "{";
   json += "\"date\":\"" + TimeToString(start, TIME_DATE) + "\",";
   json += "\"published_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   json += "\"ea\":\"" + MOLIDO_EA_NAME + "\",";
   json += "\"ea_version\":\"" + MOLIDO_EA_VERSION + "\",";
   json += "\"profile\":" + IntegerToString((int)ActiveProfile()) + ",";
   json += "\"profile_detected\":" + IntegerToString((int)DetectedProfile()) + ",";
   json += "\"real_unsupported\":" + (MolidoRealBlocked() ? "true" : "false") + ",";
   json += "\"rehearsal\":" + ((RehearsalMode && (ActiveProfile() == PROFILE_PROP_FTMO || ActiveProfile() == PROFILE_PROP_GENERIC)) ? "true" : "false") + ",";
   json += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   json += "\"daily_pnl\":" + DoubleToString(daily_pnl, 2) + ",";
   json += "\"trades\":" + IntegerToString(trades) + ",";
   json += "\"wins\":" + IntegerToString(wins) + ",";
   json += "\"losses\":" + IntegerToString(losses) + ",";
   json += "\"win_rate\":" + DoubleToString(wr, 1) + ",";
   json += "\"profit_factor\":" + DoubleToString(pf, 2) + ",";
   json += "\"open_positions\":" + IntegerToString((int)PositionsTotal()) + ",";
   json += "\"connected\":" + (TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false") + ",";
   json += "\"link_healthy\":" + (MolidoLinkHealthy() ? "true" : "false");
   json += "}";
   int handle = FileOpen("molido_daily_summary.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;
   FileWriteString(handle, json);
   FileClose(handle);
  }

void WriteHeartbeat(int cycle)
  {
   int handle = FileOpen("molido_heartbeat.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;
   string json = "{";
   json += "\"published_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"cycle\":" + IntegerToString(cycle) + ",";
   json += "\"connected\":" + (TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false") + ",";
   json += "\"trade_allowed\":" + (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ? "true" : "false") + ",";
   json += "\"build\":" + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)) + ",";
   json += "\"refresh_seconds\":" + IntegerToString(g_RefreshSeconds) + ",";
   json += "\"ea_version\":\"" + MOLIDO_EA_VERSION + "\",";
   json += "\"places_orders\":" + ((AllowTrading && EnableDemoScalper) ? "true" : "false");
   json += "}";
   FileWriteString(handle, json);
   FileClose(handle);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(!AccountAllowed())
      return INIT_FAILED;
   g_initTime = TimeCurrent();
   MolidoI18nInit();
   g_RefreshSeconds = RefreshSeconds;
   g_BarCount = BarCount;
   g_IntradayBarCount = IntradayBarCount;
   g_Symbols = ExtraSymbols;
   Print("MolidoBridge ", MOLIDO_EA_VERSION, ": publishing every ", g_RefreshSeconds, "s to the common Files folder");
   //--- One timer rather than OnTick: this publishes on a clock, not on price
   //--- movement. Tying it to ticks would stop publishing exactly when the
   //--- market goes quiet, which is when a stale-feed check needs it most.
   PublishAvailableSymbols();
   FetchRemoteConfig(true);
   SelectExtraSymbols();
   if(!DemoScalperOnInit())
      return INIT_FAILED;
#ifdef MOLIDO_EXPERT_UI
   ExpertInstanceOnInit();
#endif
   EventSetTimer(g_RefreshSeconds);
   Publish();
   MolidoDashOnInit();
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Ask the terminal to show the symbols this system wants.          |
//|                                                                  |
//| Every name is reported either way. A symbol that silently fails  |
//| to appear looks exactly like one the broker does not offer, and  |
//| those need different fixes - one is a typo, the other is a       |
//| different broker.                                                |
//+------------------------------------------------------------------+
void SelectExtraSymbols()
  {
   if(StringLen(g_Symbols) == 0)
      return;

   string names[];
   int count = StringSplit(g_Symbols, ',', names);
   for(int i = 0; i < count; i++)
     {
      string name = names[i];
      StringTrimLeft(name);
      StringTrimRight(name);
      if(StringLen(name) == 0)
         continue;

      if(SymbolSelect(name, true))
         Print("MolidoBridge: added ", name, " to Market Watch");
      else
         Print("MolidoBridge: ", name, " not offered by this broker (", GetLastError(), ")");
      names[i] = name;
     }

   if(!HideUnlistedSymbols)
      return;

   //--- Backwards: hiding a symbol shifts every index after it.
   for(int j = SymbolsTotal(true) - 1; j >= 0; j--)
     {
      string shown = SymbolName(j, true);
      bool listed = false;
      for(int k = 0; k < count && !listed; k++)
         listed = (names[k] == shown);
      if(listed)
         continue;
      if(SymbolSelect(shown, false))
         Print("MolidoBridge: hid ", shown, " from Market Watch");
      else
         Print("MolidoBridge: kept ", shown, " - the terminal refused to hide it (", GetLastError(), ")");
     }
  }

//+------------------------------------------------------------------+
//| Write every symbol the broker offers, not just the visible ones. |
//|                                                                  |
//| The terminal reported 94 symbols while Market Watch showed ten,   |
//| and asking for XAUUSD did nothing - almost certainly because this |
//| broker calls it something else. Guessing the name from the        |
//| outside is how an hour goes into a typo. This writes the real     |
//| list once so the guessing stops.                                  |
//+------------------------------------------------------------------+
void PublishAvailableSymbols()
  {
   int handle = FileOpen("molido_available.json", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("MolidoBridge: could not write the available-symbol list (", GetLastError(), ")");
      return;
     }

   int total = SymbolsTotal(false);
   string json = "{\"published_at\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\",";
   json += "\"count\":" + IntegerToString(total) + ",\"symbols\":[";
   for(int i = 0; i < total; i++)
     {
      if(i > 0)
         json += ",";
      json += "\"" + SymbolName(i, false) + "\"";
     }
   json += "]}";

   FileWriteString(handle, json);
   FileClose(handle);
   Print("MolidoBridge: published ", total, " available symbols");
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
#ifdef MOLIDO_EXPERT_UI
   ExpertInstanceOnDeinit();
#endif
   MolidoDashOnDeinit();
   Print("MolidoBridge: stopped, reason ", reason);
  }

//+------------------------------------------------------------------+
//| Order execution                                                   |
//|                                                                   |
//| The bridge published prices for weeks and could not place a       |
//| single order. `api_can_place_orders` was false, the only broker   |
//| adapter was a paper one that fills nothing, and the autopilot     |
//| reported `would_send_live_orders: true` - a policy verdict about  |
//| a path that did not exist.                                        |
//|                                                                   |
//| One property matters more than every other here: a request must   |
//| execute at most once. A duplicated OrderSend opens a second real  |
//| position, and no amount of care further up recovers from it. So   |
//| the sequence is: claim the request by renaming it, then send,     |
//| then write the result. A crash between claim and send loses the   |
//| order, which is recoverable. A crash between send and result      |
//| leaves an unexplained position, which reconcile() is for. Neither |
//| can double it.                                                    |
//+------------------------------------------------------------------+
//--- Turned on deliberately, for a demo account, after the refusal path was
//--- watched working: a request was claimed, refused with "AllowTrading is off
//--- on the expert", and no order was sent.
//---
//--- MaxLots stays small and still refuses rather than clamps. The account
//--- gate on the autopilot reads the terminal's own trade_mode and treats an
//--- absent field as real money, so this switch alone cannot reach a funded
//--- account - and MOLIDO_ALLOW_REAL_MONEY_ORDERS is a separate refusal on top
//--- of that.
input bool   AllowTrading    = true;   // armed for demo 68531270; hard account gate still applies
//--- Expert-side real-money guard (added 2026-11-14, agents stage 2).
//--- The backend already refuses real accounts (autopilot.account_gate and
//--- MOLIDO_ALLOW_REAL_MONEY_ORDERS); this is the same refusal one layer down,
//--- so a backend defect alone cannot reach a funded account. Every trade
//--- request - open, close and amend - is refused while the terminal reports
//--- ACCOUNT_TRADE_MODE_REAL and this stays false. Changing it is an owner
//--- (L5) decision. Needs a recompile on each terminal to take effect.
input bool   AllowRealAccount = false;

//--- Explicit login allowlists. Demo/prop accounts use AllowedLogins
//--- (default 68531270). LIVE_REAL uses AllowedRealLogins, which starts
//--- empty and is hard-locked until the user fills it later AND sets
//--- AllowRealAccount=true and AccountProfile=LIVE_REAL. Neither list is
//--- remotely writable.
input string AllowedLogins     = "68531270";
input string AllowedRealLogins = "";

input double            PropProfitTargetPct        = 10.0;  // FTMO challenge default
input int               PropMinTradingDays         = 4;
input bool              PropNoWeekendHold          = true;
input bool              PropForceNewsAvoid         = true;  // challenge news rule
input double            PropGenericDailyLossPct    = 5.0;
input double            PropGenericMaxDdPct        = 10.0;
input double            PropGenericProfitTargetPct = 8.0;
input int               PropGenericMinTradingDays  = 0;
input double            PropRiskPct                = 0.25;  // conservative prop default
input double            PropDailyBufferFrac        = 0.80;  // stop at 80% of daily limit
input double            PropDdBufferFrac           = 0.80;  // stop at 80% of max DD
input double            PropPaceStartFrac          = 0.70;  // slow down near the target
input double            PropPaceTightFrac          = 0.90;
input double            PropConsistencyDayShare    = 40.0;  // max share of target in one day
input bool              RehearsalMode              = MOLIDO_DEFAULT_REHEARSAL;

bool LoginInCsv(const string csv, const long login)
  {
   if(login <= 0)
      return(false);
   int n = StringLen(csv);
   if(n <= 0)
      return(false);
   string token = "";
   for(int i = 0; i <= n; i++)
     {
      ushort ch = (i < n) ? StringGetCharacter(csv, i) : ',';
      if(ch == ',' || ch == ';' || ch == ' ' || ch == '\t' || i == n)
        {
         if(StringLen(token) > 0)
           {
            long value = StringToInteger(token);
            if(value == login)
               return(true);
            token = "";
           }
        }
      else
         token += ShortToString(ch);
     }
   return(false);
  }

bool LoginInAllowlist(const long login)
  {
   return(LoginInCsv(AllowedLogins, login));
  }

bool LoginInRealAllowlist(const long login)
  {
   return(LoginInCsv(AllowedRealLogins, login));
  }

bool MolidoHayHas(const string hay, const string needle)
  {
   if(StringLen(needle) <= 0)
      return(false);
   string h = hay;
   string n = needle;
   StringToUpper(h);
   StringToUpper(n);
   return(StringFind(h, n) >= 0);
  }

string MolidoBrokerHay()
  {
   return(AccountInfoString(ACCOUNT_SERVER) + " " + AccountInfoString(ACCOUNT_COMPANY));
  }

bool MolidoLooksLikeFtmo(const string hay)
  {
   return(MolidoHayHas(hay, "FTMO"));
  }

bool MolidoLooksLikeProp(const string hay)
  {
   if(MolidoLooksLikeFtmo(hay))
      return(true);
   string names[] = {
      "FUNDED NEXT", "FUNDEDNEXT", "THE5ERS", "THE 5%ERS", "5ERS",
      "E8 MARKETS", "E8 FUNDING", "E8FUNDING", "TOPSTEP",
      "APEX TRADER", "FUNDED TRADING PLUS", "THE FUNDED TRADER",
      "SMART PROP", "SURGETRADER", "SURGE TRADER", "LUX TRADING",
      "MAVEN TRADING", "FUNDINGPIPS", "FUNDING PIPS", "GOAT FUNDED",
      "CITY TRADERS IMPERIUM", "FINTOKEI", "BLUE GUARDIAN",
      "FUNDED ENGINEER", "INSTANT FUNDING", "PROP FIRM", "PROP TRADING",
      "EVALUATION ACCOUNT", "CHALLENGE ACCOUNT"
   };
   for(int i = 0; i < ArraySize(names); i++)
      if(MolidoHayHas(hay, names[i]))
         return(true);
   return(false);
  }

ENUM_ACCOUNT_PROFILE DetectAccountProfile()
  {
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   string hay = MolidoBrokerHay();
   //--- Real accounts are never treated as demo/prop. Master blocks them
   //--- outright; the Live EA may still use its hard-lock path later.
   if(mode == ACCOUNT_TRADE_MODE_REAL)
      return(PROFILE_LIVE_REAL);
   if(MolidoLooksLikeFtmo(hay))
      return(PROFILE_PROP_FTMO);
   if(MolidoLooksLikeProp(hay))
      return(PROFILE_PROP_GENERIC);
   if(mode == ACCOUNT_TRADE_MODE_CONTEST)
      return(PROFILE_PROP_GENERIC);
   if(mode == ACCOUNT_TRADE_MODE_DEMO)
     {
      if(LoginInAllowlist(login))
         return(PROFILE_DEMO);
      //--- Uncertain demo: safest is prop rules.
      return(PROFILE_PROP_GENERIC);
     }
   if(mode == ACCOUNT_TRADE_MODE_REAL)
      return(PROFILE_LIVE_REAL);
   return(PROFILE_PROP_GENERIC);
  }

bool MolidoRealBlocked()
  {
   return(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL
          && !MOLIDO_REAL_SUPPORTED);
  }

void RefreshActiveProfile()
  {
   g_detected_profile = DetectAccountProfile();
   g_real_unsupported = MolidoRealBlocked();
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL)
     {
      //--- Never allow a manual override to downgrade a real account.
      g_effective_profile = PROFILE_LIVE_REAL;
      return;
     }
   if(AccountProfile != PROFILE_AUTO)
      g_effective_profile = AccountProfile;
   else
      g_effective_profile = g_detected_profile;
  }

ENUM_ACCOUNT_PROFILE ActiveProfile()
  {
   return(g_effective_profile);
  }

ENUM_ACCOUNT_PROFILE DetectedProfile()
  {
   return(g_detected_profile);
  }


bool AccountAllowed()
  {
   RefreshActiveProfile();
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   if(mode == ACCOUNT_TRADE_MODE_REAL)
     {
      if(MolidoRealBlocked())
        {
         Print("Molido: Real account not supported yet - no trading on this expert");
         return true;
        }
      if(!AllowRealAccount || !LoginInRealAllowlist(login))
        {
         Print("MolidoBridge: REAL account hard-locked - need AllowRealAccount=true ",
               "and this login in AllowedRealLogins (default empty)");
         return false;
        }
     }
   else if(!MolidoIsTester() && !LoginInAllowlist(login))
     {
      Print("MolidoBridge: login ", login, " is not in AllowedLogins - refusing");
      return false;
     }
   Print("MolidoBridge: AllowTrading=", (AllowTrading ? "true" : "false"),
         " profile=", AccountProfile,
         " (false AllowTrading = read-only, command files are refused)");
   return true;
  }

//--- Hard ceiling, whatever is asked. Raised from 0.10 after the first live
//--- sizing run: 0.25% of a 10,000 account behind a real stop came out at 0.26
//--- lots on USDCAD, which is correct risk and would have been refused by an
//--- arbitrary ceiling.
//---
//--- Raised again to 5.00 for the practice account, which is deliberately
//--- being run hard: at 2% of a 10,000 account the same USDCAD stop sizes to
//--- about 2.1 lots, and a 0.50 ceiling would have silently refused every
//--- order while looking like the risk setting had been applied. A ceiling
//--- that fires on correct sizing teaches nothing.
//---
//--- It is still a fat-finger stop, not a risk control - the risk control is
//--- the equity-and-stop calculation in the backend, and this only catches the
//--- case where that calculation has gone wrong. Both are behind the account
//--- gate, which reads the terminal's own trade_mode and refuses real money.
//---
//--- Raised from 5.00 on 14 September 2026 (owner's decision). At 8% fleet
//--- risk the backend sized USDCAD at 8.2-8.9 lots and EURCAD at 6.0 - about
//--- 1.9% of balance each, correctly - and this cap refused all nine: CAD is
//--- worth ~0.72 per tick, so the same dollars at risk need more lots than a
//--- USD-quoted pair. Ten still catches a sizing error an order of magnitude
//--- out, which is what this line exists for.
input double MaxLots         = 2.00;
input int    MaxSlippagePts  = 30;

enum ENUM_MOLIDO_STRATEGY
  {
   STRAT_SCALPER = 0,
   STRAT_NEWS    = 1,
   STRAT_TREND   = 2,
   STRAT_AUTO    = 3
  };
input ENUM_MOLIDO_STRATEGY StrategyMode     = MOLIDO_DEFAULT_STRATEGY;
input bool              UseScalper         = MOLIDO_USE_SCALPER;
input bool              UseNews            = MOLIDO_USE_NEWS;
input bool              UseTrend           = MOLIDO_USE_TREND;
input bool              UseAutoSymbol      = MOLIDO_USE_AUTO;
input bool              UseFibo            = MOLIDO_USE_FIBO;  // off until OOS is positive
input ENUM_TIMEFRAMES   FiboSwingTF        = PERIOD_M15;
input int               FiboSwingStrength  = 3;
input int               FiboLookbackBars   = 80;
input bool              FiboUse382         = true;
input bool              FiboUse50          = true;
input bool              FiboUse618         = true;

input bool              EnableDemoScalper   = true;           // armed for demo 68531270
input bool              AutoSymbolMode      = MOLIDO_DEFAULT_AUTO;
input int               AutoSymbolTopN      = MOLIDO_DEFAULT_TOPN;
input int               AutoSymbolMaxScan   = 60;
input string            ScalperSymbols      = "XAUUSD,EURUSD"; // fallback if auto finds none
input ENUM_TIMEFRAMES   ScalperTF           = PERIOD_M5;
input int               ScalperMaxSpreadPts = 40;             // 0 = ATR filter only
input int               SpreadSpikeLookback = 20;
input double            SpreadSpikeMult     = 2.0;            // skip if spread > average * this
input bool              ScalperKillSwitch   = false;          // input kill switch

enum ENUM_RISK_PRESET
  {
   RISK_PRESET_SCALPER = 0,   // 0.5% risk, 2% daily loss
   RISK_PRESET_FTMO    = 1    // also enforce 5% daily / 10% max DD
  };
input ENUM_RISK_PRESET  RiskPreset          = RISK_PRESET_SCALPER;
input double            FtmoInitialBalance  = 0;              // 0 = snapshot first equity

enum ENUM_NEWS_MODE
  {
   NEWS_AVOID = 0,            // no new entries around high-impact news
   NEWS_TRADE = 1             // breakout after release, reduced size
  };
input ENUM_NEWS_MODE    NewsMode            = MOLIDO_DEFAULT_NEWS;
input int               NewsAvoidMinutes    = 15;
input int               NewsTradeWindowMinutes = 10;
input bool              NewsTightenSL       = true;

input bool              UseRegimeFilter     = true;
input int               AtrPctMin           = 20;
input int               AtrPctMax           = 80;
input int               AdxPeriod           = 14;
input int               AdxMin              = 18;
input bool              UseSessionFilter    = true;
input int               LondonOpenHourGMT   = 7;
input int               LondonCloseHourGMT  = 16;
input int               NewYorkOpenHourGMT  = 12;
input int               NewYorkCloseHourGMT = 21;
input bool              UseTrendConfirm     = true;
input bool              UseBreakEven        = true;
input double            BeAtrMult           = 1.0;
input bool              UseTrailing         = true;
input double            TrailStartAtr       = 1.5;
input double            TrailAtrMult        = 1.0;
input int               CooldownMinutes     = 30;
input bool              RequireServerConsensus = false;

input int               SafeModeReduceAfter    = 2;      // 0 = off
input double            SafeModeReduceFactor   = 0.5;
input int               SafeModeStopAfter      = 3;      // 0 = off; stop until next day
input bool              UsePartialTP           = true;
input double            PartialTpClosePct      = 50.0;   // close half at TP1
input bool              UseCorrelationGuard    = true;
input bool              UseWeeklySessionFocus  = false;  // only after enough weekly trades
input int               WeeklyFocusMinTrades   = 5;

input bool              ShowDashboard       = true;
input double            DashFontScale       = 1.4;            // readable on high-res screens
input ENUM_BASE_CORNER  DashCorner          = CORNER_LEFT_UPPER;
input int               DashX               = 12;
input int               DashY               = 24;
input int               DisconnectGraceSec  = 180;            // 0 = only local terminal connection
input bool              AutoUpdateEnabled   = true;           // confirm on-chart, then updater applies

//--- Where requests arrive and results are written. Common folder, same as
//--- everything else the bridge exchanges with the platform.
//--- Drop this file into a terminal's Common\Files to stop it publishing
//--- bars. It keeps publishing account, positions, deals and heartbeat -
//--- everything that makes it a usable trading endpoint - and skips the six
//--- hundred writes that only one terminal's worth of is ever read.
//--- How many timer ticks between full bar publications.
//---
//--- At twenty seconds a tick that is one bar sweep every five minutes,
//--- which is faster than the collector ingests them, while the account and
//--- heartbeat refresh every twenty seconds regardless of how long a sweep
//--- takes. Before this the two were the same loop, so the freshness of "is
//--- this terminal alive" was decided by how long it took to write a hundred
//--- and thirty two CSV files.
#define BARS_EVERY 15

//--- Symbols written per sweep pass. Twelve symbols is thirty-six files,
//--- which returns in well under a tick on this host; the forty-four in the
//--- watchlist are covered in four sweeps, twenty minutes at BARS_EVERY.
#define BARS_PER_PASS 12

#define BARS_OFF_MARKER "molido_bars_off"

#define REQUEST_PREFIX "molido_order_"
#define RESULT_PREFIX  "molido_result_"
#define CLAIM_PREFIX   "molido_claimed_"

string JsonField(string body, string key)
  {
   string needle = "\"" + key + "\"";
   int at = StringFind(body, needle);
   if(at < 0)
      return "";
   int colon = StringFind(body, ":", at + StringLen(needle));
   if(colon < 0)
      return "";
   int i = colon + 1;
   while(i < StringLen(body) && (StringGetCharacter(body, i) == ' ' || StringGetCharacter(body, i) == '"'))
      i++;
   int end = i;
   while(end < StringLen(body))
     {
      ushort c = StringGetCharacter(body, end);
      if(c == ',' || c == '}' || c == '"')
         break;
      end++;
     }
   return StringSubstr(body, i, end - i);
  }

void WriteResult(string id, bool ok, ulong ticket, double price, string reason)
  {
   int handle = FileOpen(RESULT_PREFIX + id + ".json",
                         FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("MolidoBridge: cannot write result for ", id);
      return;
     }
   FileWriteString(handle, "{\"id\":\"" + id + "\",");
   FileWriteString(handle, "\"ok\":" + (ok ? "true" : "false") + ",");
   FileWriteString(handle, "\"ticket\":" + IntegerToString((long)ticket) + ",");
   FileWriteString(handle, "\"price\":" + DoubleToString(price, 5) + ",");
   FileWriteString(handle, "\"reason\":\"" + reason + "\",");
   FileWriteString(handle, "\"at\":\"" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\"}");
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| True (and a refusal written) when this is a real-money account    |
//| and AllowRealAccount is off. Reads the terminal, never the name.  |
//+------------------------------------------------------------------+
bool RealAccountRefused(string id)
  {
   if(AllowRealAccount)
      return(false);
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_REAL)
      return(false);
   WriteResult(id, false, 0, 0.0,
               "refused - real-money account and AllowRealAccount is off on the expert");
   return(true);
  }

//+------------------------------------------------------------------+
//| The filling mode this symbol will actually accept.               |
//|                                                                  |
//| IOC was hardcoded, and a broker that does not offer it on a      |
//| symbol answers 10030 "Unsupported filling mode" - an order that  |
//| never reaches the market and reads, from outside, exactly like a |
//| rejected trade. FundedNext refused every order this way.         |
//|                                                                  |
//| SYMBOL_FILLING_MODE is a bitmask of what the symbol permits, so  |
//| it is asked rather than assumed. RETURN is the fallback because  |
//| it is the mode the flag does not advertise: the mask covers FOK  |
//| and IOC only, and a symbol offering neither takes RETURN.        |
//+------------------------------------------------------------------+
//| Put the stop and target at their intended distances from the      |
//| price actually paid.                                              |
//|                                                                   |
//| The backend prices a trade from a quote this expert published     |
//| some seconds earlier. By the time the deal fills the market has   |
//| moved, so a stop sent as an absolute level sits at its intended   |
//| distance from a price nobody got and at some other distance from  |
//| the one paid. Across twenty-eight live fills a geometry built for |
//| one unit of reward per unit of risk was arriving at 0.77, and the |
//| worst at 0.15 - a trade needing an 87% win rate, taken by a       |
//| system that believed it had an even-money bet.                    |
//|                                                                   |
//| It is a risk failure before it is a return one. Size is computed  |
//| from the intended stop distance, so an adverse fill risks more    |
//| than was authorised: that 0.15 trade carried 1.75 times its       |
//| budget, and nothing anywhere said so.                             |
//|                                                                   |
//| Done after the deal rather than before it, because the price      |
//| paid is not knowable until it is paid. The order already carries  |
//| the old levels, so the position is never unprotected - this moves |
//| a stop that exists, it does not add a missing one.                |
//+------------------------------------------------------------------+
string Reanchor(const string symbol, const string side, const ulong ticket,
                const double fill, const double sl_gap, const double tp_gap)
  {
   //--- Only the position this deal opened. On a netting account a second
   //--- deal in the same symbol merges into the existing position, and
   //--- moving that position's stop would re-shape a trade this request did
   //--- not open. In hedging mode the position carries the opening order's
   //--- ticket, so failing to select it is the netting case and is left
   //--- alone rather than guessed at.
   if(!PositionSelectByTicket(ticket))
      return("filled; levels left as sent - no position with this ticket");

   int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
   long   stops  = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double nearest = stops * point;

   //--- A distance the broker will not hold is not a stop. Reported rather
   //--- than clamped: a stop quietly widened to the venue's minimum is a
   //--- position risking more than the size was computed for, which is the
   //--- exact failure this function exists to end.
   if(nearest > 0.0 && sl_gap < nearest)
      return("filled; levels left as sent - stop " + DoubleToString(sl_gap, digits) +
             " is inside the broker minimum " + DoubleToString(nearest, digits));

   double sl, tp;
   if(side == "sell")
     {
      sl = fill + sl_gap;
      tp = (tp_gap > 0.0) ? fill - tp_gap : 0.0;
     }
   else
     {
      sl = fill - sl_gap;
      tp = (tp_gap > 0.0) ? fill + tp_gap : 0.0;
     }
   if(sl <= 0.0 || (tp_gap > 0.0 && tp <= 0.0))
      return("filled; levels left as sent - re-anchoring put a level at or below zero");

   MqlTradeRequest amend;
   MqlTradeResult  answer;
   ZeroMemory(amend);
   ZeroMemory(answer);
   amend.action   = TRADE_ACTION_SLTP;
   amend.symbol   = symbol;
   amend.position = ticket;
   amend.sl       = NormalizeDouble(sl, digits);
   amend.tp       = NormalizeDouble(tp, digits);

   if(!OrderSend(amend, answer) || answer.retcode != TRADE_RETCODE_DONE)
      return("filled; levels left as sent - re-anchor retcode " +
             IntegerToString(answer.retcode));
   return("filled and re-anchored");
  }


//+------------------------------------------------------------------+
//| Close one position, named by its ticket.                          |
//|                                                                   |
//| The bridge could open a position and move its stop and nothing    |
//| else, so a position it had opened could only ever leave by        |
//| hitting a level. That is fine while a terminal is running and a   |
//| gap the moment one is not: four terminals were stopped during a   |
//| tidy-up with positions still on them, and those sat at the broker |
//| unmanaged and invisible to every report here for a day.           |
//|                                                                   |
//| By ticket, never "close everything". A request that names what it |
//| closes can be checked before it is written and read afterwards to |
//| see what it did; a sweep primitive is one typo from emptying an   |
//| account, and the convenience is not worth keeping that within     |
//| reach of a file drop.                                             |
//|                                                                   |
//| In hedging mode a position closes by dealing the opposite way     |
//| with `position` set - an opposite order without it opens a second |
//| position and doubles the exposure it was meant to remove.         |
//+------------------------------------------------------------------+
void CloseOne(const string id, const ulong ticket)
  {
   if(!PositionSelectByTicket(ticket))
     {
      //--- Already gone is not a failure. A stop may have taken it between
      //--- the request being written and read, and reporting that as an
      //--- error would have somebody hunting a position that closed
      //--- correctly.
      WriteResult(id, true, ticket, 0.0, "no such position - already closed");
      return;
     }

   string symbol = PositionGetString(POSITION_SYMBOL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   long   kind   = PositionGetInteger(POSITION_TYPE);

   MqlTradeRequest request;
   MqlTradeResult  result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action       = TRADE_ACTION_DEAL;
   request.position     = ticket;
   request.symbol       = symbol;
   request.volume       = volume;
   request.type         = (kind == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price        = (kind == POSITION_TYPE_BUY)
                          ? SymbolInfoDouble(symbol, SYMBOL_BID)
                          : SymbolInfoDouble(symbol, SYMBOL_ASK);
   request.deviation    = MaxSlippagePts;
   request.type_filling = MolidoFilling(symbol);
   request.comment      = "molido-close:" + id;

   if(!OrderSend(request, result) ||
      (result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED))
     {
      WriteResult(id, false, ticket, 0.0,
                  "close retcode " + IntegerToString(result.retcode) + " " + result.comment);
      return;
     }
   WriteResult(id, true, ticket, result.price, "closed " + DoubleToString(volume, 2) + " " + symbol);
   Print("MolidoBridge: closed ", symbol, " ticket ", ticket);
  }


//+------------------------------------------------------------------+
//| Move the stop, and the target, on a position already open.        |
//|                                                                   |
//| The bridge could open a position and set its levels once, and     |
//| after that the only thing that could move a stop was the market   |
//| reaching it. So a stop could never be tightened as a trade went   |
//| the right way: every position carried its opening risk until it   |
//| closed, however much of the move was already banked.              |
//|                                                                   |
//| Levels only. This never sizes, never opens and never closes - the |
//| worst a bad amend can do is put a stop somewhere unhelpful, and   |
//| the checks below refuse the two placements that are worse than    |
//| unhelpful.                                                        |
//|                                                                   |
//| **A stop may only move toward the price, never away from it.**    |
//| That is the whole safety property. Widening a stop is how a       |
//| losing position turns into a larger losing position, and a caller |
//| that has miscalculated should be refused rather than obeyed - so  |
//| the refusal lives here, at the venue, where no backend bug can    |
//| reach past it.                                                    |
//+------------------------------------------------------------------+
void AmendOne(const string id, const ulong ticket, double sl, double tp)
  {
   if(!PositionSelectByTicket(ticket))
     {
      //--- Already gone is not a failure, exactly as for a close: a stop may
      //--- have taken it between the request being written and read.
      WriteResult(id, true, ticket, 0.0, "no such position - nothing to amend");
      return;
     }

   string symbol   = PositionGetString(POSITION_SYMBOL);
   long   kind     = PositionGetInteger(POSITION_TYPE);
   double open     = PositionGetDouble(POSITION_PRICE_OPEN);
   double have_sl  = PositionGetDouble(POSITION_SL);
   double have_tp  = PositionGetDouble(POSITION_TP);
   int    digits   = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point    = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double nearest  = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double bid      = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask      = SymbolInfoDouble(symbol, SYMBOL_ASK);

   //--- Absent means "leave this one alone", so a caller can move the stop
   //--- without restating a target it does not want to change.
   if(sl <= 0.0)
      sl = have_sl;
   if(tp <= 0.0)
      tp = have_tp;

   if(sl == have_sl && tp == have_tp)
     {
      WriteResult(id, true, ticket, 0.0, "levels already there");
      return;
     }

   //--- Never away from the price. A stop that only ever tightens cannot
   //--- turn a bounded loss into an unbounded one, whatever sent it.
   if(have_sl > 0.0)
     {
      if(kind == POSITION_TYPE_BUY && sl < have_sl)
        {
         WriteResult(id, false, ticket, 0.0,
                     "refused - a buy stop may only rise, " +
                     DoubleToString(sl, digits) + " is below " +
                     DoubleToString(have_sl, digits));
         return;
        }
      if(kind == POSITION_TYPE_SELL && sl > have_sl)
        {
         WriteResult(id, false, ticket, 0.0,
                     "refused - a sell stop may only fall, " +
                     DoubleToString(sl, digits) + " is above " +
                     DoubleToString(have_sl, digits));
         return;
        }
     }

   //--- On the wrong side of the market is not a stop, it is an instruction
   //--- to close at once at whatever the book holds.
   if((kind == POSITION_TYPE_BUY && sl >= bid) ||
      (kind == POSITION_TYPE_SELL && sl <= ask))
     {
      WriteResult(id, false, ticket, 0.0,
                  "refused - stop " + DoubleToString(sl, digits) +
                  " is on the wrong side of the market");
      return;
     }

   //--- A distance the venue will not hold is not a stop. Reported rather
   //--- than clamped, for the same reason the opening path reports it.
   double gap = (kind == POSITION_TYPE_BUY) ? (bid - sl) : (sl - ask);
   if(nearest > 0.0 && gap < nearest)
     {
      WriteResult(id, false, ticket, 0.0,
                  "refused - stop " + DoubleToString(gap, digits) +
                  " from price is inside the broker minimum " +
                  DoubleToString(nearest, digits));
      return;
     }

   MqlTradeRequest request;
   MqlTradeResult  result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action   = TRADE_ACTION_SLTP;
   request.symbol   = symbol;
   request.position = ticket;
   request.sl       = NormalizeDouble(sl, digits);
   request.tp       = NormalizeDouble(tp, digits);

   if(!OrderSend(request, result) || result.retcode != TRADE_RETCODE_DONE)
     {
      WriteResult(id, false, ticket, 0.0,
                  "amend retcode " + IntegerToString(result.retcode) + " " + result.comment);
      return;
     }
   WriteResult(id, true, ticket, sl,
               "stop " + DoubleToString(have_sl, digits) + " -> " +
               DoubleToString(sl, digits) + " on " + symbol);
   Print("MolidoBridge: amended ", symbol, " ticket ", ticket,
         " stop ", DoubleToString(have_sl, digits), " -> ", DoubleToString(sl, digits),
         " open ", DoubleToString(open, digits));
  }


//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING MolidoFilling(const string symbol)
  {
   long allowed = 0;
   if(!SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE, allowed))
      return(ORDER_FILLING_RETURN);
   if((allowed & SYMBOL_FILLING_IOC) != 0)
      return(ORDER_FILLING_IOC);
   if((allowed & SYMBOL_FILLING_FOK) != 0)
      return(ORDER_FILLING_FOK);
   return(ORDER_FILLING_RETURN);
  }

void ExecuteOne(string filename)
  {
   //--- The id is whatever sits between the prefix and the extension.
   string id = StringSubstr(filename, StringLen(REQUEST_PREFIX));
   int dot = StringFind(id, ".json");
   if(dot >= 0)
      id = StringSubstr(id, 0, dot);

   //--- Claimed before it is read, so a second pass of the timer cannot pick
   //--- up the same request while this one is still working on it.
   string claimed = CLAIM_PREFIX + id + ".json";
   if(!FileMove(filename, FILE_COMMON, claimed, FILE_COMMON))
     {
      Print("MolidoBridge: could not claim ", filename, " - leaving it alone");
      return;
     }

   int handle = FileOpen(claimed, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      WriteResult(id, false, 0, 0.0, "claimed file could not be read");
      return;
     }
   string body = "";
   while(!FileIsEnding(handle))
      body += FileReadString(handle);
   FileClose(handle);

   //--- A close names a ticket and nothing else. Routed before the fields
   //--- an opening needs are read, because a close has no size, no stop and
   //--- no side to validate.
   string closing = JsonField(body, "close_ticket");
   if(closing != "")
     {
      if(!AllowTrading)
        {
         WriteResult(id, false, 0, 0.0, "AllowTrading is off on the expert");
         return;
        }
      if(RealAccountRefused(id))
         return;
      CloseOne(id, (ulong)StringToInteger(closing));
      return;
     }

   //--- An amend names a ticket and the levels to put on it. Routed here for
   //--- the same reason a close is: it has no size and no side to validate,
   //--- and reading the opening fields for it would reject a valid request
   //--- for missing a symbol it never needed.
   string amending = JsonField(body, "amend_ticket");
   if(amending != "")
     {
      if(!AllowTrading)
        {
         WriteResult(id, false, 0, 0.0, "AllowTrading is off on the expert");
         return;
        }
      if(RealAccountRefused(id))
         return;
      AmendOne(id, (ulong)StringToInteger(amending),
               StringToDouble(JsonField(body, "stop")),
               StringToDouble(JsonField(body, "target")));
      return;
     }

   string symbol = JsonField(body, "symbol");
   string side   = JsonField(body, "side");
   double lots   = StringToDouble(JsonField(body, "lots"));
   double sl     = StringToDouble(JsonField(body, "stop"));
   double tp     = StringToDouble(JsonField(body, "target"));
   //--- The same shape as distances. Absent on requests from an older
   //--- backend, and then the levels above are used exactly as before.
   double sl_gap = StringToDouble(JsonField(body, "stop_distance"));
   double tp_gap = StringToDouble(JsonField(body, "target_distance"));

   if(!AllowTrading)
     {
      WriteResult(id, false, 0, 0.0, "AllowTrading is off on the expert");
      return;
     }
   if(!MolidoLinkHealthy())
     {
      WriteResult(id, false, 0, 0.0, "refused - terminal or server link is down; only managing open positions");
      return;
     }
   if(RealAccountRefused(id))
      return;
   if(DemoRefuseUnsafeOpen(id, symbol, side, lots, sl, tp, sl_gap))
      return;
   if(symbol == "" || lots <= 0.0)
     {
      WriteResult(id, false, 0, 0.0, "request has no symbol or no size");
      return;
     }
   if(lots > MaxLots)
     {
      //--- Refused, not clamped. Silently filling a smaller size than asked
      //--- makes every risk number above this wrong by an unknown factor.
      WriteResult(id, false, 0, 0.0,
                  "size " + DoubleToString(lots, 2) + " exceeds MaxLots " + DoubleToString(MaxLots, 2));
      return;
     }
   if(!SymbolSelect(symbol, true))
     {
      WriteResult(id, false, 0, 0.0, "symbol not available: " + symbol);
      return;
     }

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
   request.comment      = "molido:" + id;

   bool sent = OrderSend(request, result);
   if(!sent || (result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED))
     {
      WriteResult(id, false, 0, 0.0,
                  "retcode " + IntegerToString(result.retcode) + " " + result.comment);
      return;
     }

   string note = "filled";
   if(sl_gap > 0.0 && result.price > 0.0)
      note = Reanchor(symbol, side, result.order, result.price, sl_gap, tp_gap);

   WriteResult(id, true, result.order, result.price, note);
   Print("MolidoBridge: executed ", side, " ", lots, " ", symbol, " ticket ", result.order);
  }

void ExecutePending()
  {
   string filename;
   long search = FileFindFirst(REQUEST_PREFIX + "*.json", filename, FILE_COMMON);
   if(search == INVALID_HANDLE)
      return;
   do
     {
      ExecuteOne(filename);
     }
   while(FileFindNext(search, filename));
   FileFindClose(search);
  }

//+------------------------------------------------------------------+
//| Closed deals                                                      |
//|                                                                   |
//| Realised profit is the one figure the platform could not compute. |
//| Positions publish their floating profit every cycle, but a closed |
//| trade leaves the positions file entirely and nothing recorded     |
//| where it went - so an account could be up four hundred dollars on |
//| the day and every page would show only what was still open.       |
//|                                                                   |
//| Deals rather than orders. An order is a request; a deal is what   |
//| the account was actually charged or paid, which is the number a   |
//| P&L is made of.                                                   |
//+------------------------------------------------------------------+
input int DealHistoryDays = 30;

void WriteDeals()
  {
   datetime from = TimeCurrent() - (datetime)DealHistoryDays * 86400;
   if(!HistorySelect(from, TimeCurrent()))
     {
      Print("MolidoBridge: HistorySelect failed for the deal window");
      return;
     }

   int handle = FileOpen("molido_deals.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;

   FileWriteString(handle, "{\"published_at\":\"" +
                   TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\",");
   FileWriteString(handle, "\"window_days\":" + IntegerToString(DealHistoryDays) + ",");
   FileWriteString(handle, "\"deals\":[");

   int total = HistoryDealsTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;

      //--- Entry deals open a position and carry no realised profit; only
      //--- the closing side does. Publishing both would double every trade
      //--- and put a zero beside each real one.
      long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      long kind  = HistoryDealGetInteger(ticket, DEAL_TYPE);

      //--- But a charge is not a trade and was being dropped with them.
      //--- Swap on a position that is still open is booked nightly as its
      //--- own deal, not as part of a close, so the filter above hid every
      //--- one: on 2026-09-08 six accounts had drifted a few dollars below
      //--- their starting balance with `deals: []` on all of them and
      //--- nothing anywhere to say where the money went.
      //---
      //--- Published beside the trades rather than instead of them, with
      //--- `entry` and `type` on every row so a reader can tell a closed
      //--- trade from an overnight charge and never add the two by
      //--- accident.
      double swap_here = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double fee_here  = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      bool   closing   = (entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_INOUT);
      bool   charge    = (!closing && (swap_here != 0.0 || fee_here != 0.0));
      if(!closing && !charge)
         continue;

      if(!first)
         FileWriteString(handle, ",");
      first = false;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      double swap   = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double fee    = HistoryDealGetDouble(ticket, DEAL_COMMISSION);

      FileWriteString(handle, "{\"ticket\":" + IntegerToString((long)ticket) + ",");
      FileWriteString(handle, "\"entry\":" + IntegerToString(entry) + ",");
      FileWriteString(handle, "\"type\":" + IntegerToString(kind) + ",");
      FileWriteString(handle, "\"is_charge\":" + (charge ? "true" : "false") + ",");
      FileWriteString(handle, "\"symbol\":\"" +
                      Escape(HistoryDealGetString(ticket, DEAL_SYMBOL)) + "\",");
      FileWriteString(handle, "\"side\":\"" +
                      (HistoryDealGetInteger(ticket, DEAL_TYPE) == DEAL_TYPE_BUY ? "buy" : "sell") + "\",");
      FileWriteString(handle, "\"volume\":" +
                      DoubleToString(HistoryDealGetDouble(ticket, DEAL_VOLUME), 4) + ",");
      FileWriteString(handle, "\"price\":" +
                      DoubleToString(HistoryDealGetDouble(ticket, DEAL_PRICE), 8) + ",");
      FileWriteString(handle, "\"profit\":" + DoubleToString(profit, 2) + ",");
      FileWriteString(handle, "\"swap\":" + DoubleToString(swap, 2) + ",");
      FileWriteString(handle, "\"commission\":" + DoubleToString(fee, 2) + ",");
      //--- Published summed as well as split. Every page that shows "profit"
      //--- without swap and commission is showing a number the account never
      //--- saw, and the three are stored separately by the terminal.
      FileWriteString(handle, "\"net\":" + DoubleToString(profit + swap + fee, 2) + ",");
      FileWriteString(handle, "\"closed_at\":\"" +
                      TimeToString((datetime)HistoryDealGetInteger(ticket, DEAL_TIME),
                                   TIME_DATE | TIME_SECONDS) + "\",");
      FileWriteString(handle, "\"comment\":\"" +
                      Escape(HistoryDealGetString(ticket, DEAL_COMMENT)) + "\"}");
     }

   FileWriteString(handle, "]}");
   FileClose(handle);
  }

void OnTimer()
  {
   FetchRemoteConfig(false);
   Publish();
   ExecutePending();
   DemoScalperOnTimer();
#ifdef MOLIDO_EXPERT_UI
   ExpertInstanceHeartbeat();
   ExpertBridgeOnTimer();
#endif
   MolidoDashOnTimer();
  }

//--- Required for an expert, and deliberately empty. Publishing is on the
//--- timer; doing it per tick would rewrite every file hundreds of times a
//--- minute for no extra information.
void OnTick()
  {
   RefreshActiveProfile();
   DemoScalperOnTick();
   MolidoDashOnTick();
  }

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   MolidoDashOnChartEvent(id, lparam, dparam, sparam);
  }


//+------------------------------------------------------------------+
//| Publishing to the platform over HTTPS.                             |
//|                                                                    |
//| The file bridge assumes the reader shares a filesystem with this   |
//| terminal. That holds for one terminal on one box and stops holding |
//| at eleven accounts, which is the ordinary shape for anyone running |
//| funded accounts beside a challenge - eleven terminals do not fit   |
//| on the machine the platform runs on, and nothing about the bridge  |
//| requires them to.                                                  |
//|                                                                    |
//| So the same payload goes out over HTTPS as well. Outbound only, so |
//| it crosses any firewall a trading VPS sits behind, with no shared  |
//| drive and no sync agent to fail separately.                        |
//|                                                                    |
//| **As well as the files, never instead of them.** A terminal that   |
//| already publishes locally keeps working exactly as it did, and a   |
//| network that goes down costs the remote copy rather than the whole |
//| bridge. Turning this on cannot break a setup that works.           |
//|                                                                    |
//| Leave PublishUrl empty and none of this runs.                      |
//+------------------------------------------------------------------+

//--- Where to publish. Empty disables HTTP publishing entirely.
input string PublishUrl        = "";
//--- The API key. Held in memory and never written to a file or the log:
//--- the Experts tab is shoulder-surfable and gets pasted into forums.
input string PublishApiKey     = "";
//--- Which account this terminal is. Must match a key the platform has been
//--- configured for - the backend refuses an unknown one rather than filing
//--- it somewhere plausible, because the directory it lands in *is* the
//--- account and the wrong one is somebody else's money.
input string PublishAccountKey = "main";
//--- How long to wait. Long enough to cross a continent, short enough that a
//--- dead endpoint cannot stall the publish timer behind it.
input int    PublishTimeoutMs  = 15000;

//--- Said once rather than every cycle. A whitelist that has not been set is
//--- a permanent condition until somebody changes a setting, and repeating it
//--- every twenty seconds buries the rest of the log.
bool warned_not_whitelisted = false;

void PostToPlatform()
  {
   if(MolidoIsTester())
      return;
   if(StringLen(PublishUrl) == 0)
      return;

   string body = "{";
   body += "\"account_key\":\"" + Escape(PublishAccountKey) + "\",";
   body += "\"account\":" + AccountJson() + ",";
   body += "\"positions\":" + PositionsArray() + ",";
   //--- Both are also inside the account block. Sent again at the top level
   //--- because the backend reads them from there when a terminal publishes a
   //--- bare account, and duplicating two booleans is cheaper than a contract
   //--- that only works when the account block is complete.
   body += "\"connected\":" + (TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false") + ",";
   body += "\"ea_version\":\"" + MOLIDO_EA_VERSION + "\",";
   body += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   body += "}";

   char post[];
   char result[];
   string headers = "Content-Type: application/json\r\n";
   if(StringLen(PublishApiKey) > 0)
      headers += "X-API-Key: " + PublishApiKey + "\r\n";

   //--- Without the trailing zero the request carries a stray byte and the
   //--- backend rejects the JSON for a reason nothing here would explain.
   StringToCharArray(body, post, 0, StringLen(body), CP_UTF8);

   string response_headers;
   ResetLastError();
   int status = WebRequest("POST", PublishUrl, headers, PublishTimeoutMs,
                           post, result, response_headers);

   if(status == -1)
     {
      g_publish_status = -1;
      int err = GetLastError();
      if(err == 4060 && !warned_not_whitelisted)
        {
         //--- The first error everybody hits, and the message MetaTrader gives
         //--- for it does not say what to do. This one does.
         Print("MolidoBridge: MetaTrader is blocking the request. Add ",
               PublishUrl, " under Tools > Options > Expert Advisors > ",
               "Allow WebRequest for listed URL, then restart the terminal.");
         warned_not_whitelisted = true;
        }
      else if(err != 4060)
         Print("MolidoBridge: publish failed, error ", err);
      return;
     }

   if(status >= 400)
     {
      g_publish_status = -1;
      //--- The backend writes a sentence explaining which field it refused, and
      //--- it is far more useful than the status code on its own - the usual
      //--- cause is an account key that does not match the configuration, and
      //--- the response names the keys that do.
      Print("MolidoBridge: platform answered ", status, ": ",
            CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
      return;
     }
   g_publish_status = 1;
   g_lastServerOk = TimeCurrent();
   g_last_publish_at = TimeCurrent();
  }

void Publish()
  {
   static int cycle = 0;
   cycle++;

   WriteAccount();
   //--- Immediately after the account, not at the end of the pass.
   //---
   //--- The platform treats a missing or stale heartbeat as "the expert is
   //--- not attached, or the terminal is not running", which is the right
   //--- rule and was being fed the wrong evidence: the account file was
   //--- written first and the heartbeat last, with a hundred and thirty two
   //--- bar files between them. A connected, funded, trading-enabled account
   //--- with a ninety-eight second old account file read as absent, because
   //--- the only thing that said the terminal was alive was ten minutes
   //--- behind it.
   //---
   //--- They describe the same fact - this terminal is running and here is
   //--- its account - so they are written together. It is written again at
   //--- the end of the pass, where its cycle count still means "a full pass
   //--- completed".
   WriteHeartbeat(cycle);
   WriteDailySummary();
   WritePositions();

   //--- Everything above is cheap and runs every tick. Everything below is
   //--- not, and runs every BARS_EVERY ticks.
   //---
   //--- Moving the heartbeat to the top of the pass was not enough: the pass
   //--- itself takes ten minutes on this host, so the heartbeat was fresh for
   //--- twenty seconds in every six hundred and the platform spent the rest
   //--- of the time reporting a live, funded, trading account as absent. The
   //--- website said "not publishing" about two terminals that were.
   //---
   //--- So the fast facts are decoupled from the slow ones. Account,
   //--- heartbeat and positions are what the platform reads to decide a
   //--- terminal is alive and what it holds, and they are three small files.
   //--- Symbols, deals and bars are reference data that nothing checks for
   //--- freshness in seconds.
   //--- The first pass is not special, and treating it as special is what
   //--- broke this. `cycle > 1` here meant pass one still swept every bar,
   //--- and MetaTrader serialises timer events - so for the ten minutes that
   //--- sweep took, no heartbeat was written at all. A terminal that had just
   //--- connected sat invisible for exactly as long as the thing meant to
   //--- make it visible sooner.
   //---
   //--- Now the account and heartbeat land twenty seconds after the expert
   //--- loads, and the first bar sweep happens at pass fifteen, five minutes
   //--- later, when nobody is waiting to see whether the login worked.
   //--- No every-Nth gate any more: the slice above is the throttle, and a
   //--- sweep that runs every pass in twelve-symbol pieces covers the list
   //--- faster than one that runs every fifteenth pass whole.

   WriteSymbols();
   WriteDeals();

   //--- Bars are the expensive half of a cycle and only one terminal's are
   //--- ever read.
   //---
   //--- A hundred and fifty symbols across four timeframes is six hundred
   //--- files per pass. With seven terminals awake that is four thousand two
   //--- hundred writes, and the backend ingests exactly one terminal's worth
   //--- - it picks whichever is signed in and ignores the rest. The other six
   //--- were spending the whole cycle producing data nobody reads.
   //---
   //--- The cost is not the disk. `WriteAccount` runs at the top of a pass,
   //--- so a pass that takes ten minutes means an account file ten minutes
   //--- stale, and the platform reads that as a terminal publishing nothing.
   //--- A freshly connected account looked broken for ten minutes for exactly
   //--- this reason.
   //---
   //--- Off by file rather than by input: a marker the host can drop in
   //--- needs no MT5 preset plumbing and no restart to change. Absent means
   //--- publish, so a terminal nobody has configured behaves as it always
   //--- did and the price feed cannot be switched off by forgetting to
   //--- create something.
   if(FileIsExist(BARS_OFF_MARKER, FILE_COMMON))
     {
      WriteHeartbeat(cycle);
      PostToPlatform();
      return;
     }

   //--- A bounded slice per pass, resumed where the last one stopped.
   //---
   //--- Even with the synchronised guard above, a full sweep is a hundred
   //--- and thirty-odd files and MetaTrader serialises timer events, so the
   //--- heartbeat cannot fire until the sweep returns. Slicing it means a
   //--- pass returns in seconds whatever the host is doing, the heartbeat
   //--- keeps its twenty-second cadence, and the whole watchlist still gets
   //--- covered - just across several passes instead of one.
   static int cursor = 0;
   int total = SymbolsTotal(true);
   if(cursor >= total)
      cursor = 0;
   int stop_at = MathMin(cursor + BARS_PER_PASS, total);
   for(int i = cursor; i < stop_at; i++)
     {
      string name = SymbolName(i, true);
      WriteBars(name, PERIOD_H1);
      WriteBars(name, PERIOD_M15);
      //--- Published so the faster timeframes can be measured. Whether the
      //--- rule is *traded* on them is a separate decision, taken in the
      //--- backend against what these bars turn out to say: the spread is a
      //--- constant and the bar range falls with the square root of time, so
      //--- the cost of a decision rises as the timeframe shortens whatever
      //--- the edge does. Publishing the data settles that with evidence
      //--- rather than with either of our opinions.
      WriteBars(name, PERIOD_M5);
      WriteTicks(name);
      cursor = i + 1;
      //--- M1 is not published, and its absence is a measurement rather than
      //--- a preference. `collector._broker_timeframes` stopped ingesting it
      //--- for a reason it states: the round trip costs about 0.52 R at one
      //--- minute against a 0.25 R ceiling, so no M1 decision can pass the
      //--- spread gate however good the signal is.
      //---
      //--- The backend stopped reading them and this kept writing them. A
      //--- quarter of every cycle went to files nothing opens, and a cycle
      //--- here is the interval at which the account file refreshes - so the
      //--- cost was not disk, it was a freshly connected account looking
      //--- dead for ten minutes.
     }

   WriteHeartbeat(cycle);

   //--- Last, and after the heartbeat. The local files are the bridge this
   //--- terminal has always had; a slow or unreachable endpoint must cost the
   //--- remote copy and nothing else.
   PostToPlatform();
  }
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| Remote config and version check.                                   |
//|                                                                    |
//| The EA stays a thin bridge: the symbol list, refresh period and    |
//| bar counts come from the platform (GET .../bridge/config) so they  |
//| change without touching this file. Only those four values are read.|
//| AllowTrading, AllowRealAccount, AllowedLogins, EnableDemoScalper    |
//| and ScalperKillSwitch are inputs with no runtime copy, so the       |
//| config cannot reach them. Values are clamped,                       |
//| symbol names are character-checked, and a failed fetch keeps the    |
//| current settings.                                                   |
//+------------------------------------------------------------------+
input string ConfigUrl            = "";   // empty = PublishUrl with /publish -> /config
input int    ConfigRefreshMinutes = 10;

bool MolidoLinkHealthy()
  {
   if(MolidoIsTester())
      return(true);
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
      return(false);
   bool server = (StringLen(ConfigUrl) > 0 || StringLen(PublishUrl) > 0);
   if(!server)
      return(true);
   int grace = DisconnectGraceSec;
   if(grace < 30)
      grace = 30;
   if(g_lastServerOk > 0)
      return((TimeCurrent() - g_lastServerOk) <= grace);
   if(g_initTime > 0 && (TimeCurrent() - g_initTime) > grace)
      return(false);
   return(true);
  }


datetime g_lastConfigFetch = 0;
string   g_announcedVersion = "";

string ResolvedConfigUrl()
  {
   if(StringLen(ConfigUrl) > 0)
      return ConfigUrl;
   if(StringLen(PublishUrl) == 0)
      return "";
   string url = PublishUrl;
   if(StringReplace(url, "/bridge/publish", "/bridge/config") <= 0)
      return "";
   return url;
  }

//--- Value of "key": in a flat JSON object; strings unquoted. Empty if absent.
string JsonValue(const string body, const string key)
  {
   string pattern = "\"" + key + "\":";
   int at = StringFind(body, pattern);
   if(at < 0)
      return "";
   int i = at + StringLen(pattern);
   while(i < StringLen(body) && StringGetCharacter(body, i) == ' ')
      i++;
   if(i >= StringLen(body))
      return "";
   if(StringGetCharacter(body, i) == '"')
     {
      int end = StringFind(body, "\"", i + 1);
      return end < 0 ? "" : StringSubstr(body, i + 1, end - i - 1);
     }
   int stop = i;
   while(stop < StringLen(body))
     {
      ushort c = StringGetCharacter(body, stop);
      if(c == ',' || c == '}' || c == ' ')
         break;
      stop++;
     }
   string raw = StringSubstr(body, i, stop - i);
   return raw == "null" ? "" : raw;
  }

bool SafeSymbolList(const string csv)
  {
   if(StringLen(csv) == 0 || StringLen(csv) > 2000)
      return false;
   for(int i = 0; i < StringLen(csv); i++)
     {
      ushort c = StringGetCharacter(csv, i);
      bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')
                || c == ',' || c == '.' || c == '_' || c == '#' || c == '-';
      if(!ok)
         return false;
     }
   return true;
  }

int Clamp(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

//--- true when version a is newer than b ("1.20" vs "1.10").
bool VersionNewer(const string a, const string b)
  {
   string pa[], pb[];
   int na = StringSplit(a, '.', pa), nb = StringSplit(b, '.', pb);
   for(int i = 0; i < MathMax(na, nb); i++)
     {
      long x = i < na ? StringToInteger(pa[i]) : 0;
      long y = i < nb ? StringToInteger(pb[i]) : 0;
      if(x != y)
         return x > y;
     }
   return false;
  }

void FetchRemoteConfig(bool force)
  {
   if(MolidoIsTester())
      return;
   string url = ResolvedConfigUrl();
   if(StringLen(url) == 0)
      return;
   if(!force && TimeCurrent() - g_lastConfigFetch < ConfigRefreshMinutes * 60)
      return;
   g_lastConfigFetch = TimeCurrent();
   string full = url + (StringFind(url, "?") < 0 ? "?" : "&") + "account_key=" + PublishAccountKey
                 + "&ea_version=" + MOLIDO_EA_VERSION;
   string headers = "";
   if(StringLen(PublishApiKey) > 0)
      headers = "X-API-Key: " + PublishApiKey + "\r\n";
   char data[];
   char result[];
   string response_headers;
   ResetLastError();
   int status = WebRequest("GET", full, headers, PublishTimeoutMs, data, result, response_headers);
   if(status != 200)
     {
      g_config_status = -1;
      Print("MolidoBridge: remote config not loaded (status ", status, ", error ", GetLastError(),
            ") - keeping current settings");
      return;
     }
   g_config_status = 1;
   g_lastServerOk = TimeCurrent();
   string body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   string caps = JsonValue(body, "demo_risk_caps_csv");
   if(StringLen(caps) > 0)
      ApplyDemoRiskCaps(caps);
   string news_csv = JsonValue(body, "news_events_csv");
   if(StringLen(news_csv) > 0)
      g_news_server_csv = news_csv;
   string consensus = JsonValue(body, "consensus_csv");
   if(StringLen(consensus) > 0)
      g_consensus_csv = consensus;
   string ranks = JsonValue(body, "ranking_csv");
   if(StringLen(ranks) > 0)
      g_ranking_csv = ranks;

   string symbols = JsonValue(body, "symbols_csv");
   if(SafeSymbolList(symbols) && symbols != g_Symbols)
     {
      g_Symbols = symbols;
      Print("MolidoBridge: symbol list updated from the platform");
      SelectExtraSymbols();
     }
   string refresh = JsonValue(body, "refresh_seconds");
   if(StringLen(refresh) > 0)
     {
      int seconds = Clamp((int)StringToInteger(refresh), 5, 300);
      if(seconds != g_RefreshSeconds)
        {
         g_RefreshSeconds = seconds;
         EventKillTimer();
         EventSetTimer(g_RefreshSeconds);
         Print("MolidoBridge: refresh set to ", g_RefreshSeconds, "s by the platform");
        }
     }
   string bars = JsonValue(body, "bar_count");
   if(StringLen(bars) > 0)
      g_BarCount = Clamp((int)StringToInteger(bars), 50, 5000);
   string ticks = JsonValue(body, "tick_count");
   if(StringLen(ticks) > 0)
      g_TickCount = Clamp((int)StringToInteger(ticks), 0, 1000);
   string intraday = JsonValue(body, "intraday_bar_count");
   if(StringLen(intraday) > 0)
      g_IntradayBarCount = Clamp((int)StringToInteger(intraday), 50, 2000);

   string latest = JsonValue(body, "ea_latest_version");
   string gate = JsonValue(body, "ea_gate");
   string sha = JsonValue(body, "ea_latest_sha256");
   if(StringLen(latest) > 0 && VersionNewer(latest, MOLIDO_EA_VERSION)
      && (gate == "PASS" || gate == "pass")
      && StringLen(sha) == 64)
     {
      g_update_version = latest;
      g_update_sha256 = sha;
      g_update_gate = "PASS";
      g_update_ready = AutoUpdateEnabled;
     }
   else
     {
      g_update_ready = false;
     }
   if(StringLen(latest) > 0 && latest != g_announcedVersion && VersionNewer(latest, MOLIDO_EA_VERSION))
     {
      g_announcedVersion = latest;
      Print("MolidoBridge: a newer EA is available (", latest, ", running ", MOLIDO_EA_VERSION,
            "). The updater script installs it; nothing changes until then.");
     }
  }

//+------------------------------------------------------------------+
//| Recent quote ticks for the microstructure agent (SC02).           |
//| Off unless the platform sets tick_count; written in the same      |
//| bounded slice as bars so a pass stays short.                      |
//+------------------------------------------------------------------+
void WriteTicks(string symbol)
  {
   if(g_TickCount <= 0)
      return;
   MqlTick ticks[];
   int got = CopyTicks(symbol, ticks, COPY_TICKS_INFO, 0, g_TickCount);
   if(got <= 0)
      return;
   int handle = FileOpen("molido_ticks_" + symbol + ".csv", FLAGS | FILE_CSV, ',');
   if(handle == INVALID_HANDLE)
      return;
   FileWrite(handle, "time_msc", "bid", "ask");
   for(int i = 0; i < got; i++)
      FileWrite(handle, IntegerToString(ticks[i].time_msc), DoubleToString(ticks[i].bid, 8),
                DoubleToString(ticks[i].ask, 8));
   FileClose(handle);
  }

//--- Demo scalper, news, dashboard. Included last so they can call helpers
//--- and the trading inputs declared above. Safety inputs stay local.
#include "MolidoShared.mqh"

int MolidoOwnOpenCount()
  {
   int n = 0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) == MOLIDO_MAGIC)
         n++;
     }
   return(n);
  }

bool MolidoPositionsHaveStops()
  {
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != MOLIDO_MAGIC)
         continue;
      if(PositionGetDouble(POSITION_SL) <= 0.0)
         return(false);
     }
   return(true);
  }

void MolidoWriteSettingsSnapshot()
  {
   string json = "{";
   json += "\"ea\":\"" + MOLIDO_EA_NAME + "\",";
   json += "\"ea_version\":\"" + MOLIDO_EA_VERSION + "\",";
   json += "\"magic\":" + IntegerToString(MOLIDO_MAGIC) + ",";
   json += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   json += "\"AccountProfile\":" + IntegerToString((int)AccountProfile) + ",";
   json += "\"AllowTrading\":" + (AllowTrading ? "true" : "false") + ",";
   json += "\"AllowRealAccount\":" + (AllowRealAccount ? "true" : "false") + ",";
   json += "\"AllowedLogins\":\"" + AllowedLogins + "\",";
   json += "\"AllowedRealLogins\":\"" + AllowedRealLogins + "\",";
   json += "\"RehearsalMode\":" + (RehearsalMode ? "true" : "false") + ",";
   json += "\"UseScalper\":" + (UseScalper ? "true" : "false") + ",";
   json += "\"UseNews\":" + (UseNews ? "true" : "false") + ",";
   json += "\"UseTrend\":" + (UseTrend ? "true" : "false") + ",";
   json += "\"UseAutoSymbol\":" + (UseAutoSymbol ? "true" : "false") + ",";
   json += "\"chart_id\":" + IntegerToString(ChartID()) + ",";
   json += "\"symbol\":\"" + _Symbol + "\",";
   json += "\"timeframe\":" + IntegerToString((int)_Period);
   json += "}";
   int h = FileOpen("molido_master_settings.json", FLAGS);
   if(h == INVALID_HANDLE)
      return;
   FileWriteString(h, json);
   FileClose(h);
  }

bool MolidoRequestUpdate()
  {
   if(!g_update_ready || StringLen(g_update_version) == 0 || StringLen(g_update_sha256) != 64)
      return(false);
   if(MolidoOwnOpenCount() > 0 && !MolidoPositionsHaveStops())
     {
      Print("MolidoMaster: update deferred - open positions are missing a stop");
      return(false);
     }
   MolidoWriteSettingsSnapshot();
   string json = "{";
   json += "\"action\":\"update\",";
   json += "\"confirmed\":true,";
   json += "\"ea\":\"" + MOLIDO_EA_NAME + "\",";
   json += "\"from_version\":\"" + MOLIDO_EA_VERSION + "\",";
   json += "\"to_version\":\"" + g_update_version + "\",";
   json += "\"sha256\":\"" + g_update_sha256 + "\",";
   json += "\"gate\":\"PASS\",";
   json += "\"profile\":" + IntegerToString((int)ActiveProfile()) + ",";
   json += "\"profile_detected\":" + IntegerToString((int)DetectedProfile()) + ",";
   json += "\"real_unsupported\":" + (MolidoRealBlocked() ? "true" : "false") + ",";
   json += "\"open_positions\":" + IntegerToString(MolidoOwnOpenCount()) + ",";
   json += "\"stops_ok\":" + (MolidoPositionsHaveStops() ? "true" : "false") + ",";
   json += "\"chart_id\":" + IntegerToString(ChartID()) + ",";
   json += "\"symbol\":\"" + _Symbol + "\",";
   json += "\"timeframe\":" + IntegerToString((int)_Period) + ",";
   json += "\"requested_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\"";
   json += "}";
   int h = FileOpen("molido_update_request.json", FLAGS);
   if(h == INVALID_HANDLE)
     {
      Print("MolidoMaster: cannot write update request (", GetLastError(), ")");
      return(false);
     }
   FileWriteString(h, json);
   FileClose(h);
   g_update_pending = true;
   g_update_ready = false;
   Print("MolidoMaster: update ", g_update_version, " confirmed - watcher will apply, then reattach with the same AccountProfile");
   return(true);
  }

#include "MolidoI18n.mqh"
#ifdef MOLIDO_EXPERT_UI
#include "MolidoExpertPolicy.mqh"
#include "MolidoV2Filters.mqh"
#endif
#include "MolidoDemoScalper.mqh"
#include "MolidoFibo.mqh"
#include "MolidoNews.mqh"
#include "MolidoSmart.mqh"
#include "MolidoProtect.mqh"
#include "MolidoUniverse.mqh"
#ifdef MOLIDO_EXPERT_UI
#include "MolidoExpertBridge.mqh"
#include "MolidoExpertRisk.mqh"
#include "MolidoExpertReport.mqh"
#include "MolidoExpertExec.mqh"
#include "MolidoExpertUI.mqh"
#else
#include "MolidoDashboard.mqh"
#endif

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
//| Read-only on purpose. This service places no orders and reads no  |
//| command file: an order path that exists is an order path that can |
//| fire, and this deployment has no proven edge for it to act on.    |
//| When that changes, the gate belongs in the risk layer that        |
//| already exists, not in a service nobody is watching.               |
//+------------------------------------------------------------------+
//--- An expert rather than a service. A service starts only from the
//--- Navigator panel, and that panel does not render its expanders under
//--- Wine, so there is no way to click the thing. An expert can be named
//--- in a startup config file, which the terminal reads from the command
//--- line - no window, no click, and it survives every restart.
#property copyright "MolidoTrade AI"
#property version   "1.00"

//--- Written to the common folder rather than the terminal's own, so the path
//--- does not move when the terminal is reinstalled or run portable.
#define FLAGS (FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON)

//--- How often to republish. Hourly bars do not reward a tighter loop, and a
//--- service rewriting the same files every second would keep a disk busy for
//--- nothing.
input int RefreshSeconds = 20;
//--- How many closed bars to publish per symbol and timeframe.
input int BarCount = 500;

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
input string ExtraSymbols = "XAUUSD,XAGUSD,XAUEUR,BRENT,WTI,.US30Cash,.US500Cash,.USTECHCash,.DE40Cash,.JP225Cash,AUDCAD,AUDCHF,AUDJPY,AUDNZD,CADCHF,CADJPY,CHFJPY,EURAUD,EURCAD,EURCHF,EURGBP,EURJPY,EURNZD,GBPAUD,GBPCAD,GBPCHF,GBPJPY,GBPNZD,NZDCAD,NZDCHF,NZDJPY";

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
void WriteAccount()
  {
   int handle = FileOpen("molido_account.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;

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

   FileWriteString(handle, json);
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
      json += "\"ask\":" + DoubleToString(SymbolInfoDouble(name, SYMBOL_ASK), 8);
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
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, period, 1, BarCount, rates);
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
void WritePositions()
  {
   int handle = FileOpen("molido_positions.json", FLAGS);
   if(handle == INVALID_HANDLE)
      return;

   string json = "{\"published_at\":\"" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"positions\":[";
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
   json += "]}";

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
   json += "\"refresh_seconds\":" + IntegerToString(RefreshSeconds) + ",";
   json += "\"places_orders\":false";
   json += "}";
   FileWriteString(handle, json);
   FileClose(handle);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   Print("MolidoBridge: publishing every ", RefreshSeconds, "s to the common Files folder");
   //--- One timer rather than OnTick: this publishes on a clock, not on price
   //--- movement. Tying it to ticks would stop publishing exactly when the
   //--- market goes quiet, which is when a stale-feed check needs it most.
   PublishAvailableSymbols();
   SelectExtraSymbols();
   EventSetTimer(RefreshSeconds);
   Publish();
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
   if(StringLen(ExtraSymbols) == 0)
      return;

   string names[];
   int count = StringSplit(ExtraSymbols, ',', names);
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
   Print("MolidoBridge: stopped, reason ", reason);
  }

void OnTimer()
  {
   Publish();
  }

//--- Required for an expert, and deliberately empty. Publishing is on the
//--- timer; doing it per tick would rewrite every file hundreds of times a
//--- minute for no extra information.
void OnTick()
  {
  }

void Publish()
  {
   static int cycle = 0;
   cycle++;

   WriteAccount();
   WriteSymbols();
   WritePositions();

   int total = SymbolsTotal(true);
   for(int i = 0; i < total; i++)
     {
      string name = SymbolName(i, true);
      WriteBars(name, PERIOD_H1);
      WriteBars(name, PERIOD_M15);
     }

   WriteHeartbeat(cycle);
  }
//+------------------------------------------------------------------+

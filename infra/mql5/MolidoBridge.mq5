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
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int wanted = (period <= PERIOD_M5) ? IntradayBarCount : BarCount;
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
input bool   AllowTrading    = true;
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
input double MaxLots         = 5.00;
input int    MaxSlippagePts  = 30;

//--- Where requests arrive and results are written. Common folder, same as
//--- everything else the bridge exchanges with the platform.
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
      CloseOne(id, (ulong)StringToInteger(closing));
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
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT)
         continue;

      if(!first)
         FileWriteString(handle, ",");
      first = false;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      double swap   = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double fee    = HistoryDealGetDouble(ticket, DEAL_COMMISSION);

      FileWriteString(handle, "{\"ticket\":" + IntegerToString((long)ticket) + ",");
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
   Publish();
   ExecutePending();
  }

//--- Required for an expert, and deliberately empty. Publishing is on the
//--- timer; doing it per tick would rewrite every file hundreds of times a
//--- minute for no extra information.
void OnTick()
  {
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
      //--- The backend writes a sentence explaining which field it refused, and
      //--- it is far more useful than the status code on its own - the usual
      //--- cause is an account key that does not match the configuration, and
      //--- the response names the keys that do.
      Print("MolidoBridge: platform answered ", status, ": ",
            CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
     }
  }

void Publish()
  {
   static int cycle = 0;
   cycle++;

   WriteAccount();
   WriteSymbols();
   WritePositions();
   WriteDeals();

   int total = SymbolsTotal(true);
   for(int i = 0; i < total; i++)
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
      WriteBars(name, PERIOD_M1);
     }

   WriteHeartbeat(cycle);

   //--- Last, and after the heartbeat. The local files are the bridge this
   //--- terminal has always had; a slow or unreachable endpoint must cost the
   //--- remote copy and nothing else.
   PostToPlatform();
  }
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| MolidoDashboard.mqh - compact dark on-chart status panel.        |
//| CCanvas, corner-anchored, redrawn at most once a second.         |
//| All objects are destroyed in MolidoDashOnDeinit.                 |
//+------------------------------------------------------------------+
#ifndef MOLIDO_DASHBOARD_MQH
#define MOLIDO_DASHBOARD_MQH

#include <Canvas/Canvas.mqh>

#define DASH_NAME   "MolidoDash_canvas"
#define DASH_W      312
#define DASH_H      306

CCanvas g_dash;
bool    g_dash_ready = false;
string  g_dash_sig   = "";
uint    g_dash_last_ms = 0;

void MolidoDashDestroy()
  {
   if(g_dash_ready)
     {
      g_dash.Destroy();
      g_dash_ready = false;
     }
   g_dash_sig = "";
   if(ObjectFind(0, DASH_NAME) >= 0)
      ObjectDelete(0, DASH_NAME);
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, "MolidoDash_") == 0)
         ObjectDelete(0, name);
     }
   ChartRedraw(0);
  }

bool MolidoDashEnsure()
  {
   if(!ShowDashboard)
     {
      MolidoDashDestroy();
      return(false);
     }
   if(g_dash_ready)
      return(true);
   if(!g_dash.CreateBitmapLabel(DASH_NAME, DashX, DashY, DASH_W, DASH_H, COLOR_FORMAT_ARGB_NORMALIZE))
     {
      Print("MolidoDash: cannot create canvas (", GetLastError(), ")");
      return(false);
     }
   ObjectSetInteger(0, DASH_NAME, OBJPROP_CORNER, DashCorner);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_XDISTANCE, DashX);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_YDISTANCE, DashY);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_BACK, false);
   g_dash_ready = true;
   return(true);
  }

string DashMoney(const double value)
  {
   return DoubleToString(value, 2);
  }

string DashVerdictName(const ENUM_DEMO_VERDICT v)
  {
   if(v == DEMO_APPROVE) return "APPROVE";
   if(v == DEMO_REDUCE)  return "REDUCE";
   return "BLOCK";
  }

void DashOpenBook(int &count, double &lots)
  {
   count = PositionsTotal();
   lots = 0.0;
   for(int i = count - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) != 0)
         lots += PositionGetDouble(POSITION_VOLUME);
     }
  }

double DashSpreadPts()
  {
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      return 0.0;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
      return 0.0;
   return (ask - bid) / point;
  }

string DashNextBar()
  {
   datetime bar = iTime(_Symbol, ScalperTF, 0);
   int step = PeriodSeconds(ScalperTF);
   if(bar <= 0 || step <= 0)
      return "n/a";
   datetime next = bar + step;
   int left = (int)(next - TimeCurrent());
   if(left < 0)
      left = 0;
   return TimeToString(next, TIME_MINUTES) + "  (" + IntegerToString(left) + "s)";
  }

string DashLinkStatus()
  {
   string pub = "local only";
   if(StringLen(PublishUrl) > 0)
     {
      if(g_publish_status > 0)       pub = "publish ok";
      else if(g_publish_status < 0)  pub = "publish fail";
      else                           pub = "publish idle";
     }
   string cfg = "no config";
   if(StringLen(ResolvedConfigUrl()) > 0)
     {
      if(g_config_status > 0)        cfg = "config ok";
      else if(g_config_status < 0)   cfg = "config fail";
      else                           cfg = "config idle";
     }
   return pub + " / " + cfg;
  }

uint DashArgb(const color clr)
  {
   return ColorToARGB(clr, 255);
  }

void DashLine(const int x, const int y, const string label, const string value, const color vcol)
  {
   g_dash.FontSet("Segoe UI", 11);
   g_dash.TextOut(x, y, label, DashArgb(C'139,147,167'), 0);
   g_dash.FontSet("Segoe UI Bold", 11);
   g_dash.TextOut(x + 92, y, value, DashArgb(vcol), 0);
  }

void MolidoDashRedraw()
  {
   if(!MolidoDashEnsure())
      return;

   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   long mode  = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string acc = (mode == ACCOUNT_TRADE_MODE_DEMO ? "DEMO " : (mode == ACCOUNT_TRADE_MODE_REAL ? "REAL " : "CONTEST "));
   acc += IntegerToString(login);

   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double daily_pct = 0.0;
   bool daily_ok = DemoDailyPnlPct(daily_pct);
   double daily_money = 0.0;
   if(daily_ok)
     {
      double start_eq = eq / (1.0 + daily_pct / 100.0);
      if(start_eq > 0.0)
         daily_money = eq - start_eq;
     }
   double cap = DemoActiveDailyPct();
   double dd_pct = 0.0, start_eq = 0.0;
   DemoMaxDdPct(dd_pct, start_eq);

   string scalper_st, scalper_why;
   DemoScalperStatus(scalper_st, scalper_why);

   string brain = "—  waiting";
   color brain_col = C'139,147,167';
   if(StringLen(g_last_verdict) > 0 && g_last_verdict != "—")
     {
      brain = g_last_verdict;
      if(StringLen(g_last_verdict_symbol) > 0)
         brain += "  " + g_last_verdict_symbol;
      if(g_last_verdict == "APPROVE") brain_col = C'61,220,151';
      else if(g_last_verdict == "REDUCE") brain_col = C'245,192,106';
      else brain_col = C'255,92,122';
     }

   int pos_n = 0;
   double pos_lots = 0.0;
   DashOpenBook(pos_n, pos_lots);

   color st_col = C'61,220,151';
   if(StringFind(scalper_st, "ARMED") < 0)
      st_col = C'255,92,122';
   color day_col = C'232,236,241';
   if(daily_ok && daily_pct < 0)
      day_col = C'255,92,122';
   else if(daily_ok && daily_pct > 0)
      day_col = C'61,220,151';

   string day_line = (daily_ok ? (daily_money >= 0 ? "+" : "") + DashMoney(daily_money) +
                      "   " + DoubleToString(daily_pct, 2) + "% / " + DoubleToString(cap, 2) + "%"
                      : "n/a");
   if(DemoActiveMaxDdPct() > 0.0)
      day_line += "   DD " + DoubleToString(dd_pct, 2) + "% / " + DoubleToString(DemoActiveMaxDdPct(), 2) + "%";

   string news_line = DemoNextNewsLine();
   color news_col = C'232,236,241';
   if(StringFind(news_line, "none soon") < 0)
      news_col = C'245,192,106';
   string kill = DemoKillEngaged() ? "ON" : "off";
   color kill_col = DemoKillEngaged() ? C'255,92,122' : C'139,147,167';
   string preset = (RiskPreset == RISK_PRESET_FTMO ? "FTMO" : "Scalper");
   string status_why = scalper_st;
   if(StringLen(scalper_why) > 0 && StringFind(scalper_st, "ARMED") < 0)
      status_why = scalper_st + "  " + scalper_why;
   if(StringLen(status_why) > 36)
      status_why = StringSubstr(status_why, 0, 36);

   string sig = MOLIDO_EA_VERSION + acc + DashMoney(bal) + DashMoney(eq) + day_line + status_why +
                brain + IntegerToString(pos_n) + DashMoney(pos_lots) + DoubleToString(DashSpreadPts(), 1) +
                DashNextBar() + news_line + kill + DashLinkStatus() + preset +
                IntegerToString((int)TerminalInfoInteger(TERMINAL_CONNECTED));
   if(sig == g_dash_sig)
      return;
   g_dash_sig = sig;

   color bg     = C'16,18,24';
   color panel  = C'22,25,33';
   color edge   = C'42,47,58';
   color gold   = C'201,162,39';
   color text   = C'232,236,241';
   color muted  = C'139,147,167';

   g_dash.Erase(DashArgb(bg));
   g_dash.FillRectangle(0, 0, DASH_W - 1, DASH_H - 1, DashArgb(panel));
   g_dash.Rectangle(0, 0, DASH_W - 1, DASH_H - 1, DashArgb(edge));
   g_dash.FillRectangle(0, 0, DASH_W - 1, 3, DashArgb(gold));

   g_dash.FontSet("Segoe UI Bold", 13);
   g_dash.TextOut(14, 12, "MOLIDO  " + MOLIDO_EA_VERSION, DashArgb(text), 0);
   g_dash.FontSet("Segoe UI", 10);
   g_dash.TextOut(210, 14, preset, DashArgb(gold), 0);

   int y = 36;
   int x = 14;
   int row = 19;
   DashLine(x, y, "Account", acc, (mode == ACCOUNT_TRADE_MODE_DEMO ? C'61,220,151' : C'255,92,122'));
   y += row;
   DashLine(x, y, "Balance", DashMoney(bal) + "   eq " + DashMoney(eq), text);
   y += row;
   DashLine(x, y, "Day P/L", day_line, day_col);
   y += row;
   DashLine(x, y, "Scalper", status_why, st_col);
   y += row;
   DashLine(x, y, "Brain", brain, brain_col);
   if(StringLen(g_last_reason) > 0 && g_last_verdict == "BLOCK")
     {
      string why = g_last_reason;
      if(StringLen(why) > 34)
         why = StringSubstr(why, 0, 34);
      y += 15;
      g_dash.FontSet("Segoe UI", 10);
      g_dash.TextOut(x + 92, y, why, DashArgb(muted), 0);
     }
   y += row;
   DashLine(x, y, "Positions", IntegerToString(pos_n) + "    lots " + DashMoney(pos_lots) +
            " / " + IntegerToString(DemoActiveMaxPositions()), text);
   y += row;
   DashLine(x, y, "Spread", DoubleToString(DashSpreadPts(), 1) + " pts  " + _Symbol, text);
   y += row;
   DashLine(x, y, "Next " + TimeframeName(ScalperTF), DashNextBar(), text);
   y += row;
   DashLine(x, y, "News", news_line, news_col);
   y += row;
   DashLine(x, y, "Kill", kill, kill_col);
   y += row;
   DashLine(x, y, "Link", DashLinkStatus(), muted);

   g_dash.Update();
   ChartRedraw(0);
  }

void MolidoDashOnInit()
  {
   g_dash_sig = "";
   g_dash_last_ms = 0;
   if(ShowDashboard)
      MolidoDashRedraw();
  }

void MolidoDashOnTick()
  {
   if(!ShowDashboard)
      return;
   uint now = GetTickCount();
   if(g_dash_last_ms != 0 && (now - g_dash_last_ms) < 1000)
      return;
   g_dash_last_ms = now;
   MolidoDashRedraw();
  }

void MolidoDashOnTimer()
  {
   MolidoDashRedraw();
  }

void MolidoDashOnDeinit()
  {
   MolidoDashDestroy();
  }

#endif // MOLIDO_DASHBOARD_MQH

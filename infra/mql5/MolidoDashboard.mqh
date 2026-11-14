//+------------------------------------------------------------------+
//| MolidoDashboard.mqh - on-chart status panel (CCanvas).           |
//| Dark theme, sectioned, font-scaled, low CPU (1 Hz, sig cache).   |
//| Objects and buttons are destroyed in MolidoDashOnDeinit.         |
//+------------------------------------------------------------------+
#ifndef MOLIDO_DASHBOARD_MQH
#define MOLIDO_DASHBOARD_MQH

#include <Canvas/Canvas.mqh>

#define DASH_NAME      "MolidoDash_canvas"
#define DASH_BTN_KILL  "MolidoDash_btnKill"
#define DASH_BTN_FOLD  "MolidoDash_btnFold"
#define DASH_BTN_SC    "MolidoDash_btnScalper"
#define DASH_BTN_NX    "MolidoDash_btnNews"
#define DASH_BTN_TR    "MolidoDash_btnTrend"
#define DASH_BTN_AU    "MolidoDash_btnAuto"
#define DASH_BTN_UPD   "MolidoDash_btnUpdate"
#define DASH_MARK      "MolidoTrade_"
#define DASH_GV_FOLD   "Molido.DashCollapsed"

CCanvas g_dash;
bool    g_dash_ready   = false;
string  g_dash_sig     = "";
uint    g_dash_last_ms = 0;
int     g_dash_w       = 0;
int     g_dash_h       = 0;
bool    g_dash_fold    = false;
string  g_marks_sig    = "";

double DashScale()
  {
   double s = DashFontScale;
   if(s < 1.0)
      s = 1.0;
   if(s > 2.2)
      s = 2.2;
   return(s);
  }

int DashPx(const int base)
  {
   int v = (int)MathRound(base * DashScale());
   if(v < 1)
      v = 1;
   return(v);
  }

int DashFontSize(const int base)
  {
   int v = (int)MathRound(base * DashScale());
   if(v < 9)
      v = 9;
   return(v);
  }

int DashPanelW()
  {
   return(DashPx(336));
  }

int DashPanelH()
  {
   if(g_dash_fold)
      return(DashPx(52));
   int h = 698;
   if(ProfileIsProp())
      h += 120;
   h += 70;
   if(g_update_ready || g_update_pending)
      h += 46;
   if(!MolidoLinkHealthy())
      h += 24;
   return(DashPx(h));
  }

void DashFont(const string face, const int base)
  {
   int sz = DashFontSize(base);
   if(!g_dash.FontSet(face, sz))
      g_dash.FontSet("Tahoma", sz, 0, 0);
  }

uint DashArgb(const color c)
  {
   return(ColorToARGB(c, 255));
  }

void DashFillRound(const int x1, const int y1, const int x2, const int y2,
                   const int r, const uint col)
  {
   int rad = r;
   int w = x2 - x1;
   int h = y2 - y1;
   if(rad * 2 > w)
      rad = w / 2;
   if(rad * 2 > h)
      rad = h / 2;
   if(rad < 1)
     {
      g_dash.FillRectangle(x1, y1, x2, y2, col);
      return;
     }
   g_dash.FillRectangle(x1 + rad, y1, x2 - rad, y2, col);
   g_dash.FillRectangle(x1, y1 + rad, x2, y2 - rad, col);
   g_dash.FillCircle(x1 + rad, y1 + rad, rad, col);
   g_dash.FillCircle(x2 - rad, y1 + rad, rad, col);
   g_dash.FillCircle(x1 + rad, y2 - rad, rad, col);
   g_dash.FillCircle(x2 - rad, y2 - rad, rad, col);
  }

void DashLine(const int x, const int y, const string label, const string value,
              const color value_col, const int col2)
  {
   color muted = C'148,156,176';
   DashFont("Segoe UI", 11);
   g_dash.TextOut(x, y, label, DashArgb(muted), 0);
   DashFont("Segoe UI Semibold", 12);
   if(!g_dash.FontSet("Segoe UI Semibold", DashFontSize(12)))
      DashFont("Segoe UI", 12);
   g_dash.TextOut(x + col2, y, value, DashArgb(value_col), 0);
  }

void DashSection(int &y, const int x, const int w, const string title)
  {
   y += DashPx(6);
   int h = DashPx(18);
   DashFont("Segoe UI Semibold", 9);
   if(!g_dash.FontSet("Segoe UI Semibold", DashFontSize(9)))
      DashFont("Segoe UI", 9);
   g_dash.TextOut(x, y, title, DashArgb(C'168,150,86'), 0);
   int tw = (int)(StringLen(title) * DashPx(7)) + DashPx(8);
   int ly = y + DashPx(8);
   g_dash.FillRectangle(x + tw, ly, x + w, ly + 1, DashArgb(C'52,58,74'));
   y += h;
  }

void MolidoDashDestroyButtons()
  {
   string names[] = {DASH_BTN_KILL, DASH_BTN_FOLD, DASH_BTN_SC, DASH_BTN_NX,
                     DASH_BTN_TR, DASH_BTN_AU, DASH_BTN_UPD};
   for(int i = 0; i < ArraySize(names); i++)
     {
      if(ObjectFind(0, names[i]) >= 0)
         ObjectDelete(0, names[i]);
     }
  }

void MolidoMarksDestroy()
  {
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, DASH_MARK) == 0)
         ObjectDelete(0, name);
     }
   g_marks_sig = "";
  }

void MolidoDashDestroy()
  {
   if(g_dash_ready)
     {
      g_dash.Destroy();
      g_dash_ready = false;
     }
   g_dash_sig = "";
   g_dash_w = 0;
   g_dash_h = 0;
   if(ObjectFind(0, DASH_NAME) >= 0)
      ObjectDelete(0, DASH_NAME);
   MolidoDashDestroyButtons();
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, "MolidoDash_") == 0)
         ObjectDelete(0, name);
     }
   ChartRedraw(0);
  }

bool DashCollapsed()
  {
   if(GlobalVariableCheck(DASH_GV_FOLD))
      return(GlobalVariableGet(DASH_GV_FOLD) > 0.5);
   return(false);
  }

void DashSetCollapsed(const bool on)
  {
   GlobalVariableSet(DASH_GV_FOLD, on ? 1.0 : 0.0);
   g_dash_fold = on;
   g_dash_sig = "";
   MolidoDashDestroy();
  }

void DashPlaceButton(const string name, const string caption, const int x,
                     const int y, const int w, const int h, const color bg,
                     const color fg)
  {
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
     }
   ObjectSetInteger(0, name, OBJPROP_CORNER, DashCorner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, C'42,47,58');
   ObjectSetString(0, name, OBJPROP_FONT, "Segoe UI Semibold");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, DashFontSize(9));
   ObjectSetString(0, name, OBJPROP_TEXT, caption);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 100);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
  }

void MolidoDashPlaceButtons()
  {
   int x = DashX;
   int y = DashY;
   int w = DashPanelW();
   int bw = DashPx(54);
   int bh = DashPx(22);
   int fold_x = x + w - bw - DashPx(10);
   int fold_y = y + DashPx(8);
   DashPlaceButton(DASH_BTN_FOLD, (g_dash_fold ? "+" : "-"), fold_x, fold_y,
                   bw, bh, C'36,40,52', C'232,236,241');
   if(g_dash_fold)
     {
      if(ObjectFind(0, DASH_BTN_KILL) >= 0)
         ObjectDelete(0, DASH_BTN_KILL);
      return;
     }
   bool killed = DemoKillEngaged();
   color kbg = killed ? C'140,36,52' : C'92,28,36';
   color kfg = killed ? C'255,200,206' : C'255,228,230';
   string cap = killed ? "KILL ON" : "KILL";
   int kx = x + DashPx(14);
   int ky = y + DashPanelH() - DashPx(36);
   if(g_update_ready || g_update_pending)
      ky -= DashPx(34);
   DashPlaceButton(DASH_BTN_KILL, cap, kx, ky, DashPx(90), DashPx(24), kbg, kfg);

   int sy = ky - DashPx(32);
   int bw2 = DashPx(72);
   int gap = DashPx(6);
   int sx = x + DashPx(14);
   color on_bg = C'20,72,52';
   color off_bg = C'42,46,58';
   color on_fg = C'180,255,210';
   color off_fg = C'168,174,188';
   DashPlaceButton(DASH_BTN_SC, (StratUseScalper() ? "SC ON" : "SC off"), sx, sy, bw2, DashPx(22),
                   (StratUseScalper() ? on_bg : off_bg), (StratUseScalper() ? on_fg : off_fg));
   DashPlaceButton(DASH_BTN_NX, (StratUseNews() ? "NX ON" : "NX off"), sx + bw2 + gap, sy, bw2, DashPx(22),
                   (StratUseNews() ? on_bg : off_bg), (StratUseNews() ? on_fg : off_fg));
   DashPlaceButton(DASH_BTN_TR, (StratUseTrend() ? "TR ON" : "TR off"), sx + 2 * (bw2 + gap), sy, bw2, DashPx(22),
                   (StratUseTrend() ? on_bg : off_bg), (StratUseTrend() ? on_fg : off_fg));
   DashPlaceButton(DASH_BTN_AU, (StratUseAuto() ? "AU ON" : "AU off"), sx + 3 * (bw2 + gap), sy, bw2, DashPx(22),
                   (StratUseAuto() ? on_bg : off_bg), (StratUseAuto() ? on_fg : off_fg));

   if(g_update_ready)
     {
      DashPlaceButton(DASH_BTN_UPD, "Update now?", x + DashPx(14), y + DashPanelH() - DashPx(32),
                      w - DashPx(28), DashPx(24), C'160,110,20', C'255,242,214');
     }
   else if(g_update_pending)
     {
      DashPlaceButton(DASH_BTN_UPD, "Updating...", x + DashPx(14), y + DashPanelH() - DashPx(32),
                      w - DashPx(28), DashPx(24), C'36,40,52', C'200,206,214');
     }
   else if(ObjectFind(0, DASH_BTN_UPD) >= 0)
      ObjectDelete(0, DASH_BTN_UPD);
  }

void MolidoMarkOne(const string name, const ENUM_OBJECT typ, const datetime t,
                   const double price, const color col, const int code)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, typ, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   if(typ == OBJ_ARROW)
     {
      ObjectSetInteger(0, name, OBJPROP_ARROWCODE, code);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
      ObjectMove(0, name, 0, t, price);
     }
   else if(typ == OBJ_HLINE)
     {
      ObjectSetDouble(0, name, OBJPROP_PRICE, price);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
     }
   else
      ObjectMove(0, name, 0, t, price);
  }

void MolidoMarksSync()
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
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      sig += IntegerToString((long)ticket) + ":" +
             DoubleToString(PositionGetDouble(POSITION_SL), 5) + ":" +
             DoubleToString(PositionGetDouble(POSITION_TP), 5) + ":" +
             DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), 5) + ";";
     }
   if(sig == g_marks_sig)
      return;
   string keep = ";";
   //--- Drop stale open-trade marks, keep recent exit arrows (OUT_).
   int objs = ObjectsTotal(0, 0, -1);
   for(int i = objs - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, DASH_MARK) != 0)
         continue;
      if(StringFind(name, DASH_MARK + "OUT_") == 0)
         continue;
      bool found = false;
      if(StringLen(sig) > 0)
        {
         // ticket lives in the name after the last underscore prefix group
        }
      if(StringFind(name, DASH_MARK + "IN_") == 0 ||
         StringFind(name, DASH_MARK + "SL_") == 0 ||
         StringFind(name, DASH_MARK + "TP_") == 0)
        {
         string rest = StringSubstr(name, StringLen(DASH_MARK) + 3);
         if(StringFind(sig, rest + ":") < 0)
            ObjectDelete(0, name);
         else
            keep += rest + ";";
        }
     }

   //--- Exits: a ticket that was in the previous signature and is gone.
   if(StringLen(g_marks_sig) > 0)
     {
      string prev[];
      int pn = StringSplit(g_marks_sig, ';', prev);
      for(int i = 0; i < pn; i++)
        {
         if(StringLen(prev[i]) <= 0)
            continue;
         int c = StringFind(prev[i], ":");
         if(c <= 0)
            continue;
         string tk = StringSubstr(prev[i], 0, c);
         if(StringFind(sig, tk + ":") >= 0)
            continue;
         ulong ticket = (ulong)StringToInteger(tk);
         if(ticket == 0)
            continue;
         if(!HistorySelect(TimeCurrent() - 14 * 86400, TimeCurrent() + 1))
            continue;
         int deals = HistoryDealsTotal();
         for(int d = deals - 1; d >= 0; d--)
           {
            ulong deal = HistoryDealGetTicket(d);
            if(deal == 0)
               continue;
            if((ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID) != ticket &&
               (ulong)HistoryDealGetInteger(deal, DEAL_TICKET) != ticket)
              {
               // still try POSITION_ID match only
              }
            if((ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID) != ticket)
               continue;
            if((int)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
               continue;
            if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
               continue;
            datetime t = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
            double px = HistoryDealGetDouble(deal, DEAL_PRICE);
            color col = (HistoryDealGetDouble(deal, DEAL_PROFIT) >= 0.0)
                        ? C'61,220,151' : C'255,92,122';
            MolidoMarkOne(DASH_MARK + "OUT_" + tk, OBJ_ARROW, t, px, col, 251);
            break;
           }
        }
     }

   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      string tk = IntegerToString((long)ticket);
      datetime t = (datetime)PositionGetInteger(POSITION_TIME);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      long kind = PositionGetInteger(POSITION_TYPE);
      int code = (kind == POSITION_TYPE_BUY) ? 233 : 234;
      color entry_col = (kind == POSITION_TYPE_BUY) ? C'61,220,151' : C'255,92,122';
      MolidoMarkOne(DASH_MARK + "IN_" + tk, OBJ_ARROW, t, open, entry_col, code);
      if(sl > 0.0)
         MolidoMarkOne(DASH_MARK + "SL_" + tk, OBJ_HLINE, t, sl, C'255,92,122', 0);
      if(tp > 0.0)
         MolidoMarkOne(DASH_MARK + "TP_" + tk, OBJ_HLINE, t, tp, C'61,220,151', 0);
     }
   g_marks_sig = sig;
  }

string DashMoney(const double v)
  {
   return(DoubleToString(v, 2));
  }

void DashOpenBook(int &count, double &lots)
  {
   count = 0;
   lots = 0.0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != DEMO_SCALPER_MAGIC)
         continue;
      count++;
      lots += PositionGetDouble(POSITION_VOLUME);
     }
  }

double DashSpreadPts()
  {
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(ask <= 0.0 || bid <= 0.0 || pt <= 0.0)
      return(0.0);
   return((ask - bid) / pt);
  }

string DashNextBar()
  {
   datetime t0 = iTime(_Symbol, ScalperTF, 0);
   int sec = PeriodSeconds(ScalperTF);
   if(t0 == 0 || sec <= 0)
      return("—");
   int left = (int)(t0 + sec - TimeCurrent());
   if(left < 0)
      left = 0;
   int m = left / 60;
   int s = left % 60;
   string ss = IntegerToString(s);
   if(s < 10)
      ss = "0" + ss;
   return(IntegerToString(m) + ":" + ss);
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
   return(pub + " / " + cfg);
  }

void DashMeter(const int x, const int y, const int w, const int h,
               const double frac, const color fill, const color back)
  {
   double f = frac;
   if(f < 0.0) f = 0.0;
   if(f > 1.0) f = 1.0;
   DashFillRound(x, y, x + w, y + h, DashPx(3), DashArgb(back));
   int fw = (int)MathRound(w * f);
   if(fw > DashPx(4))
      DashFillRound(x, y, x + fw, y + h, DashPx(3), DashArgb(fill));
  }

bool MolidoDashEnsure()
  {
   if(!ShowDashboard)
     {
      MolidoDashDestroy();
      return(false);
     }
   g_dash_fold = DashCollapsed();
   int w = DashPanelW();
   int h = DashPanelH();
   if(g_dash_ready && (g_dash_w != w || g_dash_h != h))
     {
      g_dash.Destroy();
      g_dash_ready = false;
      if(ObjectFind(0, DASH_NAME) >= 0)
         ObjectDelete(0, DASH_NAME);
     }
   if(g_dash_ready)
      return(true);
   if(!g_dash.CreateBitmapLabel(DASH_NAME, DashX, DashY, w, h, COLOR_FORMAT_ARGB_NORMALIZE))
     {
      Print("MolidoDash: CreateBitmapLabel failed ", GetLastError());
      return(false);
     }
   ObjectSetInteger(0, DASH_NAME, OBJPROP_CORNER, DashCorner);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_XDISTANCE, DashX);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_YDISTANCE, DashY);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_BACK, false);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, DASH_NAME, OBJPROP_HIDDEN, true);
   g_dash_ready = true;
   g_dash_w = w;
   g_dash_h = h;
   g_dash_sig = "";
   return(true);
  }

void MolidoDashRedraw()
  {
   if(!MolidoDashEnsure())
      return;
   DemoSmartRefresh(_Symbol);

   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double flt = eq - bal;
   double daily_pct = 0.0;
   bool daily_ok = DemoDailyPnlPct(daily_pct);
   double daily_money = 0.0;
   if(daily_ok)
     {
      double start_day = eq / (1.0 + daily_pct / 100.0);
      if(start_day > 0.0)
         daily_money = eq - start_day;
     }
   double cap = DemoActiveDailyPct();
   double dd_pct = 0.0, start_eq = 0.0;
   DemoMaxDdPct(dd_pct, start_eq);

   string scalper_st, scalper_why;
   DemoScalperStatus(scalper_st, scalper_why);

   int pos_n = 0;
   double pos_lots = 0.0;
   DashOpenBook(pos_n, pos_lots);

   string acc = (mode == ACCOUNT_TRADE_MODE_DEMO ? "Demo " : "LIVE ")
                + IntegerToString(login);
   string brain = "—";
   color brain_col = C'148,156,176';
   if(StringLen(g_last_verdict) > 0 && g_last_verdict != "—")
     {
      brain = g_last_verdict;
      if(StringLen(g_last_verdict_symbol) > 0)
         brain += "  " + g_last_verdict_symbol;
      if(g_last_verdict == "APPROVE") brain_col = C'61,220,151';
      else if(g_last_verdict == "REDUCE") brain_col = C'245,192,106';
      else if(g_last_verdict == "BLOCK") brain_col = C'255,92,122';
     }
   color st_col = C'61,220,151';
   if(StringFind(scalper_st, "ARMED") < 0)
      st_col = C'255,92,122';
   color day_col = C'232,236,241';
   if(daily_ok && daily_pct < 0)
      day_col = C'255,92,122';
   else if(daily_ok && daily_pct > 0)
      day_col = C'61,220,151';
   color flt_col = (flt > 0.0 ? C'61,220,151' : flt < 0.0 ? C'255,92,122' : C'232,236,241');

   string day_line = (daily_ok ? ((daily_money >= 0 ? "+" : "") + DashMoney(daily_money) +
                      "   " + DoubleToString(daily_pct, 2) + "% / " + DoubleToString(cap, 2) + "%")
                      : "n/a");
   if(DemoActiveMaxDdPct() > 0.0)
      day_line += "   DD " + DoubleToString(dd_pct, 2) + "% / " + DoubleToString(DemoActiveMaxDdPct(), 2) + "%";

   string news_line = DemoNextNewsLine();
   color news_col = C'232,236,241';
   if(StringFind(news_line, "none soon") < 0)
      news_col = C'245,192,106';
   string kill = DemoKillEngaged() ? "ON" : "off";
   color kill_col = DemoKillEngaged() ? C'255,92,122' : C'148,156,176';
   string preset = ProfileName();
   string ch_state = ProfileChallengeState();
   double daily_stop = DemoEffectiveDailyStopPct();
   double dd_stop = DemoEffectiveDdStopPct();
   double start_eq2 = 0.0;
   double profit_pct = ProfileProfitPct(start_eq2);
   double target_pct = ProfileProfitTargetPct();
   int trade_days = ProfileTradingDays();
   int min_days = ProfileMinTradingDays();
   double dd_left = 0.0;
   if(DemoActiveMaxDdPct() > 0.0)
      dd_left = DemoActiveMaxDdPct() - dd_pct;
   string target_line = (target_pct > 0.0
      ? ((profit_pct >= 0.0 ? "+" : "") + DoubleToString(profit_pct, 2) + "% / " +
         DoubleToString(target_pct, 2) + "%")
      : "n/a");
   string days_line = IntegerToString(trade_days) + (min_days > 0 ? " / " + IntegerToString(min_days) : "");
   string ddleft_line = (DemoActiveMaxDdPct() > 0.0
      ? DoubleToString(dd_left, 2) + "%  of " + DoubleToString(DemoActiveMaxDdPct(), 2) + "%"
      : "n/a");
   string status_why = scalper_st;
   if(StringLen(scalper_why) > 0 && StringFind(scalper_st, "ARMED") < 0)
      status_why = scalper_st + "  " + scalper_why;
   if(StringLen(status_why) > 28)
      status_why = StringSubstr(status_why, 0, 28);

   string smart1 = DemoSmartLineRegime();
   string smart2 = DemoSmartLineTrend();
   string weekly = DemoWeeklyStatsLine();
   string safe = DemoSafeModeLine();
   string auto_line = DemoAutoRankLine();
   int strength = DemoSignalStrength();
   string flt_txt = (flt >= 0.0 ? "+" : "") + DashMoney(flt);

   string sig = MOLIDO_EA_VERSION + acc + DashMoney(bal) + DashMoney(eq) + DashMoney(flt) +
                day_line + status_why + brain + IntegerToString(pos_n) + DashMoney(pos_lots) +
                DoubleToString(DashSpreadPts(), 1) + DashNextBar() + news_line + kill +
                DashLinkStatus() + preset + ch_state + target_line + days_line + ddleft_line + smart1 + smart2 + weekly + safe + auto_line + IntegerToString(strength) +
                IntegerToString((int)g_dash_fold) + DoubleToString(DashScale(), 2) +
                IntegerToString((int)TerminalInfoInteger(TERMINAL_CONNECTED)) + IntegerToString((int)g_update_ready) + g_update_version + IntegerToString((int)g_update_pending) + IntegerToString((int)MolidoLinkHealthy()) + IntegerToString((int)StratUseScalper()) + IntegerToString((int)StratUseNews()) + IntegerToString((int)StratUseTrend()) + IntegerToString((int)StratUseAuto());
   if(sig == g_dash_sig)
     {
      MolidoDashPlaceButtons();
      MolidoMarksSync();
      return;
     }
   g_dash_sig = sig;

   color bg     = C'12,14,20';
   color panel  = C'18,21,29';
   color card   = C'24,28,38';
   color edge   = C'48,54,68';
   color gold   = C'201,162,39';
   color text   = C'232,236,241';
   color muted  = C'148,156,176';
   color accent = (flt > 0.0 ? C'61,220,151' : flt < 0.0 ? C'255,92,122' : gold);

   g_dash.Erase(DashArgb(bg));
   DashFillRound(0, 0, g_dash_w - 1, g_dash_h - 1, DashPx(10), DashArgb(panel));
   g_dash.FillRectangle(0, 0, g_dash_w - 1, DashPx(3), DashArgb(accent));

   int pad = DashPx(14);
   int col2 = DashPx(102);
   int inner_w = g_dash_w - pad * 2;

   DashFont("Segoe UI Bold", 16);
   g_dash.TextOut(pad, DashPx(10), MOLIDO_EA_NAME + "  " + MOLIDO_EA_VERSION, DashArgb(text), 0);
   DashFont("Segoe UI", 11);
   g_dash.TextOut(pad + DashPx(168), DashPx(14), preset, DashArgb(gold), 0);
   if(!MolidoLinkHealthy())
      g_dash.TextOut(pad, DashPx(34), "SAFE DISCONNECT - managing only", DashArgb(C'255,92,122'), 0);

   if(g_dash_fold)
     {
      DashFont("Segoe UI Semibold", 14);
      if(!g_dash.FontSet("Segoe UI Semibold", DashFontSize(14)))
         DashFont("Segoe UI", 14);
      g_dash.TextOut(pad, DashPx(28), flt_txt, DashArgb(flt_col), 0);
      DashFont("Segoe UI", 11);
      g_dash.TextOut(pad + DashPx(110), DashPx(30), (ProfileIsProp() ? ch_state : preset) + "  " + status_why, DashArgb(st_col), 0);
      g_dash.Update();
      MolidoDashPlaceButtons();
      MolidoMarksSync();
      ChartRedraw(0);
      return;
     }

   int y = DashPx(36);
   int x = pad;
   int row = DashPx(18);

   DashSection(y, x, inner_w, "▸  ACCOUNT");
   DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                 y + DashPx(68), DashPx(8), DashArgb(card));
   DashLine(x, y, "Account", acc, (mode == ACCOUNT_TRADE_MODE_DEMO ? C'61,220,151' : C'255,92,122'), col2);
   y += row;
   DashLine(x, y, "Balance", DashMoney(bal) + "    eq " + DashMoney(eq), text, col2);
   y += row;
   DashLine(x, y, "Float P/L", flt_txt, flt_col, col2);
   y += DashPx(22);

   if(ProfileIsProp())
     {
      color stc = C'61,220,151';
      if(ch_state == "NEAR DD") stc = C'255,92,122';
      else if(ch_state == "PACING" || ch_state == "CONSISTENCY") stc = C'245,192,106';
      else if(ch_state == "TARGET HIT") stc = C'61,220,151';
      DashSection(y, x, inner_w, "▸  CHALLENGE");
      DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                    y + DashPx(128), DashPx(8), DashArgb(card));
      DashFont("Segoe UI Bold", 16);
      g_dash.TextOut(x, y, preset + "  " + ch_state, DashArgb(stc), 0);
      y += DashPx(22);
      color tcol = (target_pct > 0.0 && profit_pct >= target_pct)
                   ? C'61,220,151'
                   : (profit_pct < 0.0 ? C'255,92,122' : text);
      DashLine(x, y, "Target", target_line, tcol, col2);
      y += row;
      double tprog = (target_pct > 0.0 ? MathMax(0.0, MathMin(1.0, profit_pct / target_pct)) : 0.0);
      color tbar = (tprog >= 1.0 ? C'61,220,151' : C'201,162,39');
      DashFont("Segoe UI", 10);
      g_dash.TextOut(x, y, "Progress", DashArgb(muted), 0);
      DashMeter(x + col2, y + DashPx(4), inner_w - col2 - DashPx(40), DashPx(10), tprog, tbar, C'36,40,52');
      DashFont("Segoe UI Semibold", 11);
      g_dash.TextOut(x + inner_w - DashPx(36), y, DoubleToString(tprog * 100.0, 0) + "%", DashArgb(tbar), 0);
      y += row;
      string ddbuf = (dd_stop > 0.0
                      ? DoubleToString(dd_pct, 2) + "% / buf " + DoubleToString(dd_stop, 2) +
                        "% (lim " + DoubleToString(DemoActiveMaxDdPct(), 2) + "%)"
                      : "n/a");
      color dcol = (dd_stop > 0.0 && dd_pct >= dd_stop * 0.8) ? C'255,92,122' : text;
      DashLine(x, y, "DD", ddbuf, dcol, col2);
      y += row;
      string daybuf = DoubleToString(daily_pct, 2) + "% / buf " + DoubleToString(daily_stop, 2) + "%";
      DashLine(x, y, "Daily", daybuf, day_col, col2);
      y += row;
      DashLine(x, y, "Days", days_line, text, col2);
      y += DashPx(22);
     }
   else
     {
      DashSection(y, x, inner_w, "▸  PROFILE");
      DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                    y + DashPx(84), DashPx(8), DashArgb(card));
      color pcol = (AccountProfile == PROFILE_LIVE_REAL
                    ? (DemoAccountOk() ? C'245,192,106' : C'255,92,122')
                    : C'201,162,39');
      DashLine(x, y, "Profile", preset, pcol, col2);
      y += row;
      color tcol = (target_pct > 0.0 && profit_pct >= target_pct)
                   ? C'61,220,151'
                   : (profit_pct < 0.0 ? C'255,92,122' : text);
      DashLine(x, y, "Target", target_line, tcol, col2);
      y += row;
      color dcol = (dd_left <= 0.0 && DemoActiveMaxDdPct() > 0.0) ? C'255,92,122' : text;
      DashLine(x, y, "DD left", ddleft_line, dcol, col2);
      y += row;
      DashLine(x, y, "Days", days_line, text, col2);
      y += DashPx(22);
     }

   DashSection(y, x, inner_w, "▸  RISK");
   DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                 y + DashPx(48), DashPx(8), DashArgb(card));
   DashLine(x, y, "Day P/L", day_line, day_col, col2);
   y += row;
   double used = 0.0;
   double cap_show = (ProfileIsProp() && daily_stop > 0.0 ? daily_stop : cap);
   if(daily_ok && cap_show > 0.0 && daily_pct < 0.0)
      used = MathMin(1.0, (-daily_pct) / cap_show);
   color bar = (used >= 0.8 ? C'255,92,122' : used >= 0.5 ? C'245,192,106' : C'61,220,151');
   DashFont("Segoe UI", 10);
   g_dash.TextOut(x, y, "Daily cap", DashArgb(muted), 0);
   DashMeter(x + col2, y + DashPx(4), inner_w - col2, DashPx(10), used, bar, C'36,40,52');
   string used_txt = DoubleToString(used * 100.0, 0) + "%";
   DashFont("Segoe UI", 9);
   g_dash.TextOut(x + inner_w - DashPx(36), y - DashPx(1), used_txt, DashArgb(muted), 0);
   y += DashPx(22);

   DashSection(y, x, inner_w, "▸  SIGNAL");
   int sig_h = DashPx(70);
   if(StringLen(g_last_reason) > 0 && g_last_verdict == "BLOCK")
      sig_h += DashPx(16);
   DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                 y + sig_h, DashPx(8), DashArgb(card));
   DashLine(x, y, "Scalper", status_why, st_col, col2);
   y += row;
   DashLine(x, y, "Brain", brain, brain_col, col2);
   if(StringLen(g_last_reason) > 0 && g_last_verdict == "BLOCK")
     {
      string why = g_last_reason;
      if(StringLen(why) > 28)
         why = StringSubstr(why, 0, 28);
      y += DashPx(16);
      DashFont("Segoe UI", 10);
      g_dash.TextOut(x + col2, y, why, DashArgb(muted), 0);
     }
   y += row;
   DashFont("Segoe UI", 11);
   g_dash.TextOut(x, y, "Strength", DashArgb(muted), 0);
   color mcol = (strength >= 70 ? C'61,220,151' : strength >= 40 ? C'245,192,106' : C'255,92,122');
   DashMeter(x + col2, y + DashPx(4), inner_w - col2 - DashPx(40), DashPx(10),
             strength / 100.0, mcol, C'36,40,52');
   DashFont("Segoe UI Semibold", 11);
   if(!g_dash.FontSet("Segoe UI Semibold", DashFontSize(11)))
      DashFont("Segoe UI", 11);
   g_dash.TextOut(x + inner_w - DashPx(32), y, IntegerToString(strength), DashArgb(mcol), 0);
   y += DashPx(22);

   DashSection(y, x, inner_w, "▸  MARKET");
   DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                 y + DashPx(104), DashPx(8), DashArgb(card));
   DashLine(x, y, "Positions", IntegerToString(pos_n) + "    lots " + DashMoney(pos_lots) +
            " / " + IntegerToString(DemoActiveMaxPositions()), text, col2);
   y += row;
   DashLine(x, y, "Spread", DoubleToString(DashSpreadPts(), 1) + " pts   " + _Symbol, text, col2);
   y += row;
   DashLine(x, y, "Next " + TimeframeName(ScalperTF), DashNextBar(), text, col2);
   y += row;
   DashLine(x, y, "News", news_line, news_col, col2);
   y += row;
   DashLine(x, y, "Auto", auto_line, text, col2);
   y += DashPx(22);

   DashSection(y, x, inner_w, "▸  SMART");
   DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                 y + DashPx(86), DashPx(8), DashArgb(card));
   DashFont("Segoe UI", 11);
   g_dash.TextOut(x, y, smart1, DashArgb(text), 0);
   y += row;
   g_dash.TextOut(x, y, smart2, DashArgb(text), 0);
   y += row;
   color scol = (StringFind(safe, "STOP") >= 0 ? C'255,92,122' :
                 StringFind(safe, "REDUCE") >= 0 ? C'245,192,106' : text);
   DashLine(x, y, "Safe", safe, scol, col2);
   y += row;
   DashLine(x, y, "Week", weekly, text, col2);
   y += DashPx(22);

   DashSection(y, x, inner_w, "▸  STATUS");
   DashFillRound(x - DashPx(4), y - DashPx(2), x + inner_w + DashPx(4),
                 y + DashPx(44), DashPx(8), DashArgb(card));
   DashLine(x, y, "Kill", kill, kill_col, col2);
   y += row;
   DashLine(x, y, "Link", DashLinkStatus(), muted, col2);

   g_dash.Update();
   MolidoDashPlaceButtons();
   MolidoMarksSync();
   ChartRedraw(0);
  }

void MolidoDashOnInit()
  {
   if(MolidoIsTester() && !MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   g_dash_fold = DashCollapsed();
   g_dash_sig = "";
   if(ShowDashboard)
      MolidoDashEnsure();
  }

void MolidoDashOnTick()
  {
   if(MolidoIsTester() && !MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   if(!ShowDashboard && ObjectFind(0, DASH_NAME) < 0)
     {
      MolidoMarksSync();
      return;
     }
   uint now = GetTickCount();
   if(g_dash_last_ms != 0 && (now - g_dash_last_ms) < 1000)
      return;
   g_dash_last_ms = now;
   MolidoDashRedraw();
  }

void MolidoDashOnTimer()
  {
   MolidoDashOnTick();
  }

void MolidoDashOnDeinit()
  {
   MolidoMarksDestroy();
   MolidoDashDestroy();
  }

void MolidoDashOnChartEvent(const int id, const long &lparam,
                            const double &dparam, const string &sparam)
  {
   if(id != CHARTEVENT_OBJECT_CLICK)
      return;
   if(sparam == DASH_BTN_FOLD)
     {
      ObjectSetInteger(0, DASH_BTN_FOLD, OBJPROP_STATE, false);
      DashSetCollapsed(!DashCollapsed());
      MolidoDashRedraw();
      return;
     }
   if(sparam == DASH_BTN_KILL)
     {
      ObjectSetInteger(0, DASH_BTN_KILL, OBJPROP_STATE, false);
      //--- Safe: the button can always engage the file kill switch.
      //--- Clearing it never overrides the ScalperKillSwitch input.
      bool on = DemoKillEngaged();
      if(!on)
         DemoKillSet(true);
      else
         DemoKillSet(false);
      g_dash_sig = "";
      MolidoDashRedraw();
      return;
     }
   if(sparam == DASH_BTN_SC || sparam == DASH_BTN_NX || sparam == DASH_BTN_TR || sparam == DASH_BTN_AU)
     {
      ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      if(sparam == DASH_BTN_SC) StratSet("scalper", !StratUseScalper());
      if(sparam == DASH_BTN_NX) StratSet("news", !StratUseNews());
      if(sparam == DASH_BTN_TR) StratSet("trend", !StratUseTrend());
      if(sparam == DASH_BTN_AU) StratSet("auto", !StratUseAuto());
      g_dash_sig = "";
      MolidoDashRedraw();
      return;
     }
   if(sparam == DASH_BTN_UPD)
     {
      ObjectSetInteger(0, DASH_BTN_UPD, OBJPROP_STATE, false);
      if(g_update_ready)
         MolidoRequestUpdate();
      g_dash_sig = "";
      MolidoDashRedraw();
     }
  }

#endif

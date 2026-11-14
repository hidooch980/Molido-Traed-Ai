//+------------------------------------------------------------------+
//| MolidoExpertUI.mqh - Molido Expert – AI Trading Power dashboard  |
//| Native CCanvas / objects only. Does not cover the full chart.    |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_UI_MQH
#define MOLIDO_EXPERT_UI_MQH

#include <Canvas/Canvas.mqh>

#define EX_NAME      "MolidoExpertDash"
#define EX_BTN       "ExDash_"
#define EX_MARK      "ExMark_"

#define EX_NAVY   C'6,10,22'
#define EX_PANEL  C'12,18,36'
#define EX_GLASS  C'18,26,48'
#define EX_CARD   C'22,32,58'
#define EX_GOLD   C'212,175,90'
#define EX_BLUE   C'56,180,255'
#define EX_GREEN  C'46,220,150'
#define EX_AMBER  C'245,186,74'
#define EX_CORAL  C'255,107,107'
#define EX_TEXT   C'230,236,246'
#define EX_MUTED  C'140,158,190'
#define EX_LINE   C'40,60,96'

CCanvas g_ex;
bool    g_ex_ready = false;
bool    g_ex_fold  = false;
int     g_ex_w = 0, g_ex_h = 0, g_ex_x = 10, g_ex_y = 10;
int     g_ex_scroll = 0, g_ex_content_h = 0;
uint    g_ex_last_ms = 0;
string  g_ex_sig = "";
bool    g_ex_sec[10];
int     g_ex_cpu_hint = 0;

string ExTr(const string key)
  {
   int L = MolidoLangId();
   if(key == "title")   return(L==LANG_FA ? "مولیدو اکسپرت" : L==LANG_AR ? "موليدو إكسبرت" : L==LANG_TR ? "Molido Expert" : "Molido Expert");
   if(key == "active")  return(L==LANG_FA ? "فعال" : L==LANG_AR ? "نشط" : L==LANG_TR ? "Aktif" : "Active");
   if(key == "off")     return(L==LANG_FA ? "خاموش" : L==LANG_AR ? "متوقف" : L==LANG_TR ? "Kapalı" : "Off");
   if(key == "on")      return(L==LANG_FA ? "روشن" : L==LANG_AR ? "تشغيل" : L==LANG_TR ? "Açık" : "On");
   if(key == "brain")   return(L==LANG_FA ? "مغز هوش مصنوعی" : L==LANG_AR ? "الدماغ" : L==LANG_TR ? "AI Beyin" : "AI Brain");
   if(key == "disc")    return(L==LANG_FA ? "قطع ارتباط" : L==LANG_AR ? "غير متصل" : L==LANG_TR ? "Bağlı değil" : "Disconnected");
   if(key == "conn")    return(L==LANG_FA ? "متصل" : L==LANG_AR ? "متصل" : L==LANG_TR ? "Bağlı" : "Connected");
   if(key == "agents")  return(L==LANG_FA ? "عامل‌ها" : L==LANG_AR ? "الوكلاء" : L==LANG_TR ? "Ajanlar" : "Agents");
   if(key == "council") return(L==LANG_FA ? "شورا" : L==LANG_AR ? "المجلس" : L==LANG_TR ? "Konsey" : "Council");
   if(key == "anal")    return(L==LANG_FA ? "تحلیل" : L==LANG_AR ? "تحليل" : L==LANG_TR ? "Analiz" : "Analysis");
   if(key == "learn")   return(L==LANG_FA ? "یادگیری" : L==LANG_AR ? "التعلم" : L==LANG_TR ? "Öğrenme" : "Learning");
   if(key == "risk")    return(L==LANG_FA ? "ریسک" : L==LANG_AR ? "المخاطر" : L==LANG_TR ? "Risk" : "Risk");
   if(key == "hybrid")  return("HYBRID");
   if(key == "chart")   return(L==LANG_FA ? "نمودار" : L==LANG_AR ? "الرسم" : L==LANG_TR ? "Grafik" : "Chart");
   if(key == "trade")   return(L==LANG_FA ? "معاملات" : L==LANG_AR ? "التداول" : L==LANG_TR ? "İşlem" : "Trade");
   if(key == "buy")     return(L==LANG_FA ? "خرید" : L==LANG_AR ? "شراء" : L==LANG_TR ? "AL" : "BUY");
   if(key == "sell")    return(L==LANG_FA ? "فروش" : L==LANG_AR ? "بيع" : L==LANG_TR ? "SAT" : "SELL");
   if(key == "close")   return(L==LANG_FA ? "بستن موقعیت" : L==LANG_AR ? "إغلاق" : L==LANG_TR ? "Kapat" : "CLOSE POSITION");
   if(key == "closeall")return(L==LANG_FA ? "بستن همه" : L==LANG_AR ? "إغلاق الكل" : L==LANG_TR ? "Tümünü kapat" : "CLOSE ALL");
   if(key == "auto")    return(L==LANG_FA ? "خودکار" : L==LANG_AR ? "تلقائي" : L==LANG_TR ? "Oto" : "AUTO");
   if(key == "stopnew") return(L==LANG_FA ? "توقف ورود جدید" : L==LANG_AR ? "إيقاف الصفقات الجديدة" : L==LANG_TR ? "Yeni işlem yok" : "STOP NEW");
   if(key == "groups")  return(L==LANG_FA ? "گروه‌های عامل" : L==LANG_AR ? "مجموعات الوكلاء" : L==LANG_TR ? "Ajan grupları" : "Agent groups");
   if(key == "perf")    return(L==LANG_FA ? "عملکرد استراتژی" : L==LANG_AR ? "الأداء" : L==LANG_TR ? "Performans" : "Strategy performance");
   if(key == "nodata")  return(L==LANG_FA ? "داده‌ای نیست" : L==LANG_AR ? "لا بيانات" : L==LANG_TR ? "Veri yok" : "no data");
   if(key == "markets") return(L==LANG_FA ? "بازارها" : L==LANG_AR ? "الأسواق" : L==LANG_TR ? "Piyasalar" : "Markets");
   if(key == "report")  return(L==LANG_FA ? "گزارش" : L==LANG_AR ? "التقرير" : L==LANG_TR ? "Rapor" : "Report");
   if(key == "forex")   return("Forex");
   if(key == "gold")    return(L==LANG_FA ? "طلا" : L==LANG_AR ? "ذهب" : L==LANG_TR ? "Altın" : "Gold");
   if(key == "crypto")  return("Crypto");
   if(key == "today")   return(L==LANG_FA ? "امروز" : L==LANG_AR ? "اليوم" : L==LANG_TR ? "Bugün" : "Today");
   if(key == "week")    return(L==LANG_FA ? "هفته" : L==LANG_AR ? "الأسبوع" : L==LANG_TR ? "Hafta" : "Week");
   if(key == "month")   return(L==LANG_FA ? "ماه" : L==LANG_AR ? "الشهر" : L==LANG_TR ? "Ay" : "Month");
   if(key == "bal")     return(L==LANG_FA ? "موجودی" : L==LANG_AR ? "الرصيد" : L==LANG_TR ? "Bakiye" : "Balance");
   if(key == "eq")      return(L==LANG_FA ? "دارایی" : L==LANG_AR ? "حقوق" : L==LANG_TR ? "Equity" : "Equity");
   if(key == "margin")  return(L==LANG_FA ? "مارجین آزاد" : L==LANG_AR ? "هامش حر" : L==LANG_TR ? "Serbest teminat" : "Free margin");
   if(key == "open")    return(L==LANG_FA ? "باز" : L==LANG_AR ? "مفتوحة" : L==LANG_TR ? "Açık" : "Open");
   if(key == "strength")return(L==LANG_FA ? "قدرت سیگنال" : L==LANG_AR ? "قوة الإشارة" : L==LANG_TR ? "Sinyal gücü" : "Signal strength");
   if(key == "lot")     return("Lot");
   if(key == "real")    return(Tr("real_unsupported"));
   if(key == "balanced")return(L==LANG_FA ? "متوازن" : L==LANG_AR ? "متوازن" : L==LANG_TR ? "Dengeli" : "Balanced");
   if(key == "smart")   return("Smart TP/SL");
   if(key == "partial") return("Partial Close");
   if(key == "be")      return("Break Even");
   if(key == "trail")   return("Trailing");
   if(key == "news")    return("News Filter");
   if(key == "rocket")  return("Rocket");
   if(key == "impl_no") return(L==LANG_FA ? "پیاده‌سازی نشده" : "not implemented");
   return(key);
  }

int ExPx(const int base)
  {
   double s = DashFontScale;
   if(s < 1.0) s = 1.0;
   if(s > 1.8) s = 1.8;
   int v = (int)MathRound(base * s);
   return(v < 1 ? 1 : v);
  }

int ExFontSz(const int base)
  {
   int v = ExPx(base);
   return(v < 8 ? 8 : v);
  }

void ExFont(const string face, const int base)
  {
   int sz = ExFontSz(base);
   string ui = MolidoUiFont(StringFind(face, "Bold") >= 0 || StringFind(face, "Semibold") >= 0);
   if(!g_ex.FontSet(ui, sz))
      if(!g_ex.FontSet(face, sz))
         g_ex.FontSet("Tahoma", sz, 0, 0);
  }

uint ExArgb(const color c, const uchar a = 255)
  {
   return(ColorToARGB(c, a));
  }

void ExRound(const int x1, const int y1, const int x2, const int y2, const int r, const uint col)
  {
   int rad = r, w = x2 - x1, h = y2 - y1;
   if(rad * 2 > w) rad = w / 2;
   if(rad * 2 > h) rad = h / 2;
   if(rad < 1) { g_ex.FillRectangle(x1, y1, x2, y2, col); return; }
   g_ex.FillRectangle(x1 + rad, y1, x2 - rad, y2, col);
   g_ex.FillRectangle(x1, y1 + rad, x2, y2 - rad, col);
   g_ex.FillCircle(x1 + rad, y1 + rad, rad, col);
   g_ex.FillCircle(x2 - rad, y1 + rad, rad, col);
   g_ex.FillCircle(x1 + rad, y2 - rad, rad, col);
   g_ex.FillCircle(x2 - rad, y2 - rad, rad, col);
  }

void ExGlass(const int x1, const int y1, const int x2, const int y2, const int r)
  {
   ExRound(x1 - 1, y1 - 1, x2 + 1, y2 + 1, r + 1, ExArgb(EX_BLUE, 35));
   ExRound(x1, y1, x2, y2, r, ExArgb(EX_GLASS, 230));
   g_ex.FillRectangle(x1 + r, y1, x2 - r, y1 + 2, ExArgb(EX_GOLD, 90));
  }

void ExIconMark(const int x, const int y, const color c)
  {
   g_ex.FillCircle(x, y, ExPx(5), ExArgb(c, 220));
   g_ex.FillCircle(x, y, ExPx(3), ExArgb(c));
  }

int ExPanelW()
  {
   int cw = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int cap = (int)MathFloor(cw * 0.40);
   if(cap < 300) cap = 300;
   if(cap > 420) cap = 420;
   if(cw > 0 && cap > cw - 80)
      cap = cw - 80;
   if(cap < 260) cap = 260;
   return(cap);
  }

int ExHeaderH() { return(ExPx(g_ex_fold ? 52 : 62)); }
int ExFooterH() { return(g_ex_fold ? 0 : ExPx(78)); }

int ExAvailH()
  {
   int ch = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int avail = ch - g_ex_y - ExPx(24);
   int min_h = ExHeaderH() + ExFooterH() + ExPx(80);
   if(avail < min_h) avail = min_h;
   return(avail);
  }

int ExPanelH()
  {
   if(g_ex_fold)
      return(ExHeaderH());
   int avail = ExAvailH();
   int body = g_ex_content_h;
   if(body < ExPx(160)) body = ExPx(720);
   int need = ExHeaderH() + body + ExFooterH();
   return(need < avail ? need : avail);
  }

int ExMaxScroll()
  {
   int room = ExPanelH() - ExHeaderH() - ExFooterH();
   int mx = g_ex_content_h - room;
   return(mx < 0 ? 0 : mx);
  }

void ExDestroyButtons()
  {
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, EX_BTN) == 0)
         ObjectDelete(0, name);
     }
  }

void ExBtn(const string id, const string cap, const int x, const int y,
           const int w, const int h, const color bg, const color fg)
  {
   string name = EX_BTN + id;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, EX_LINE);
   ObjectSetString(0, name, OBJPROP_FONT, MolidoUiFont(true));
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, ExFontSz(8));
   ObjectSetString(0, name, OBJPROP_TEXT, cap);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 120);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
  }

void ExEdit(const string id, const string val, const int x, const int y,
            const int w, const int h)
  {
   string name = EX_BTN + id;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_EDIT, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, EX_CARD);
   ObjectSetInteger(0, name, OBJPROP_COLOR, EX_TEXT);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, EX_LINE);
   ObjectSetString(0, name, OBJPROP_FONT, MolidoUiFont(false));
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, ExFontSz(8));
   ObjectSetString(0, name, OBJPROP_TEXT, val);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 120);
   ObjectSetInteger(0, name, OBJPROP_READONLY, false);
  }

string ExEditVal(const string id, const string fallback)
  {
   string name = EX_BTN + id;
   if(ObjectFind(0, name) < 0)
      return(fallback);
   string v = ObjectGetString(0, name, OBJPROP_TEXT);
   return(StringLen(v) > 0 ? v : fallback);
  }

void ExReadFields()
  {
   g_ex_lot = StringToDouble(ExEditVal("lot", DoubleToString(g_ex_lot, 2)));
   g_ex_risk_ui = StringToDouble(ExEditVal("risk", DoubleToString(g_ex_risk_ui, 2)));
   g_ex_sl_pts = StringToDouble(ExEditVal("sl", DoubleToString(g_ex_sl_pts, 0)));
   g_ex_tp_pts = StringToDouble(ExEditVal("tp", DoubleToString(g_ex_tp_pts, 0)));
   g_ex_max_pos = (int)StringToInteger(ExEditVal("maxp", IntegerToString(g_ex_max_pos)));
   if(g_ex_lot < 0.0) g_ex_lot = 0.0;
   if(g_ex_risk_ui < 0.0) g_ex_risk_ui = 0.0;
  }

void ExDestroy()
  {
   if(g_ex_ready)
     {
      g_ex.Destroy();
      g_ex_ready = false;
     }
   g_ex_sig = "";
   g_ex_w = 0; g_ex_h = 0;
   if(ObjectFind(0, EX_NAME) >= 0)
      ObjectDelete(0, EX_NAME);
   ExDestroyButtons();
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, EX_MARK) == 0)
         ObjectDelete(0, name);
     }
   ChartRedraw(0);
  }

bool ExEnsure()
  {
   if(!ShowDashboard)
     { ExDestroy(); return(false); }
   int w = ExPanelW();
   int h = ExPanelH();
   if(g_ex_ready && (g_ex_w != w || g_ex_h != h))
     {
      g_ex.Destroy();
      g_ex_ready = false;
      if(ObjectFind(0, EX_NAME) >= 0)
         ObjectDelete(0, EX_NAME);
     }
   if(g_ex_ready)
      return(true);
   if(!g_ex.CreateBitmapLabel(EX_NAME, g_ex_x, g_ex_y, w, h, COLOR_FORMAT_ARGB_NORMALIZE))
     {
      Print("MolidoExpert: CreateBitmapLabel failed ", GetLastError());
      return(false);
     }
   ObjectSetInteger(0, EX_NAME, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, EX_NAME, OBJPROP_XDISTANCE, g_ex_x);
   ObjectSetInteger(0, EX_NAME, OBJPROP_YDISTANCE, g_ex_y);
   ObjectSetInteger(0, EX_NAME, OBJPROP_BACK, false);
   ObjectSetInteger(0, EX_NAME, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, EX_NAME, OBJPROP_HIDDEN, true);
   g_ex_ready = true;
   g_ex_w = w;
   g_ex_h = h;
   g_ex_sig = "";
   return(true);
  }

void ExLine(const int x, const int y, const string label, const string value, const color vc, const int col2)
  {
   ExFont("Segoe UI", 9);
   g_ex.TextOut(x, y, label, ExArgb(EX_MUTED), 0);
   ExFont("Segoe UI Semibold", 10);
   g_ex.TextOut(x + col2, y, value, ExArgb(vc), 0);
  }

int ExSecHead(int &y, const int x, const int w, const int idx, const string title)
  {
   y += ExPx(4);
   ExFont("Segoe UI Semibold", 9);
   string mark = (g_ex_sec[idx] ? "▾  " : "▸  ");
   g_ex.TextOut(x, y, mark + title, ExArgb(EX_BLUE), 0);
   int ly = y + ExPx(8);
   g_ex.FillRectangle(x + ExPx(130), ly, x + w, ly + 1, ExArgb(EX_LINE));
   // click target stored as tiny button on the right
   ExBtn("sec" + IntegerToString(idx), (g_ex_sec[idx] ? "-" : "+"),
         g_ex_x + x + w - ExPx(20), g_ex_y + y, ExPx(18), ExPx(14), EX_CARD, EX_MUTED);
   y += ExPx(16);
   return(y);
  }

void ExPlaceHeaderButtons()
  {
   int x = g_ex_x, y = g_ex_y;
   int w = g_ex_w;
   int lang = MolidoLangId();
   ExBtn("fa", "FA", x + w - ExPx(86), y + ExPx(8), ExPx(28), ExPx(18),
         (lang == LANG_FA ? EX_GOLD : EX_CARD), (lang == LANG_FA ? EX_NAVY : EX_TEXT));
   ExBtn("en", "EN", x + w - ExPx(56), y + ExPx(8), ExPx(28), ExPx(18),
         (lang == LANG_EN || (lang != LANG_FA && lang != LANG_AR && lang != LANG_TR) ? EX_GOLD : EX_CARD),
         EX_NAVY);
   ExBtn("fold", (g_ex_fold ? "+" : "-"), x + w - ExPx(24), y + ExPx(8), ExPx(16), ExPx(18), EX_CARD, EX_TEXT);
  }

void ExPlaceFooterButtons()
  {
   if(g_ex_fold)
     {
      string hide[] = {"buy","sell","close","closeall","auto","stop","up","dn"};
      for(int i = 0; i < ArraySize(hide); i++)
         if(ObjectFind(0, EX_BTN + hide[i]) >= 0)
            ObjectDelete(0, EX_BTN + hide[i]);
      return;
     }
   int x = g_ex_x, y = g_ex_y + g_ex_h - ExFooterH();
   int bw = ExPx(62), bh = ExPx(22), gap = ExPx(4), pad = ExPx(10);
   ExBtn("buy", ExTr("buy"), x + pad, y + ExPx(8), bw, bh, C'16,90,70', EX_GREEN);
   ExBtn("sell", ExTr("sell"), x + pad + bw + gap, y + ExPx(8), bw, bh, C'90,32,40', EX_CORAL);
   ExBtn("close", ExTr("close"), x + pad + 2 * (bw + gap), y + ExPx(8), ExPx(90), bh, EX_CARD, EX_TEXT);
   ExBtn("closeall", ExTr("closeall"), x + pad + 2 * (bw + gap) + ExPx(94), y + ExPx(8), ExPx(70), bh, EX_CARD, EX_MUTED);
   bool auto_on = ExpertAutoOn();
   bool stop = ExpertStopNew();
   ExBtn("auto", ExTr("auto") + " " + (auto_on ? ExTr("on") : ExTr("off")),
         x + pad, y + ExPx(34), ExPx(90), bh, auto_on ? C'16,80,96' : EX_CARD, auto_on ? EX_BLUE : EX_MUTED);
   ExBtn("stop", ExTr("stopnew"),
         x + pad + ExPx(96), y + ExPx(34), ExPx(110), bh, stop ? C'96,32,40' : EX_CARD, stop ? EX_CORAL : EX_TEXT);
   if(ExMaxScroll() > 0)
     {
      ExBtn("up", "^", x + g_ex_w - ExPx(28), y + ExPx(8), ExPx(18), ExPx(16), EX_CARD, EX_BLUE);
      ExBtn("dn", "v", x + g_ex_w - ExPx(28), y + ExPx(28), ExPx(18), ExPx(16), EX_CARD, EX_BLUE);
     }
   else
     {
      if(ObjectFind(0, EX_BTN + "up") >= 0) ObjectDelete(0, EX_BTN + "up");
      if(ObjectFind(0, EX_BTN + "dn") >= 0) ObjectDelete(0, EX_BTN + "dn");
     }
  }

void ExPlaceTfButtons(const int x, const int y)
  {
   string labs[9] = {"M1","M5","M15","M30","H1","H4","D1","W1","MN"};
   ENUM_TIMEFRAMES tfs[9] = {PERIOD_M1,PERIOD_M5,PERIOD_M15,PERIOD_M30,PERIOD_H1,PERIOD_H4,PERIOD_D1,PERIOD_W1,PERIOD_MN1};
   ENUM_TIMEFRAMES cur = (ENUM_TIMEFRAMES)Period();
   int bw = ExPx(28), bh = ExPx(16);
   for(int i = 0; i < 9; i++)
     {
      bool on = (cur == tfs[i]);
      ExBtn("tf" + labs[i], labs[i],
            g_ex_x + x + i * (bw + ExPx(2)), g_ex_y + y, bw, bh,
            on ? EX_BLUE : EX_CARD, on ? EX_NAVY : EX_TEXT);
     }
  }

void ExMarkSync()
  {
   //--- entry / SL / TP for last manual or open positions
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, EX_MARK) == 0)
         ObjectDelete(0, name);
     }
   if(g_ex_last_entry > 0.0 && g_ex_last_side != "")
     {
      color c = (g_ex_last_side == "buy") ? EX_GREEN : EX_CORAL;
      string n = EX_MARK + "SIG";
      ObjectCreate(0, n, OBJ_ARROW, 0, TimeCurrent(), g_ex_last_entry);
      ObjectSetInteger(0, n, OBJPROP_ARROWCODE, (g_ex_last_side == "buy") ? 233 : 234);
      ObjectSetInteger(0, n, OBJPROP_COLOR, c);
      ObjectSetInteger(0, n, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
     }
   if(g_ex_last_sl > 0.0)
     {
      string n = EX_MARK + "SL";
      ObjectCreate(0, n, OBJ_HLINE, 0, 0, g_ex_last_sl);
      ObjectSetInteger(0, n, OBJPROP_COLOR, EX_CORAL);
      ObjectSetInteger(0, n, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
     }
   if(g_ex_last_tp > 0.0)
     {
      string n = EX_MARK + "TP";
      ObjectCreate(0, n, OBJ_HLINE, 0, 0, g_ex_last_tp);
      ObjectSetInteger(0, n, OBJPROP_COLOR, EX_GREEN);
      ObjectSetInteger(0, n, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
     }
  }

string ExMarketKind(const string sym)
  {
   string u = sym;
   StringToUpper(u);
   if(StringFind(u, "XAU") >= 0 || StringFind(u, "XAG") >= 0 || StringFind(u, "GOLD") >= 0)
      return("gold");
   if(StringFind(u, "BTC") >= 0 || StringFind(u, "ETH") >= 0 || StringFind(u, "USDT") >= 0 ||
      StringFind(u, "CRYPTO") >= 0)
      return("crypto");
   return("forex");
  }

void ExCapture()
  {
   static string captured = "";
   if(g_ex_fold)
      return;
   if(captured == MOLIDO_EA_VERSION)
      return;
   int w = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int h = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   if(w < 640) w = 1280;
   if(h < 480) h = 900;
   if(ChartScreenShot(0, "dashboard.png", w, h, ALIGN_LEFT))
      captured = MOLIDO_EA_VERSION;
  }

void MolidoDashRedraw();  // defined below

void MolidoDashOnInit()
  {
   if(MolidoIsTester() && !MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   MolidoI18nInit();
   ExpertBridgeInit();
   for(int i = 0; i < 10; i++)
      g_ex_sec[i] = true;
   g_ex_sig = "";
   if(ShowDashboard)
      ExEnsure();
  }

void MolidoDashOnDeinit()
  {
   ExDestroy();
  }

void MolidoDashOnTick()
  {
   if(MolidoIsTester() && !MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   uint now = GetTickCount();
   if(g_ex_last_ms != 0 && (now - g_ex_last_ms) < 1000)
      return;
   g_ex_last_ms = now;
   MolidoDashRedraw();
  }

void MolidoDashOnTimer()
  {
   MolidoDashOnTick();
  }

void MolidoDashRedraw()
  {
   if(!ExEnsure())
      return;

   bool blocked = MolidoRealBlocked();
   bool linked = ExpertBridgeConnected();
   bool ea_on = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && AllowTrading && !blocked && !DemoKillEngaged();
   ExpertPerf perf;
   ExpertReport rep;
   ExpertScanHistory(perf, rep);
   int strength = DemoSignalStrength();
   string clock = TimeToString(TimeLocal(), TIME_MINUTES);

   string sig = MOLIDO_EA_VERSION + IntegerToString((int)MolidoLangId()) +
                IntegerToString((int)linked) + IntegerToString(g_ai_agents_on) +
                IntegerToString((int)ea_on) + clock + _Symbol + IntegerToString(Period()) +
                IntegerToString((int)g_ex_fold) + IntegerToString(g_ex_scroll) +
                IntegerToString(ExPanelH()) + IntegerToString((int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS)) +
                IntegerToString((int)ExpertAutoOn()) + IntegerToString((int)ExpertStopNew()) +
                DoubleToString(rep.equity, 2) + IntegerToString(rep.open_count) +
                IntegerToString(perf.trades) + g_ai_reason + g_ex_last_msg +
                IntegerToString((int)blocked) + IntegerToString(strength);
   for(int si = 0; si < 10; si++)
      sig += (g_ex_sec[si] ? "1" : "0");
   if(sig == g_ex_sig)
     {
      ExPlaceHeaderButtons();
      if(!g_ex_fold) ExPlaceFooterButtons();
      return;
     }
   g_ex_sig = sig;

   int w = g_ex_w, h = g_ex_h;
   int pad = ExPx(12);
   int col2 = ExPx(108);
   int header_h = ExHeaderH();
   int footer_h = ExFooterH();
   int inner = w - pad * 2;

   g_ex.Erase(ExArgb(EX_NAVY, 255));
   ExRound(0, 0, w - 1, h - 1, ExPx(10), ExArgb(EX_PANEL, 245));
   g_ex.FillRectangle(0, 0, w - 1, ExPx(3), ExArgb(EX_GOLD));

   if(g_ex_fold)
     {
      ExFont("Segoe UI Bold", 13);
      g_ex.TextOut(pad + ExPx(18), ExPx(8), "Molido Expert  2.0", ExArgb(EX_TEXT), 0);
      ExFont("Segoe UI", 9);
      g_ex.TextOut(pad + ExPx(18), ExPx(28),
                   (blocked ? ExTr("real") : (linked ? ExTr("conn") : ExTr("disc"))) + "  " + clock,
                   ExArgb(blocked ? EX_CORAL : (linked ? EX_GREEN : EX_AMBER)), 0);
      g_ex.FillCircle(pad + ExPx(6), ExPx(16), ExPx(6), ExArgb(EX_GOLD));
      g_ex.Update();
      ExPlaceHeaderButtons();
      ChartRedraw(0);
      return;
     }

   if(g_ex_scroll > ExMaxScroll()) g_ex_scroll = ExMaxScroll();
   if(g_ex_scroll < 0) g_ex_scroll = 0;
   int y = header_h + ExPx(2) - g_ex_scroll;
   int x = pad;

   // B AI brain
   ExSecHead(y, x, inner, 1, ExTr("brain"));
   if(g_ex_sec[1])
     {
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(88), ExPx(8));
      color lc = linked ? EX_GREEN : EX_CORAL;
      ExLine(x, y + ExPx(6), "Mode", g_ai_mode, EX_BLUE, col2);
      ExLine(x, y + ExPx(22), ExTr("brain"), (linked ? ExTr("conn") : ExTr("disc")), lc, col2);
      ExLine(x, y + ExPx(38), ExTr("agents"),
             IntegerToString(linked ? g_ai_agents_on : 0) + " / " + IntegerToString(g_ai_agents_total),
             linked ? EX_GREEN : EX_MUTED, col2);
      ExFont("Segoe UI", 8);
      string extra = ExTr("council") + ": " + (StringLen(g_ai_council) > 0 && linked ? g_ai_council : ExTr("disc"));
      extra += "  " + ExTr("anal") + ": " + (StringLen(g_ai_analysis) > 0 && linked ? g_ai_analysis : "—");
      g_ex.TextOut(x, y + ExPx(56), extra, ExArgb(EX_MUTED), 0);
      string extra2 = ExTr("learn") + ": " + (StringLen(g_ai_learning) > 0 && linked ? g_ai_learning : "—");
      extra2 += "  " + ExTr("risk") + ": " + (StringLen(g_ai_risk) > 0 && linked ? g_ai_risk : "—");
      g_ex.TextOut(x, y + ExPx(70), extra2, ExArgb(EX_MUTED), 0);
      y += ExPx(96);
     }

   // C chart overlay (selector, no second chart)
   ExSecHead(y, x, inner, 2, ExTr("chart"));
   if(g_ex_sec[2])
     {
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(64), ExPx(8));
      ExLine(x, y + ExPx(4), "Symbol", _Symbol + "  " + EnumToString((ENUM_TIMEFRAMES)Period()), EX_GOLD, col2);
      ExPlaceTfButtons(x, y + ExPx(22));
      ExFont("Segoe UI", 8);
      g_ex.TextOut(x, y + ExPx(42), ExTr("strength") + "  " + IntegerToString(strength), ExArgb(EX_MUTED), 0);
      color mcol = (strength >= 70 ? EX_GREEN : strength >= 40 ? EX_AMBER : EX_CORAL);
      int mw = inner - col2;
      g_ex.FillRectangle(x + col2, y + ExPx(46), x + col2 + mw, y + ExPx(54), ExArgb(EX_CARD));
      int fw = (int)MathRound(mw * strength / 100.0);
      if(fw > 2)
         g_ex.FillRectangle(x + col2, y + ExPx(46), x + col2 + fw, y + ExPx(54), ExArgb(mcol));
      y += ExPx(72);
     }

   // D trade fields (buttons live in the sticky footer)
   ExSecHead(y, x, inner, 3, ExTr("trade"));
   if(g_ex_sec[3])
     {
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(70), ExPx(8));
      ExFont("Segoe UI", 8);
      g_ex.TextOut(x, y + ExPx(4), ExTr("lot"), ExArgb(EX_MUTED), 0);
      ExEdit("lot", DoubleToString(g_ex_lot, 2), g_ex_x + x + ExPx(48), g_ex_y + y + ExPx(2), ExPx(50), ExPx(16));
      g_ex.TextOut(x + ExPx(108), y + ExPx(4), "Risk%", ExArgb(EX_MUTED), 0);
      ExEdit("risk", DoubleToString(g_ex_risk_ui, 2), g_ex_x + x + ExPx(150), g_ex_y + y + ExPx(2), ExPx(44), ExPx(16));
      g_ex.TextOut(x + ExPx(204), y + ExPx(4), "Max", ExArgb(EX_MUTED), 0);
      ExEdit("maxp", IntegerToString(g_ex_max_pos), g_ex_x + x + ExPx(232), g_ex_y + y + ExPx(2), ExPx(36), ExPx(16));
      g_ex.TextOut(x, y + ExPx(24), "SL pts", ExArgb(EX_MUTED), 0);
      ExEdit("sl", DoubleToString(g_ex_sl_pts, 0), g_ex_x + x + ExPx(48), g_ex_y + y + ExPx(22), ExPx(50), ExPx(16));
      g_ex.TextOut(x + ExPx(108), y + ExPx(24), "TP pts", ExArgb(EX_MUTED), 0);
      ExEdit("tp", DoubleToString(g_ex_tp_pts, 0), g_ex_x + x + ExPx(150), g_ex_y + y + ExPx(22), ExPx(44), ExPx(16));
      ExFont("Segoe UI", 8);
      string feat = ExTr("smart") + (g_ex_smart_sl ? " ON" : " off");
      feat += "  " + ExTr("partial") + (UsePartialTP ? " ON" : " off");
      feat += "  " + ExTr("be") + (UseBreakEven ? " ON" : " off");
      g_ex.TextOut(x, y + ExPx(44), feat, ExArgb(EX_MUTED), 0);
      string feat2 = ExTr("trail") + (UseTrailing ? " ON" : " off");
      feat2 += "  " + ExTr("news") + " ON";
      feat2 += "  " + ExTr("rocket") + "  " + ExTr("impl_no");
      g_ex.TextOut(x, y + ExPx(56), feat2, ExArgb(EX_MUTED), 0);
      y += ExPx(78);
     }

   // E agent groups
   ExSecHead(y, x, inner, 4, ExTr("groups"));
   if(g_ex_sec[4])
     {
      int rows = 11;
      int bh = ExPx(14) * rows + ExPx(8);
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + bh, ExPx(8));
      for(int i = 0; i < 11; i++)
        {
         bool ok = (linked && StringFind(g_ai_group_st[i], "Disconnected") < 0 &&
                    StringFind(g_ai_group_st[i], "off") < 0);
         color gc = linked ? (ok ? EX_GREEN : EX_AMBER) : EX_CORAL;
         ExIconMark(x + ExPx(8), y + ExPx(10) + i * ExPx(14), gc);
         ExFont("Segoe UI", 8);
         g_ex.TextOut(x + ExPx(18), y + ExPx(4) + i * ExPx(14), g_ai_groups[i], ExArgb(EX_TEXT), 0);
         g_ex.TextOut(x + ExPx(150), y + ExPx(4) + i * ExPx(14),
                      linked ? g_ai_group_st[i] : ExTr("disc"), ExArgb(gc), 0);
        }
      y += bh + ExPx(8);
     }

   // F risk panel
   ExSecHead(y, x, inner, 5, ExTr("risk"));
   if(g_ex_sec[5])
     {
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(52), ExPx(8));
      ExLine(x, y + ExPx(6), "Profile", ExTr("balanced"), EX_GOLD, col2);
      ExLine(x, y + ExPx(22), "Cap",
             DoubleToString(DemoActiveRiskPct(), 2) + "%  max lots " + DoubleToString(DemoActiveMaxLotsCap(), 2) +
             "  pos " + IntegerToString(DemoActiveMaxPositions()), EX_TEXT, col2);
      ExFont("Segoe UI", 8);
      g_ex.TextOut(x, y + ExPx(38), "UI risk tightens only; hard caps stay local.", ExArgb(EX_MUTED), 0);
      y += ExPx(60);
     }

   // G performance
   ExSecHead(y, x, inner, 6, ExTr("perf"));
   if(g_ex_sec[6])
     {
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(70), ExPx(8));
      if(!perf.has_data)
        {
         ExFont("Segoe UI Semibold", 10);
         g_ex.TextOut(x, y + ExPx(20), ExTr("nodata"), ExArgb(EX_AMBER), 0);
        }
      else
        {
         ExLine(x, y + ExPx(4), "Trades", IntegerToString(perf.trades) + "   win " + DoubleToString(perf.winpct, 1) + "%", EX_TEXT, col2);
         ExLine(x, y + ExPx(20), "P/L", ExpertMoney(perf.pnl), perf.pnl >= 0 ? EX_GREEN : EX_CORAL, col2);
         ExLine(x, y + ExPx(36), "Avg W/L", ExpertMoney(perf.avg_win) + " / " + ExpertMoney(perf.avg_loss), EX_TEXT, col2);
         ExLine(x, y + ExPx(52), "Max DD", DoubleToString(perf.max_dd, 2) + "%", EX_AMBER, col2);
        }
      y += ExPx(78);
     }

   // H markets
   ExSecHead(y, x, inner, 7, ExTr("markets"));
   if(g_ex_sec[7])
     {
      string fx = "", gd = "", cr = "";
      int nfx = 0, ngd = 0, ncr = 0;
      int total = SymbolsTotal(true);
      for(int i = 0; i < total && (nfx + ngd + ncr) < 18; i++)
        {
         string s = SymbolName(i, true);
         if(StringLen(s) == 0) continue;
         string k = ExMarketKind(s);
         if(k == "gold" && ngd < 6) { gd += (ngd==0?"": ", ") + s; ngd++; }
         else if(k == "crypto" && ncr < 6) { cr += (ncr==0?"": ", ") + s; ncr++; }
         else if(k == "forex" && nfx < 8) { fx += (nfx==0?"": ", ") + s; nfx++; }
        }
      if(StringLen(fx) == 0) fx = ExTr("nodata");
      if(StringLen(gd) == 0) gd = ExTr("nodata");
      if(StringLen(cr) == 0) cr = ExTr("nodata");
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(56), ExPx(8));
      ExFont("Segoe UI", 8);
      g_ex.TextOut(x, y + ExPx(4), ExTr("forex") + ": " + fx, ExArgb(EX_TEXT), 0);
      g_ex.TextOut(x, y + ExPx(20), ExTr("gold") + ": " + gd, ExArgb(EX_GOLD), 0);
      g_ex.TextOut(x, y + ExPx(36), ExTr("crypto") + ": " + cr, ExArgb(EX_BLUE), 0);
      // clickable a few watch symbols
      string picks[3] = {"XAUUSD","EURUSD","GBPUSD"};
      for(int p = 0; p < 3; p++)
         ExBtn("sym" + picks[p], picks[p], g_ex_x + x + p * ExPx(64), g_ex_y + y + ExPx(48),
               ExPx(60), ExPx(16), (_Symbol == picks[p] ? EX_GOLD : EX_CARD),
               (_Symbol == picks[p] ? EX_NAVY : EX_TEXT));
      y += ExPx(72);
     }

   // I report
   ExSecHead(y, x, inner, 8, ExTr("report"));
   if(g_ex_sec[8])
     {
      ExGlass(x - ExPx(2), y, x + inner + ExPx(2), y + ExPx(88), ExPx(8));
      ExLine(x, y + ExPx(4), ExTr("today"), IntegerToString(rep.today_trades) + "  " + ExpertMoney(rep.today_pnl),
             rep.today_pnl >= 0 ? EX_GREEN : EX_CORAL, col2);
      ExLine(x, y + ExPx(20), ExTr("bal"), DoubleToString(rep.balance, 2), EX_TEXT, col2);
      ExLine(x, y + ExPx(36), ExTr("eq"), DoubleToString(rep.equity, 2), EX_TEXT, col2);
      ExLine(x, y + ExPx(52), ExTr("margin"), DoubleToString(rep.free_margin, 2), EX_TEXT, col2);
      ExLine(x, y + ExPx(68), ExTr("open") + "/" + ExTr("week") + "/" + ExTr("month"),
             IntegerToString(rep.open_count) + "   " + ExpertMoney(rep.week_pnl) + "   " + ExpertMoney(rep.month_pnl),
             EX_TEXT, col2);
      y += ExPx(96);
     }

   if(StringLen(g_ex_last_msg) > 0)
     {
      ExFont("Segoe UI", 8);
      g_ex.TextOut(x, y, g_ex_last_msg, ExArgb(EX_AMBER), 0);
      y += ExPx(16);
     }

   g_ex_content_h = y + g_ex_scroll - (header_h + ExPx(2));
   if(g_ex_content_h < 0) g_ex_content_h = 0;
   if(g_ex_scroll > ExMaxScroll()) g_ex_scroll = ExMaxScroll();

   // sticky header (A)
   g_ex.FillRectangle(0, 0, w - 1, header_h, ExArgb(EX_PANEL, 250));
   g_ex.FillRectangle(0, 0, w - 1, ExPx(3), ExArgb(EX_GOLD));
   g_ex.FillCircle(pad + ExPx(8), ExPx(22), ExPx(8), ExArgb(EX_GOLD));
   g_ex.FillCircle(pad + ExPx(8), ExPx(22), ExPx(4), ExArgb(EX_BLUE));
   ExFont("Segoe UI Bold", 13);
   g_ex.TextOut(pad + ExPx(22), ExPx(6), "Molido Expert  2.0", ExArgb(EX_TEXT), 0);
   ExFont("Segoe UI", 8);
   string st = (blocked ? ExTr("real") : (ea_on ? ExTr("active") : ExTr("off")));
   color stc = blocked ? EX_CORAL : (ea_on ? EX_GREEN : EX_AMBER);
   g_ex.TextOut(pad + ExPx(22), ExPx(26), "EA " + st, ExArgb(stc), 0);
   string br = ExTr("brain") + "  " + (linked ? ExTr("conn") : ExTr("disc"));
   g_ex.TextOut(pad + ExPx(22), ExPx(40), br + "   " + clock, ExArgb(linked ? EX_GREEN : EX_CORAL), 0);

   // sticky footer
   int fy = h - footer_h;
   g_ex.FillRectangle(0, fy, w - 1, h - 1, ExArgb(EX_PANEL, 250));
   g_ex.FillRectangle(ExPx(10), fy, w - ExPx(10), fy + 1, ExArgb(EX_LINE));

   g_ex.Update();
   ExPlaceHeaderButtons();
   ExPlaceFooterButtons();
   ExMarkSync();
   ChartRedraw(0);
   ExCapture();
  }

void MolidoDashOnChartEvent(const int id, const long &lparam,
                            const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_CHART_CHANGE)
     {
      g_ex_sig = "";
      MolidoDashRedraw();
      return;
     }
   if(id != CHARTEVENT_OBJECT_CLICK)
      return;
   if(StringFind(sparam, EX_BTN) != 0)
      return;
   string idb = StringSubstr(sparam, StringLen(EX_BTN));
   ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
   ExReadFields();

   if(idb == "fold")
     { g_ex_fold = !g_ex_fold; g_ex_sig = ""; ExDestroy(); MolidoDashRedraw(); return; }
   if(idb == "fa")
     { g_ui_lang = LANG_FA; g_i18n_fallback = false; MolidoI18nInit(); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "en")
     { g_ui_lang = LANG_EN; g_i18n_fallback = false; MolidoI18nInit(); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "up")
     { g_ex_scroll -= ExPx(64); if(g_ex_scroll < 0) g_ex_scroll = 0; g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "dn")
     { g_ex_scroll += ExPx(64); if(g_ex_scroll > ExMaxScroll()) g_ex_scroll = ExMaxScroll(); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(StringFind(idb, "sec") == 0)
     {
      int idx = (int)StringToInteger(StringSubstr(idb, 3));
      if(idx >= 0 && idx < 10)
         g_ex_sec[idx] = !g_ex_sec[idx];
      g_ex_sig = "";
      MolidoDashRedraw();
      return;
     }
   if(StringFind(idb, "tf") == 0)
     {
      string tf = StringSubstr(idb, 2);
      ENUM_TIMEFRAMES p = PERIOD_CURRENT;
      if(tf=="M1") p=PERIOD_M1; else if(tf=="M5") p=PERIOD_M5; else if(tf=="M15") p=PERIOD_M15;
      else if(tf=="M30") p=PERIOD_M30; else if(tf=="H1") p=PERIOD_H1; else if(tf=="H4") p=PERIOD_H4;
      else if(tf=="D1") p=PERIOD_D1; else if(tf=="W1") p=PERIOD_W1; else if(tf=="MN") p=PERIOD_MN1;
      if(p != PERIOD_CURRENT)
         ChartSetSymbolPeriod(0, _Symbol, p);
      g_ex_sig = "";
      return;
     }
   if(StringFind(idb, "sym") == 0)
     {
      string sym = StringSubstr(idb, 3);
      if(SymbolSelect(sym, true))
         ChartSetSymbolPeriod(0, sym, (ENUM_TIMEFRAMES)Period());
      g_ex_sig = "";
      return;
     }
   if(idb == "buy")  { ExpertManualTrade("buy");  g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "sell") { ExpertManualTrade("sell"); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "close"){ ExpertCloseChart();        g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "closeall"){ ExpertCloseAll();       g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "auto") { ExpertSetAuto(!ExpertAutoOn()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "stop") { ExpertSetStopNew(!ExpertStopNew()); g_ex_sig = ""; MolidoDashRedraw(); return; }
  }

#endif

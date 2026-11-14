//+------------------------------------------------------------------+
//| MolidoExpertUI.mqh - Molido Expert – AI Trading Power dashboard  |
//| Native CCanvas / objects only. Does not cover the full chart.    |
//| Strict grid: aligned columns, uniform cards, no overlapping text.|
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
#define EX_KILLBG C'132,28,42'
#define EX_BUYBG  C'16,90,70'
#define EX_SELLBG C'90,32,40'
#define EX_AUTOON C'16,80,96'
#define EX_STOPON C'96,32,40'
#define EX_STRON  C'14,86,78'

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
   if(key == "status")  return(L==LANG_FA ? "وضعیت" : L==LANG_AR ? "الحالة" : L==LANG_TR ? "Durum" : "Status");
   if(key == "disc")    return(L==LANG_FA ? "قطع ارتباط" : L==LANG_AR ? "غير متصل" : L==LANG_TR ? "Bağlı değil" : "Disconnected");
   if(key == "conn")    return(L==LANG_FA ? "متصل" : L==LANG_AR ? "متصل" : L==LANG_TR ? "Bağlı" : "Connected");
   if(key == "agents")  return(L==LANG_FA ? "عامل‌ها" : L==LANG_AR ? "الوكلاء" : L==LANG_TR ? "Ajanlar" : "Agents");
   if(key == "council") return(L==LANG_FA ? "شورا" : L==LANG_AR ? "المجلس" : L==LANG_TR ? "Konsey" : "Council");
   if(key == "anal")    return(L==LANG_FA ? "تحلیل" : L==LANG_AR ? "تحليل" : L==LANG_TR ? "Analiz" : "Analysis");
   if(key == "learn")   return(L==LANG_FA ? "یادگیری" : L==LANG_AR ? "التعلم" : L==LANG_TR ? "Öğrenme" : "Learning");
   if(key == "risk")    return(L==LANG_FA ? "ریسک" : L==LANG_AR ? "المخاطر" : L==LANG_TR ? "Risk" : "Risk");
   if(key == "hybrid")  return("HYBRID");
   if(key == "chart")   return(L==LANG_FA ? "نمودار" : L==LANG_AR ? "الرسم" : L==LANG_TR ? "Grafik" : "Chart");
   if(key == "trade")   return(L==LANG_FA ? "کنترل معامله" : L==LANG_AR ? "التحكم بالصفقة" : L==LANG_TR ? "İşlem kontrol" : "Trade Control");
   if(key == "buy")     return(L==LANG_FA ? "خرید" : L==LANG_AR ? "شراء" : L==LANG_TR ? "AL" : "BUY");
   if(key == "sell")    return(L==LANG_FA ? "فروش" : L==LANG_AR ? "بيع" : L==LANG_TR ? "SAT" : "SELL");
   if(key == "close")   return(L==LANG_FA ? "بستن موقعیت" : L==LANG_AR ? "إغلاق الصفقة" : L==LANG_TR ? "Pozisyonu kapat" : "CLOSE POSITION");
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
   if(key == "safety")  return(L==LANG_FA ? "ایمنی" : L==LANG_AR ? "أمان" : L==LANG_TR ? "Güvenlik" : "Safety");
   if(key == "max")     return("Max");
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
   return(v < 9 ? 9 : v);
  }

void ExFont(const string face, const int base)
  {
   int sz = ExFontSz(base);
   string ui = MolidoUiFont(StringFind(face, "Bold") >= 0 || StringFind(face, "Semibold") >= 0);
   if(!g_ex.FontSet(ui, sz))
      if(!g_ex.FontSet(face, sz))
         g_ex.FontSet("Tahoma", sz);
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
   ExRound(x1, y1, x2, y2, r, ExArgb(EX_GLASS, 230));
   g_ex.FillRectangle(x1 + r, y1, x2 - r, y1 + 1, ExArgb(EX_GOLD, 70));
  }

void ExIconMark(const int x, const int y, const color c)
  {
   g_ex.FillCircle(x, y, ExPx(4), ExArgb(c, 220));
   g_ex.FillCircle(x, y, ExPx(2), ExArgb(c));
  }

int ExPanelW()
  {
   int cw = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int leave = 280;
   int cap = cw - leave;
   if(cap > 460) cap = 460;
   if(cap < 360)
     {
      if(cw - 200 >= 340)
         cap = cw - 200;
      else
         cap = (cw - 160 > 280 ? cw - 160 : 280);
     }
   if(cw > 0 && cap > cw - 80)
      cap = cw - 80;
   if(cap < 280) cap = 280;
   return(cap);
  }

int ExHeaderH() { return(ExPx(g_ex_fold ? 52 : 72)); }
int ExFooterH() { return(g_ex_fold ? 0 : ExPx(52)); }
int ExGap()     { return(ExPx(8)); }
int ExBtnH()    { return(ExPx(24)); }
int ExRowH()    { return(ExPx(20)); }

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
   if(body < ExPx(160)) body = ExPx(760);
   int need = ExHeaderH() + body + ExFooterH();
   return(need < avail ? need : avail);
  }

int ExMaxScroll()
  {
   int room = ExPanelH() - ExHeaderH() - ExFooterH();
   int mx = g_ex_content_h - room;
   return(mx < 0 ? 0 : mx);
  }

int ExEqualW(const int inner, const int n, const int gap)
  {
   if(n <= 0) return(inner);
   int w = (inner - (n - 1) * gap) / n;
   int mn = ExPx(36);
   return(w < mn ? mn : w);
  }

int ExLabelCol(const int inner)
  {
   int lw = (int)MathRound(inner * 0.42);
   if(lw < ExPx(110)) lw = ExPx(110);
   if(lw > ExPx(160)) lw = ExPx(160);
   return(lw);
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

void ExHide(const string id)
  {
   string name = EX_BTN + id;
   if(ObjectFind(0, name) >= 0)
      ObjectDelete(0, name);
  }

bool ExInBody(const int abs_y, const int bh)
  {
   int top = g_ex_y + ExHeaderH() + 1;
   int bot = g_ex_y + g_ex_h - ExFooterH() - 1;
   return(abs_y >= top && (abs_y + bh) <= bot);
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

void ExBtnBody(const string id, const string cap, const int x, const int y,
               const int w, const int h, const color bg, const color fg)
  {
   if(!ExInBody(y, h))
     {
      ExHide(id);
      return;
     }
   ExBtn(id, cap, x, y, w, h, bg, fg);
  }

void ExEdit(const string id, const string val, const int x, const int y,
            const int w, const int h)
  {
   if(!ExInBody(y, h))
     {
      ExHide(id);
      return;
     }
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

void ExKV(const int x, const int y, const int inner, const string label, const string value, const color vc)
  {
   int lw = ExLabelCol(inner);
   ExFont("Segoe UI", 9);
   g_ex.TextOut(x, y, label, ExArgb(EX_MUTED), 0);
   ExFont("Segoe UI Semibold", 10);
   g_ex.TextOut(x + lw, y, value, ExArgb(vc), 0);
  }

int ExSecHead(int &y, const int x, const int w, const int idx, const string title)
  {
   y += ExPx(6);
   ExFont("Segoe UI Semibold", 10);
   g_ex.TextOut(x, y, title, ExArgb(EX_BLUE), 0);
   int tw = g_ex.TextWidth(title);
   int ly = y + ExPx(10);
   int x1 = x + tw + ExPx(8);
   int x2 = x + w - ExPx(24);
   if(x2 > x1)
      g_ex.FillRectangle(x1, ly, x2, ly + 1, ExArgb(EX_LINE));
   ExBtnBody("sec" + IntegerToString(idx), (g_ex_sec[idx] ? "-" : "+"),
             g_ex_x + x + w - ExPx(20), g_ex_y + y, ExPx(18), ExPx(16), EX_CARD, EX_MUTED);
   y += ExPx(20);
   return(y);
  }

void ExPlaceHeaderButtons()
  {
   int x = g_ex_x, y = g_ex_y;
   int w = g_ex_w;
   int lang = MolidoLangId();
   int bw = ExPx(28), bh = ExPx(20), gap = ExPx(4);
   int top = y + ExPx(8);
   int rx = x + w - ExPx(12);
   ExBtn("fold", (g_ex_fold ? "+" : "-"), rx - ExPx(18), top, ExPx(18), bh, EX_CARD, EX_TEXT);
   bool en_on = (lang != LANG_FA && lang != LANG_AR && lang != LANG_TR);
   ExBtn("en", "EN", rx - ExPx(18) - gap - bw, top, bw, bh,
         (en_on ? EX_GOLD : EX_CARD), (en_on ? EX_NAVY : EX_TEXT));
   ExBtn("fa", "FA", rx - ExPx(18) - 2 * (gap + bw), top, bw, bh,
         (lang == LANG_FA ? EX_GOLD : EX_CARD), (lang == LANG_FA ? EX_NAVY : EX_TEXT));
  }

void ExPlaceFooterButtons()
  {
   if(g_ex_fold)
     {
      string also[] = {"auto","stop","kill","up","dn"};
      for(int j = 0; j < ArraySize(also); j++)
         ExHide(also[j]);
      return;
     }
   int pad = ExPx(12);
   int gap = ExGap();
   int bh = ExBtnH();
   int reserve = ExPx(24);
   int y = g_ex_y + g_ex_h - ExFooterH();
   int x = g_ex_x + pad;
   int inner = g_ex_w - pad * 2 - reserve;
   int bw = ExEqualW(inner, 3, gap);
   int by = y + (ExFooterH() - bh) / 2;
   bool auto_on = ExpertAutoOn();
   bool stop = ExpertStopNew();
   bool killed = DemoKillEngaged();
   ExBtn("auto", ExTr("auto") + " " + (auto_on ? ExTr("on") : ExTr("off")),
         x, by, bw, bh, auto_on ? EX_AUTOON : EX_CARD, auto_on ? EX_BLUE : EX_MUTED);
   ExBtn("stop", ExTr("stopnew"),
         x + bw + gap, by, bw, bh, stop ? EX_STOPON : EX_CARD, stop ? EX_CORAL : EX_TEXT);
   color kbg = killed ? C'160,36,48' : EX_KILLBG;
   color kfg = killed ? C'255,230,230' : C'255,186,186';
   ExBtn("kill", (killed ? Tr("kill_on") : Tr("kill")),
         x + 2 * (bw + gap), by, bw, bh, kbg, kfg);
   if(ExMaxScroll() > 0)
     {
      int sx = g_ex_x + g_ex_w - ExPx(22);
      ExBtn("up", "^", sx, y + ExPx(6), ExPx(16), ExPx(16), EX_CARD, EX_BLUE);
      ExBtn("dn", "v", sx, y + ExPx(26), ExPx(16), ExPx(16), EX_CARD, EX_BLUE);
     }
   else
     {
      ExHide("up");
      ExHide("dn");
     }
  }

void ExPlaceTfButtons(const int x, const int y, const int inner)
  {
   string labs[9] = {"M1","M5","M15","M30","H1","H4","D1","W1","MN"};
   ENUM_TIMEFRAMES tfs[9] = {PERIOD_M1,PERIOD_M5,PERIOD_M15,PERIOD_M30,PERIOD_H1,PERIOD_H4,PERIOD_D1,PERIOD_W1,PERIOD_MN1};
   ENUM_TIMEFRAMES cur = (ENUM_TIMEFRAMES)Period();
   int cols = 5;
   int gap = ExPx(6);
   int bw = ExEqualW(inner, cols, gap);
   int bh = ExPx(20);
   for(int i = 0; i < 9; i++)
     {
      int row = i / cols;
      int col = i % cols;
      bool on = (cur == tfs[i]);
      ExBtnBody("tf" + labs[i], labs[i],
                g_ex_x + x + col * (bw + gap), g_ex_y + y + row * (bh + gap),
                bw, bh, on ? EX_BLUE : EX_CARD, on ? EX_NAVY : EX_TEXT);
     }
  }

void ExField(const int x, const int y, const int cell_w, const string label,
             const string id, const string val, const int ew)
  {
   ExFont("Segoe UI", 9);
   g_ex.TextOut(x, y + ExPx(2), label, ExArgb(EX_MUTED), 0);
   int lw = ExPx(52);
   ExFont("Segoe UI", 9);
   int tw = g_ex.TextWidth(label);
   if(tw + ExPx(6) > lw) lw = tw + ExPx(6);
   if(lw > cell_w - ew - ExPx(4)) lw = cell_w - ew - ExPx(4);
   ExEdit(id, val, g_ex_x + x + lw, g_ex_y + y, ew, ExPx(18));
  }

void ExMarkSync()
  {
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

void MolidoDashRedraw();

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

void ExPeriodName(string &out)
  {
   ENUM_TIMEFRAMES p = (ENUM_TIMEFRAMES)Period();
   if(p==PERIOD_M1) out="M1";
   else if(p==PERIOD_M5) out="M5";
   else if(p==PERIOD_M15) out="M15";
   else if(p==PERIOD_M30) out="M30";
   else if(p==PERIOD_H1) out="H1";
   else if(p==PERIOD_H4) out="H4";
   else if(p==PERIOD_D1) out="D1";
   else if(p==PERIOD_W1) out="W1";
   else if(p==PERIOD_MN1) out="MN";
   else out=IntegerToString(Period());
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
   string tfname = "";
   ExPeriodName(tfname);

   string sig = MOLIDO_EA_VERSION + IntegerToString((int)MolidoLangId()) +
                IntegerToString((int)linked) + IntegerToString(g_ai_agents_on) +
                IntegerToString((int)ea_on) + clock + _Symbol + IntegerToString(Period()) +
                IntegerToString((int)g_ex_fold) + IntegerToString(g_ex_scroll) +
                IntegerToString(ExPanelH()) + IntegerToString((int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS)) +
                IntegerToString((int)ExpertAutoOn()) + IntegerToString((int)ExpertStopNew()) +
                IntegerToString((int)DemoKillEngaged()) +
                IntegerToString((int)StratUseScalper()) + IntegerToString((int)StratUseNews()) +
                IntegerToString((int)StratUseTrend()) + IntegerToString((int)StratUseAuto()) +
                IntegerToString((int)StratUseFibo()) +
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
   int gap = ExGap();
   int header_h = ExHeaderH();
   int footer_h = ExFooterH();
   int inner = w - pad * 2;
   int rh = ExRowH();

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
      ExPlaceFooterButtons();
      ChartRedraw(0);
      return;
     }

   if(g_ex_scroll > ExMaxScroll()) g_ex_scroll = ExMaxScroll();
   if(g_ex_scroll < 0) g_ex_scroll = 0;
   int y = header_h + ExPx(4) - g_ex_scroll;
   int x = pad;

   // B AI brain — one pair per row
   ExSecHead(y, x, inner, 1, ExTr("brain"));
   if(g_ex_sec[1])
     {
      int rows = 7;
      int ch = ExPx(10) + rows * rh;
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      color lc = linked ? EX_GREEN : EX_CORAL;
      int yy = y + ExPx(6);
      ExKV(x + ExPx(8), yy, inner - ExPx(16), "Mode", g_ai_mode, EX_BLUE); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("status"), (linked ? ExTr("conn") : ExTr("disc")), lc); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("agents"),
           IntegerToString(linked ? g_ai_agents_on : 0) + " / " + IntegerToString(g_ai_agents_total),
           linked ? EX_GREEN : EX_MUTED); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("council"),
           (linked && StringLen(g_ai_council) > 0 ? g_ai_council : ExTr("disc")),
           linked ? EX_TEXT : EX_MUTED); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("anal"),
           (linked && StringLen(g_ai_analysis) > 0 ? g_ai_analysis : "—"), EX_TEXT); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("learn"),
           (linked && StringLen(g_ai_learning) > 0 ? g_ai_learning : "—"), EX_TEXT); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("risk"),
           (linked && StringLen(g_ai_risk) > 0 ? g_ai_risk : "—"), EX_TEXT);
      y += ch + ExPx(6);
     }

   // C chart overlay
   ExSecHead(y, x, inner, 2, ExTr("chart"));
   if(g_ex_sec[2])
     {
      int ch = ExPx(10) + rh + 2 * (ExPx(20) + ExPx(6)) + rh + ExPx(12);
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      ExKV(x + ExPx(8), y + ExPx(6), inner - ExPx(16), "Symbol", _Symbol + "  " + tfname, EX_GOLD);
      ExPlaceTfButtons(x + ExPx(8), y + ExPx(6) + rh, inner - ExPx(16));
      int bar_y = y + ExPx(6) + rh + 2 * (ExPx(20) + ExPx(6)) + ExPx(2);
      ExFont("Segoe UI", 9);
      g_ex.TextOut(x + ExPx(8), bar_y, ExTr("strength"), ExArgb(EX_MUTED), 0);
      int lw = ExLabelCol(inner - ExPx(16));
      color mcol = (strength >= 70 ? EX_GREEN : strength >= 40 ? EX_AMBER : EX_CORAL);
      int bx1 = x + ExPx(8) + lw;
      int bx2 = x + inner - ExPx(40);
      int by1 = bar_y + ExPx(4);
      int by2 = by1 + ExPx(8);
      if(bx2 > bx1 + 8)
        {
         g_ex.FillRectangle(bx1, by1, bx2, by2, ExArgb(EX_CARD));
         int fw = (int)MathRound((bx2 - bx1) * strength / 100.0);
         if(fw > 2)
            g_ex.FillRectangle(bx1, by1, bx1 + fw, by2, ExArgb(mcol));
        }
      ExFont("Segoe UI Semibold", 9);
      g_ex.TextOut(x + inner - ExPx(36), bar_y, IntegerToString(strength), ExArgb(mcol), 0);
      y += ch + ExPx(6);
     }

   // D Trade Control — fields, strategy row, then trade buttons at the card bottom
   ExSecHead(y, x, inner, 3, ExTr("trade"));
   if(g_ex_sec[3])
     {
      int cell = (inner - ExPx(16) - gap) / 2;
      int ew = ExPx(56);
      int field_h = 3 * ExPx(22);
      int feat_h = ExPx(32);
      int strat_h = ExBtnH() + ExPx(4);
      int trade_h = ExBtnH() + ExPx(8);
      int ch = ExPx(8) + field_h + feat_h + strat_h + trade_h + ExPx(6);
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      int fy = y + ExPx(8);
      int fx = x + ExPx(8);
      ExField(fx, fy, cell, ExTr("lot"), "lot", DoubleToString(g_ex_lot, 2), ew);
      ExField(fx + cell + gap, fy, cell, "Risk%", "risk", DoubleToString(g_ex_risk_ui, 2), ew);
      fy += ExPx(22);
      ExField(fx, fy, cell, "SL pts", "sl", DoubleToString(g_ex_sl_pts, 0), ew);
      ExField(fx + cell + gap, fy, cell, "TP pts", "tp", DoubleToString(g_ex_tp_pts, 0), ew);
      fy += ExPx(22);
      ExField(fx, fy, cell, ExTr("max"), "maxp", IntegerToString(g_ex_max_pos), ew);
      fy += ExPx(22);
      // feature status — two lines, not mixed with buttons
      ExFont("Segoe UI", 8);
      string feat = ExTr("smart") + (g_ex_smart_sl ? " ON" : " off");
      feat += "   " + ExTr("partial") + (UsePartialTP ? " ON" : " off");
      g_ex.TextOut(fx, fy, feat, ExArgb(EX_MUTED), 0);
      fy += ExPx(14);
      string feat2 = ExTr("be") + (UseBreakEven ? " ON" : " off");
      feat2 += "   " + ExTr("trail") + (UseTrailing ? " ON" : " off");
      feat2 += "   " + ExTr("rocket") + " " + ExTr("impl_no");
      g_ex.TextOut(fx, fy, feat2, ExArgb(EX_MUTED), 0);
      fy += ExPx(18);
      // strategy toggles — own equal row
      int sw = ExEqualW(inner - ExPx(16), 4, gap);
      int sh = ExBtnH();
      bool sc = StratUseScalper(), nx = StratUseNews(), trn = StratUseTrend(), au = StratUseAuto();
      ExBtnBody("sc", "SC " + (sc ? ExTr("on") : ExTr("off")),
                g_ex_x + fx, g_ex_y + fy, sw, sh, sc ? EX_STRON : EX_CARD, sc ? EX_GREEN : EX_MUTED);
      ExBtnBody("nx", "NX " + (nx ? ExTr("on") : ExTr("off")),
                g_ex_x + fx + (sw + gap), g_ex_y + fy, sw, sh, nx ? EX_STRON : EX_CARD, nx ? EX_GREEN : EX_MUTED);
      ExBtnBody("tr", "TR " + (trn ? ExTr("on") : ExTr("off")),
                g_ex_x + fx + 2 * (sw + gap), g_ex_y + fy, sw, sh, trn ? EX_STRON : EX_CARD, trn ? EX_GREEN : EX_MUTED);
      ExBtnBody("au", "AU " + (au ? ExTr("on") : ExTr("off")),
                g_ex_x + fx + 3 * (sw + gap), g_ex_y + fy, sw, sh, au ? EX_STRON : EX_CARD, au ? EX_GREEN : EX_MUTED);
      fy += sh + ExPx(8);
      // trade buttons — one row at the bottom of this card; KILL is not here
      int tw = ExEqualW(inner - ExPx(16), 4, gap);
      int th = ExBtnH();
      ExBtnBody("buy", ExTr("buy"), g_ex_x + fx, g_ex_y + fy, tw, th, EX_BUYBG, EX_GREEN);
      ExBtnBody("sell", ExTr("sell"), g_ex_x + fx + (tw + gap), g_ex_y + fy, tw, th, EX_SELLBG, EX_CORAL);
      ExBtnBody("close", ExTr("close"), g_ex_x + fx + 2 * (tw + gap), g_ex_y + fy, tw, th, EX_CARD, EX_TEXT);
      ExBtnBody("closeall", ExTr("closeall"), g_ex_x + fx + 3 * (tw + gap), g_ex_y + fy, tw, th, EX_CARD, EX_MUTED);
      y += ch + ExPx(6);
     }
   else
     {
      ExHide("lot"); ExHide("risk"); ExHide("sl"); ExHide("tp"); ExHide("maxp");
      ExHide("sc"); ExHide("nx"); ExHide("tr"); ExHide("au");
      ExHide("buy"); ExHide("sell"); ExHide("close"); ExHide("closeall");
     }

   // E agent groups
   ExSecHead(y, x, inner, 4, ExTr("groups"));
   if(g_ex_sec[4])
     {
      int row = ExPx(18);
      int ch = ExPx(8) + 11 * row + ExPx(4);
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      int stcol = ExLabelCol(inner - ExPx(16));
      if(stcol < ExPx(150)) stcol = (inner > ExPx(220) ? ExPx(150) : stcol);
      for(int i = 0; i < 11; i++)
        {
         bool ok = (linked && StringFind(g_ai_group_st[i], "Disconnected") < 0 &&
                    StringFind(g_ai_group_st[i], "off") < 0);
         color gc = linked ? (ok ? EX_GREEN : EX_AMBER) : EX_CORAL;
         int ry = y + ExPx(8) + i * row;
         ExIconMark(x + ExPx(12), ry + ExPx(7), gc);
         ExFont("Segoe UI", 9);
         g_ex.TextOut(x + ExPx(22), ry, g_ai_groups[i], ExArgb(EX_TEXT), 0);
         ExFont("Segoe UI Semibold", 9);
         g_ex.TextOut(x + ExPx(8) + stcol, ry, linked ? g_ai_group_st[i] : ExTr("disc"), ExArgb(gc), 0);
        }
      y += ch + ExPx(6);
     }

   // F risk
   ExSecHead(y, x, inner, 5, ExTr("risk"));
   if(g_ex_sec[5])
     {
      int ch = ExPx(10) + 3 * rh;
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      int yy = y + ExPx(6);
      ExKV(x + ExPx(8), yy, inner - ExPx(16), "Profile", ExTr("balanced"), EX_GOLD); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), "Cap",
           DoubleToString(DemoActiveRiskPct(), 2) + "%   lots " + DoubleToString(DemoActiveMaxLotsCap(), 2),
           EX_TEXT); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), "Max pos",
           IntegerToString(DemoActiveMaxPositions()), EX_TEXT);
      y += ch + ExPx(6);
     }

   // G performance
   ExSecHead(y, x, inner, 6, ExTr("perf"));
   if(g_ex_sec[6])
     {
      int ch = ExPx(10) + (perf.has_data ? 4 * rh : 2 * rh);
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      if(!perf.has_data)
        {
         ExFont("Segoe UI Semibold", 10);
         g_ex.TextOut(x + ExPx(8), y + ExPx(14), ExTr("nodata"), ExArgb(EX_AMBER), 0);
        }
      else
        {
         int yy = y + ExPx(6);
         ExKV(x + ExPx(8), yy, inner - ExPx(16), "Trades",
              IntegerToString(perf.trades) + "   win " + DoubleToString(perf.winpct, 1) + "%", EX_TEXT); yy += rh;
         ExKV(x + ExPx(8), yy, inner - ExPx(16), "P/L", ExpertMoney(perf.pnl),
              perf.pnl >= 0 ? EX_GREEN : EX_CORAL); yy += rh;
         ExKV(x + ExPx(8), yy, inner - ExPx(16), "Avg W/L",
              ExpertMoney(perf.avg_win) + " / " + ExpertMoney(perf.avg_loss), EX_TEXT); yy += rh;
         ExKV(x + ExPx(8), yy, inner - ExPx(16), "Max DD", DoubleToString(perf.max_dd, 2) + "%", EX_AMBER);
        }
      y += ch + ExPx(6);
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
      int ch = ExPx(10) + 3 * rh + ExBtnH() + ExPx(10);
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      int yy = y + ExPx(6);
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("forex"), fx, EX_TEXT); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("gold"), gd, EX_GOLD); yy += rh;
      ExKV(x + ExPx(8), yy, inner - ExPx(16), ExTr("crypto"), cr, EX_BLUE); yy += rh;
      string picks[3] = {"XAUUSD","EURUSD","GBPUSD"};
      int pw = ExEqualW(inner - ExPx(16), 3, gap);
      int ph = ExBtnH();
      for(int p = 0; p < 3; p++)
         ExBtnBody("sym" + picks[p], picks[p],
                   g_ex_x + x + ExPx(8) + p * (pw + gap), g_ex_y + yy,
                   pw, ph, (_Symbol == picks[p] ? EX_GOLD : EX_CARD),
                   (_Symbol == picks[p] ? EX_NAVY : EX_TEXT));
      y += ch + ExPx(6);
     }
   else
     {
      ExHide("symXAUUSD"); ExHide("symEURUSD"); ExHide("symGBPUSD");
     }

   // I report — one metric per row
   ExSecHead(y, x, inner, 8, ExTr("report"));
   if(g_ex_sec[8])
     {
      int ch = ExPx(10) + 7 * rh;
      ExGlass(x, y, x + inner, y + ch, ExPx(8));
      int yy = y + ExPx(6);
      int ix = x + ExPx(8);
      int iw = inner - ExPx(16);
      ExKV(ix, yy, iw, ExTr("today"), IntegerToString(rep.today_trades) + "  " + ExpertMoney(rep.today_pnl),
           rep.today_pnl >= 0 ? EX_GREEN : EX_CORAL); yy += rh;
      ExKV(ix, yy, iw, ExTr("week"), ExpertMoney(rep.week_pnl),
           rep.week_pnl >= 0 ? EX_GREEN : EX_CORAL); yy += rh;
      ExKV(ix, yy, iw, ExTr("month"), ExpertMoney(rep.month_pnl),
           rep.month_pnl >= 0 ? EX_GREEN : EX_CORAL); yy += rh;
      ExKV(ix, yy, iw, ExTr("bal"), DoubleToString(rep.balance, 2), EX_TEXT); yy += rh;
      ExKV(ix, yy, iw, ExTr("eq"), DoubleToString(rep.equity, 2), EX_TEXT); yy += rh;
      ExKV(ix, yy, iw, ExTr("margin"), DoubleToString(rep.free_margin, 2), EX_TEXT); yy += rh;
      ExKV(ix, yy, iw, ExTr("open"), IntegerToString(rep.open_count), EX_TEXT);
      y += ch + ExPx(6);
     }

   if(StringLen(g_ex_last_msg) > 0)
     {
      ExFont("Segoe UI", 9);
      g_ex.TextOut(x, y, g_ex_last_msg, ExArgb(EX_AMBER), 0);
      y += ExPx(18);
     }

   g_ex_content_h = y + g_ex_scroll - (header_h + ExPx(4));
   if(g_ex_content_h < 0) g_ex_content_h = 0;
   if(g_ex_scroll > ExMaxScroll()) g_ex_scroll = ExMaxScroll();

   // sticky header (A)
   g_ex.FillRectangle(0, 0, w - 1, header_h, ExArgb(EX_PANEL, 252));
   g_ex.FillRectangle(0, 0, w - 1, ExPx(3), ExArgb(EX_GOLD));
   g_ex.FillRectangle(0, header_h - 1, w - 1, header_h, ExArgb(EX_LINE));
   g_ex.FillCircle(pad + ExPx(10), ExPx(22), ExPx(8), ExArgb(EX_GOLD));
   g_ex.FillCircle(pad + ExPx(10), ExPx(22), ExPx(4), ExArgb(EX_BLUE));
   ExFont("Segoe UI Bold", 13);
   g_ex.TextOut(pad + ExPx(24), ExPx(8), "Molido Expert  2.0", ExArgb(EX_TEXT), 0);
   // status pills on the second header row — short labels, clock on the right
   int py = ExPx(40);
   string st = (blocked ? ExTr("real") : (ea_on ? "EA  " + ExTr("active") : "EA  " + ExTr("off")));
   color stc = blocked ? EX_CORAL : (ea_on ? EX_GREEN : EX_AMBER);
   ExFont("Segoe UI Semibold", 9);
   int tws = g_ex.TextWidth(st);
   ExRound(pad + ExPx(24), py - ExPx(2), pad + ExPx(24) + tws + ExPx(10), py + ExPx(16), ExPx(6), ExArgb(stc, 40));
   g_ex.TextOut(pad + ExPx(28), py, st, ExArgb(stc), 0);
   string br = linked ? ExTr("conn") : ExTr("disc");
   color brc = linked ? EX_GREEN : EX_CORAL;
   int bx = pad + ExPx(24) + tws + ExPx(18);
   ExFont("Segoe UI Semibold", 9);
   int tb = g_ex.TextWidth(br);
   ExRound(bx, py - ExPx(2), bx + tb + ExPx(10), py + ExPx(16), ExPx(6), ExArgb(brc, 40));
   g_ex.TextOut(bx + ExPx(4), py, br, ExArgb(brc), 0);
   ExFont("Segoe UI", 9);
   int cw = g_ex.TextWidth(clock);
   g_ex.TextOut(w - ExPx(16) - cw, py, clock, ExArgb(EX_MUTED), 0);

   // sticky footer — safety row only (Auto, Stop new, KILL)
   int fy2 = h - footer_h;
   g_ex.FillRectangle(0, fy2, w - 1, h - 1, ExArgb(EX_PANEL, 252));
   g_ex.FillRectangle(ExPx(10), fy2, w - ExPx(10), fy2 + 1, ExArgb(EX_LINE));

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
   if(idb == "sc") { StratSet("scalper", !StratUseScalper()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "nx") { StratSet("news", !StratUseNews()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "tr") { StratSet("trend", !StratUseTrend()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "au") { StratSet("auto", !StratUseAuto()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "kill")
     {
      if(DemoKillEngaged())
         DemoKillSet(false);
      else
         DemoKillSet(true);
      g_ex_sig = "";
      MolidoDashRedraw();
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

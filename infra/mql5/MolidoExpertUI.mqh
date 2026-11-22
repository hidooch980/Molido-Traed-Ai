//+------------------------------------------------------------------+
//| MolidoExpertUI.mqh - Molido Expert 2.30 dashboard                |
//| Default: compact corner panel (DashboardUiSize / DashboardScale).|
//| Full-frame layout remains available. Collapse state is remembered.|
//| Numbers are live terminal/bridge data only.                      |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_UI_MQH
#define MOLIDO_EXPERT_UI_MQH

#include <Canvas/Canvas.mqh>
#resource "Images\molido_avatar.bmp"

#define EX_H    "MolidoEx_H"
#define EX_L    "MolidoEx_L"
#define EX_R    "MolidoEx_R"
#define EX_M    "MolidoEx_M"
#define EX_B    "MolidoEx_B"
#define EX_T    "MolidoEx_T"
#define EX_TAG  "MolidoEx_Tag"
#define EX_HUD  "MolidoEx_Hud"
#define EX_LIVE "MolidoEx_Live"
#define EX_BTN  "ExDash_"
#define EX_MARK "ExMark_"

#define EX_BLACK  C'3,6,14'
#define EX_NAVY   C'6,12,28'
#define EX_NAVY2  C'10,20,42'
#define EX_GLASS  C'12,22,48'
#define EX_CARD   C'14,26,54'
#define EX_GOLD   C'220,180,70'
#define EX_GOLD2  C'255,214,110'
#define EX_BLUE   C'40,190,255'
#define EX_BLUE2  C'20,120,220'
#define EX_GREEN  C'40,230,150'
#define EX_GREEN2 C'10,140,90'
#define EX_AMBER  C'245,186,74'
#define EX_CORAL  C'255,80,90'
#define EX_RED    C'180,20,40'
#define EX_TEXT   C'230,238,248'
#define EX_MUTED  C'130,150,180'
#define EX_LINE   C'30,70,120'
#define CX_LBL    C'178,198,224'
#define CX_BD     C'60,120,180'

CCanvas g_cv_h, g_cv_l, g_cv_r, g_cv_m, g_cv_b, g_cv_t, g_cv_tag, g_cv_hud;
CCanvas *g_dc = NULL;
bool    g_ex_ready = false;
int     g_ex_cw = 0, g_ex_ch = 0;
int     g_ly_head, g_ly_tab, g_ly_mid, g_ly_bot, g_ly_left, g_ly_right;
int     g_ly_hx, g_ly_hy, g_ly_hw, g_ly_hh;
uint    g_ex_last_ms = 0;
string  g_ex_sig = "";
int     g_ex_tab = 0;
string  g_hover = "";
string  g_pressed = "";
double  g_gauge_shown = 0;
datetime g_ex_updated = 0;
int     g_pulse_sec = 0;
int     g_ox = 0, g_oy = 0;
bool    g_ex_host_saved = false;
color   g_host_bg, g_host_fg, g_host_grid, g_host_up, g_host_dn, g_host_bull, g_host_bear;
bool    g_host_show_grid, g_host_show_date, g_host_show_price;
int     g_ex_chart_w = 0, g_ex_chart_h = 0;
int     g_ex_px = 0, g_ex_py = 0;
bool    g_ex_collapsed = false;
bool    g_ex_collapse_loaded = false;
#define EX_COLLAPSE_GV "Molido.Expert.DashCollapsed"
//--- compact grid state (single opaque canvas, strict 6-column grid)
double  g_cs = 0.80;
int     g_cx_pad = 8, g_cx_colw = 58, g_cx_tfw = 36;
int     g_cx_hTitle = 34, g_cx_hStat = 21, g_cx_hTf = 19, g_cx_hBs = 26, g_cx_hStep = 35;
int     g_cx_hAct = 24, g_cx_hTab = 22, g_cx_hCont = 167, g_cx_rKV = 16, g_cx_rChip = 19;
int CP(const int base)
  {
   int v = (int)MathRound(base * g_cs);
   return(v < 1 ? 1 : v);
  }

#define EX_HIT_MAX 96
string g_hit_id[EX_HIT_MAX];
int    g_hit_x[EX_HIT_MAX], g_hit_y[EX_HIT_MAX], g_hit_w[EX_HIT_MAX], g_hit_h[EX_HIT_MAX];
int    g_hit_n = 0;

string ExTr(const string key)
  {
   int L = MolidoLangId();
   bool fa = (L==LANG_FA || L==LANG_AR);
   if(key == "subtitle") return("AI Trading Power");
   if(key == "ready")    return(fa ? "سیستم فعال و آماده معامله" : L==LANG_TR ? "Sistem hazır" : "System active and ready to trade");
   if(key == "notready") return(fa ? "سیستم آماده معامله نیست" : "System not ready to trade");
   if(key == "killed")   return(fa ? "توقف اضطراری فعال است" : "Emergency stop is on");
   if(key == "core")     return(fa ? "اتصال به مغز مرکزی" : L==LANG_TR ? "Merkezi beyin" : "Core brain link");
   if(key == "online")   return(fa ? "آنلاین" : L==LANG_TR ? "Çevrimiçi" : "Online");
   if(key == "offline")  return(fa ? "آفلاین" : L==LANG_TR ? "Çevrimdışı" : "Offline");
   if(key == "hybrid")   return("Molido AI  Hybrid Mode");
   if(key == "sigpwr")   return(fa ? "قدرت سیگنال" : L==LANG_TR ? "Sinyal gücü" : "Signal strength");
   if(key == "council")  return(fa ? "شورای 51 ایجنت هوشمند" : L==LANG_TR ? "51 ajan konseyi" : "51-agent smart council");
   if(key == "agents")   return(fa ? "ایجنت" : "Agents");
   if(key == "buy")      return(fa ? "خرید" : L==LANG_TR ? "AL" : "BUY");
   if(key == "sell")     return(fa ? "فروش" : L==LANG_TR ? "SAT" : "SELL");
   if(key == "close")    return(fa ? "بستن معامله" : L==LANG_TR ? "İşlemi kapat" : "Close position");
   if(key == "closeall") return(fa ? "بستن همه" : L==LANG_TR ? "Tümünü kapat" : "Close all");
   if(key == "lot")      return(fa ? "لات معامله" : "Lot");
   if(key == "tp")       return(fa ? "حد سود (TP)" : "Take profit (TP)");
   if(key == "sl")       return(fa ? "حد ضرر (SL)" : "Stop loss (SL)");
   if(key == "smart")    return("Smart");
   if(key == "risk")     return(fa ? "مدیریت ریسک هوشمند" : L==LANG_TR ? "Akıllı risk" : "Smart risk management");
   if(key == "perf")     return(fa ? "عملکرد معاملات" : L==LANG_TR ? "Performans" : "Trade performance");
   if(key == "markets")  return(fa ? "وضعیت بازارها" : L==LANG_TR ? "Piyasalar" : "Market status");
   if(key == "kill")     return(fa ? "توقف اضطراری" : L==LANG_TR ? "ACİL DURDUR" : "EMERGENCY STOP");
   if(key == "killsub")  return(fa ? "قطع در شرایط بحرانی" : "Halt in critical conditions");
   if(key == "safe")     return("Safe");
   if(key == "caution")  return(fa ? "احتیاط" : "Caution");
   if(key == "danger")   return(fa ? "خطر" : "Danger");
   if(key == "safemode") return(fa ? "حالت امن" : L==LANG_TR ? "Güvenli mod" : "Safe mode");
   if(key == "sm_off")   return(fa ? "حالت امن خاموش است" : "Safe mode off");
   if(key == "sm_stop")  return(fa ? "ایست امن تا" : "STOP until");
   if(key == "sm_reduce")return(fa ? "کاهش حجم به‌خاطر ضررهای پی‌درپی امروز" : "REDUCE after today's losses");
   if(key == "sm_today") return(fa ? "ضرر امروز" : "losses today");
   if(key == "r_trade")  return(fa ? "ریسک هر معامله" : "Risk per trade");
   if(key == "r_daily")  return(fa ? "حداکثر ضرر روزانه" : "Max daily loss");
   if(key == "r_dd")     return(fa ? "حداکثر Drawdown" : "Max drawdown");
   if(key == "r_open")   return(fa ? "معاملات همزمان" : "Concurrent trades");
   if(key == "today")    return(fa ? "معاملات امروز" : "Today's trades");
   if(key == "win")      return(fa ? "درصد موفقیت" : "Win rate");
   if(key == "net")      return(fa ? "سود خالص" : "Net P/L");
   if(key == "nodata")   return(fa ? "بدون داده" : L==LANG_AR ? "لا بيانات" : L==LANG_TR ? "Veri yok" : "no data");
   if(key == "dash")     return("—");
   if(key == "active")   return(fa ? "فعال" : L==LANG_TR ? "Aktif" : "Active");
   if(key == "idle")     return(fa ? "خاموش" : "Off");
   if(key == "auto")     return(fa ? "خودکار" : "AUTO");
   if(key == "stopnew")  return(fa ? "توقف ورود" : "STOP NEW");
   if(key == "on")       return(fa ? "روشن" : "On");
   if(key == "off")      return(fa ? "خاموش" : "Off");
   if(key == "tab0")     return(fa ? "معاملات" : "Trade");
   if(key == "tab1")     return(fa ? "تاریخچه" : "History");
   if(key == "tab2")     return(fa ? "سیگنال‌ها" : "Signals");
   if(key == "tab3")     return(fa ? "گزارش‌ها" : "Reports");
   if(key == "tab4")     return(fa ? "تنظیمات" : "Settings");
   if(key == "tab5")     return(fa ? "درباره" : "About");
   if(key == "g0")       return(fa ? "تحلیل بازار" : "Market analysis");
   if(key == "g1")       return(fa ? "تحلیل اخبار" : "News analysis");
   if(key == "g2")       return(fa ? "مدیریت ریسک" : "Risk management");
   if(key == "g3")       return(fa ? "تحلیل احساسات" : "Sentiment");
   if(key == "g4")       return(fa ? "شکار فرصت‌ها" : "Opportunity hunt");
   if(key == "g5")       return(fa ? "مدیریت سرمایه" : "Capital");
   if(key == "g6")       return(fa ? "یادگیری مداوم" : "Continuous learning");
   if(key == "g7")       return(fa ? "تصمیم نهایی" : "Final decision");
   if(key == "sc")       return("Scalping");
   if(key == "tf")       return("Trend Following");
   if(key == "rk")       return("Rocket Hunter");
   if(key == "sm")       return("Smart Money");
   if(key == "sp2l")     return(fa ? "تأیید SP2L" : "SP2L confirm");
   if(key == "fvg")      return(fa ? "تأیید FVG" : "FVG confirm");
   if(key == "impl_no")  return(fa ? "پیاده‌سازی نشده" : "not implemented");
   if(key == "real")     return(Tr("real_unsupported"));
   if(key == "updated")  return(fa ? "به‌روزرسانی" : "Updated");
   if(key == "gold")     return(fa ? "طلا" : "Gold");
   if(key == "forex")    return("Forex");
   if(key == "crypto")   return("Crypto");
   if(key == "about1")   return(fa ? "فقط حساب دمو. حساب واقعی مسدود است." : "Demo only. Real accounts are blocked.");
   if(key == "collapse") return(fa ? "جمع" : L==LANG_AR ? "طي" : L==LANG_TR ? "Kucult" : "Min");
   if(key == "expand")   return(fa ? "باز" : L==LANG_AR ? "فتح" : L==LANG_TR ? "Ac" : "Max");
   if(key == "c_news")   return(fa ? "اخبار" : "News");
   if(key == "c_bal")    return(fa ? "موجودی" : "Balance");
   if(key == "c_eq")     return(fa ? "دارایی" : "Equity");
   if(key == "c_fm")     return(fa ? "مارجین آزاد" : "Free margin");
   if(key == "c_wk")     return(fa ? "هفته" : "Week");
   if(key == "c_mo")     return(fa ? "ماه" : "Month");
   if(key == "c_op")     return(fa ? "باز" : "Open");
   if(key == "c_pl")     return(fa ? "سود/زیان" : "P/L");
   if(key == "c_last")   return(fa ? "آخرین سیگنال" : "Last signal");
   if(key == "c_sl")     return(fa ? "حد ضرر" : "SL");
   if(key == "c_tp")     return(fa ? "حد سود" : "TP");
   if(key == "c_riskp")  return(fa ? "درصد ریسک" : "Risk %");
   if(key == "c_maxpos") return(fa ? "حداکثر معاملات" : "Max positions");
   if(key == "c_smart")  return(fa ? "حد سود/ضرر هوشمند" : "Smart TP/SL");
   if(key == "c_magic")  return(fa ? "شناسه (Magic)" : "Magic");
   if(key == "c_reduced")return(fa ? "کاهش حجم" : "Reduced");
   if(key == "c_daily")  return(fa ? "نمودار روزانه" : "Daily P/L");
   if(key == "disc")     return(fa ? "قطع ارتباط" : "Disconnected");
   if(key == "conn")     return(fa ? "متصل" : "Connected");
   if(key == "closed")   return(fa ? "بازار بسته / داده کهنه" : "Market closed / stale tick");
   return(key);
  }

bool ExIsFullUi()
  {
   return(DashboardUiSize == DASH_UI_FULL && !g_ex_collapsed);
  }

void ExLoadCollapsed()
  {
   if(g_ex_collapse_loaded)
      return;
   g_ex_collapse_loaded = true;
   if(GlobalVariableCheck(EX_COLLAPSE_GV))
      g_ex_collapsed = (GlobalVariableGet(EX_COLLAPSE_GV) > 0.5);
  }

void ExSaveCollapsed()
  {
   GlobalVariableSet(EX_COLLAPSE_GV, g_ex_collapsed ? 1.0 : 0.0);
  }

void ExToggleCollapsed()
  {
   g_ex_collapsed = !g_ex_collapsed;
   ExSaveCollapsed();
   g_ex_sig = "";
  }

double ExUiScale()
  {
   if(!ExIsFullUi())
      return(g_cs);
   double s = DashFontScale;
   if(s < 1.0) s = 1.0;
   if(s > 1.6) s = 1.6;
   return(s);
  }

int ExPx(const int base)
  {
   int v = (int)MathRound(base * ExUiScale());
   return(v < 1 ? 1 : v);
  }

int ExLy(const int base)
  {
   double s = ExUiScale();
   if(DashboardUiSize == DASH_UI_FULL && !g_ex_collapsed && s > 1.15)
      s = 1.15;
   int v = (int)MathRound(base * s);
   return(v < 1 ? 1 : v);
  }

void ExSetOrigin(const int x, const int y)
  {
   g_ox = g_ex_px + x;
   g_oy = g_ex_py + y;
  }

void ExPanelOrigin(const int pw, const int ph, int &px, int &py)
  {
   int W = g_ex_chart_w, H = g_ex_chart_h;
   int dx = DashX, dy = DashY;
   if(dx < 0) dx = 0;
   if(dy < 0) dy = 0;
   if(DashCorner == CORNER_LEFT_UPPER) { px = dx; py = dy; }
   else if(DashCorner == CORNER_RIGHT_UPPER) { px = W - pw - dx; py = dy; }
   else if(DashCorner == CORNER_LEFT_LOWER) { px = dx; py = H - ph - dy; }
   else { px = W - pw - dx; py = H - ph - dy; }
   if(px < 0) px = 0;
   if(py < 0) py = 0;
   if(px + pw > W) px = MathMax(0, W - pw);
   if(py + ph > H) py = MathMax(0, H - ph);
  }

int ExFontSz(const int base)
  {
   int v = ExPx(base);
   int mn = (ExIsFullUi() ? 8 : 11);
   return(v < mn ? mn : v);
  }

void ExUse(CCanvas &c) { g_dc = GetPointer(c); }

void ExFont(const string face, const int base)
  {
   if(g_dc == NULL) return;
   int sz = ExFontSz(base);
   string ui = MolidoUiFont(StringFind(face, "Bold") >= 0 || StringFind(face, "Semibold") >= 0);
   if(!g_dc.FontSet(ui, sz))
      if(!g_dc.FontSet(face, sz))
         g_dc.FontSet("Tahoma", sz);
  }

uint ExArgb(const color c, const uchar a = 255) { return(ColorToARGB(c, a)); }

color ExLerp(const color a, const color b, const double t)
  {
   double k = t; if(k < 0) k = 0; if(k > 1) k = 1;
   int ar=(a&0xFF), ag=((a>>8)&0xFF), ab=((a>>16)&0xFF);
   int br=(b&0xFF), bg=((b>>8)&0xFF), bb=((b>>16)&0xFF);
   int r=(int)MathRound(ar+(br-ar)*k);
   int g=(int)MathRound(ag+(bg-ag)*k);
   int bl=(int)MathRound(ab+(bb-ab)*k);
   return((color)(r | (g<<8) | (bl<<16)));
  }

void ExRound(const int x1, const int y1, const int x2, const int y2, const int r, const uint col)
  {
   if(g_dc == NULL) return;
   int rad = r, w = x2 - x1, h = y2 - y1;
   if(w <= 0 || h <= 0) return;
   if(rad * 2 > w) rad = w / 2;
   if(rad * 2 > h) rad = h / 2;
   if(rad < 1) { g_dc.FillRectangle(x1, y1, x2, y2, col); return; }
   g_dc.FillRectangle(x1 + rad, y1, x2 - rad, y2, col);
   g_dc.FillRectangle(x1, y1 + rad, x2, y2 - rad, col);
   g_dc.FillCircle(x1 + rad, y1 + rad, rad, col);
   g_dc.FillCircle(x2 - rad, y1 + rad, rad, col);
   g_dc.FillCircle(x1 + rad, y2 - rad, rad, col);
   g_dc.FillCircle(x2 - rad, y2 - rad, rad, col);
  }

void ExGradV(const int x1, const int y1, const int x2, const int y2,
             const color c1, const color c2, const uchar a1, const uchar a2, const int r)
  {
   if(g_dc == NULL) return;
   int h = y2 - y1;
   if(h <= 0) return;
   int step = (h > 80 ? 2 : 1);
   for(int i = 0; i <= h; i += step)
     {
      double t = (double)i / (double)h;
      color c = ExLerp(c1, c2, t);
      uchar a = (uchar)MathRound(a1 + (a2 - a1) * t);
      int y = y1 + i;
      int yb = y + step - 1;
      if(yb > y2) yb = y2;
      if(r > 0 && (i < r || i > h - r))
         continue;
      g_dc.FillRectangle(x1 + (i < r || i > h - r ? r : 0), y, x2 - (i < r || i > h - r ? r : 0), yb, ExArgb(c, a));
     }
   // cap rounded ends with solid-ish fill already via ExRound caller
   if(r > 0)
     {
      // fill rounded top/bottom bands coarsely
      for(int i = 0; i < r; i++)
        {
         double t = (double)i / (double)h;
         color c = ExLerp(c1, c2, t);
         uchar a = (uchar)MathRound(a1 + (a2 - a1) * t);
         int shrink = (int)MathRound(r - MathSqrt(r * r - (r - 1 - i) * (r - 1.0 - i)));
         if(shrink < 0) shrink = 0;
         g_dc.FillRectangle(x1 + shrink, y1 + i, x2 - shrink, y1 + i, ExArgb(c, a));
        }
      for(int i = 0; i < r; i++)
        {
         double t = (double)(h - r + i) / (double)h;
         color c = ExLerp(c1, c2, t);
         uchar a = (uchar)MathRound(a1 + (a2 - a1) * t);
         int shrink = (int)MathRound(r - MathSqrt(r * r - (i) * (double)i));
         if(shrink < 0) shrink = 0;
         g_dc.FillRectangle(x1 + shrink, y2 - r + i, x2 - shrink, y2 - r + i, ExArgb(c, a));
        }
     }
  }

void ExGradH(const int x1, const int y1, const int x2, const int y2,
             const color c1, const color c2, const uchar a, const int r)
  {
   if(g_dc == NULL) return;
   int w = x2 - x1;
   if(w <= 0) return;
   int step = (w > 120 ? 2 : 1);
   for(int i = 0; i <= w; i += step)
     {
      double t = (double)i / (double)w;
      color c = ExLerp(c1, c2, t);
      int x = x1 + i;
      int xb = x + step - 1;
      if(xb > x2) xb = x2;
      int shrink = 0;
      if(r > 0)
        {
         int dy = 0;
         // leave mid band full; vertical shrink handled by prior round
        }
      g_dc.FillRectangle(x, y1 + r / 3, xb, y2 - r / 3, ExArgb(c, a));
     }
  }

void ExGlowCard(const int x1, const int y1, const int x2, const int y2, const int r, const color glow, const uchar strength)
  {
   if(g_dc == NULL) return;
   int g1 = 5, g2 = 3, g3 = 1;
   ExRound(x1 - g1, y1 - g1, x2 + g1, y2 + g1, r + 4, ExArgb(glow, (uchar)MathMax(8, strength / 5)));
   ExRound(x1 - g2, y1 - g2, x2 + g2, y2 + g2, r + 2, ExArgb(glow, (uchar)MathMax(14, strength / 3)));
   ExRound(x1 - g3, y1 - g3, x2 + g3, y2 + g3, r + 1, ExArgb(glow, strength));
   ExRound(x1, y1, x2, y2, r, ExArgb(EX_NAVY, 255));
   ExGradV(x1 + 1, y1 + 1, x2 - 1, y2 - 1, EX_NAVY2, EX_BLACK, 255, 255, r - 1);
   // bevel
   g_dc.FillRectangle(x1 + r, y1 + 1, x2 - r, y1 + 2, ExArgb(EX_GOLD2, 50));
   g_dc.FillRectangle(x1 + r, y2 - 2, x2 - r, y2 - 1, ExArgb(EX_BLACK, 80));
  }

void ExHitsClear() { g_hit_n = 0; }

void ExHitAdd(const string id, const int x, const int y, const int w, const int h)
  {
   if(g_hit_n >= EX_HIT_MAX) return;
   g_hit_id[g_hit_n] = id;
   g_hit_x[g_hit_n] = x + g_ox; g_hit_y[g_hit_n] = y + g_oy;
   g_hit_w[g_hit_n] = w; g_hit_h[g_hit_n] = h;
   g_hit_n++;
  }

string ExHitAt(const int x, const int y)
  {
   for(int i = g_hit_n - 1; i >= 0; i--)
      if(x >= g_hit_x[i] && x < g_hit_x[i] + g_hit_w[i] && y >= g_hit_y[i] && y < g_hit_y[i] + g_hit_h[i])
         return(g_hit_id[i]);
   return("");
  }

double ExPulse()
  {
   // 1s frames; period ~2s. Range 0.35..1.0
   int s = (int)(TimeLocal() % 2);
   return(s == 0 ? 0.45 : 0.95);
  }

void ExLayoutFull(const int W, const int H)
  {
   g_ex_px = 0; g_ex_py = 0;
   g_ex_cw = W; g_ex_ch = H;
   // reserved bands — never shrink the tab bar (it was getting clipped)
   g_ly_head = ExLy(68);
   g_ly_tab  = ExLy(46);
   g_ly_mid  = ExLy(66);
   g_ly_bot  = ExLy(132);
   g_ly_left = (int)MathRound(W * 0.17);
   if(g_ly_left < 180) g_ly_left = 180;
   if(g_ly_left > 240) g_ly_left = 240;
   g_ly_right = (int)MathRound(W * 0.32);
   if(g_ly_right < 300) g_ly_right = 300;
   if(g_ly_right > 400) g_ly_right = 400;
   int hole_w = W - g_ly_left - g_ly_right;
   int hole_h = H - g_ly_head - g_ly_mid - g_ly_bot - g_ly_tab;
   if(hole_w < 280)
     {
      int need = 280 - hole_w;
      int cut_r = need / 2, cut_l = need - cut_r;
      g_ly_right -= cut_r; g_ly_left -= cut_l;
      if(g_ly_right < 260) g_ly_right = 260;
      if(g_ly_left < 160) g_ly_left = 160;
      hole_w = W - g_ly_left - g_ly_right;
     }
   if(hole_h < 240)
     {
      int deficit = 240 - hole_h;
      if(g_ly_bot > ExLy(112) && deficit > 0)
        { int c = MathMin(deficit, g_ly_bot - ExLy(112)); g_ly_bot -= c; deficit -= c; }
      if(g_ly_mid > ExLy(58) && deficit > 0)
        { int c = MathMin(deficit, g_ly_mid - ExLy(58)); g_ly_mid -= c; deficit -= c; }
      hole_h = H - g_ly_head - g_ly_mid - g_ly_bot - g_ly_tab;
     }
   g_ly_hx = g_ly_left;
   g_ly_hy = g_ly_head;
   g_ly_hw = W - g_ly_left - g_ly_right;
   g_ly_hh = H - g_ly_head - g_ly_mid - g_ly_bot - g_ly_tab;
   if(g_ly_hw < 200) g_ly_hw = 200;
   if(g_ly_hh < 140) g_ly_hh = 140;
  }

void ExLayoutPanel(const int W, const int H)
  {
   bool normal = (DashboardUiSize == DASH_UI_NORMAL);
   double s0 = DashboardScale;
   if(s0 < 0.40) s0 = 0.40;
   if(s0 > 1.60) s0 = 1.60;
   if(normal) s0 *= 1.0;
   double frac = (normal ? 0.60 : 0.55);
   double sw = frac * W / 500.0;
   double sh = 0.97 * H / 556.0;
   double s = MathMin(s0, MathMin(sw, sh));
   if(s < 0.50) s = 0.50;
   g_cs = s;
   // strict grid: equal margins/gaps; 6 columns and a 9-button row share one inner width
   int pad = 2 * (int)MathRound(5.0 * s);
   if(pad < 6) pad = 6;
   int gap = pad;
   int inner = (int)MathRound(500.0 * s) - 2 * pad;
   int tfw = (inner - 8 * gap) / 9;
   tfw -= tfw % 2;
   if(tfw < 20) tfw = 20;
   int colw = (3 * tfw + gap) / 2;
   g_cx_pad = pad; g_cx_colw = colw; g_cx_tfw = tfw;
   inner = 6 * colw + 5 * gap;
   int pw = inner + 2 * pad;
   g_cx_hTitle = CP(44); g_cx_hStat = CP(28); g_cx_hTf = CP(26); g_cx_hBs = CP(34);
   g_cx_hStep = CP(48);  g_cx_hAct = CP(32);  g_cx_hTab = CP(30);
   g_cx_rKV = CP(22);    g_cx_rChip = CP(26);
   g_cx_hCont = 2 * g_cx_rKV + 5 * g_cx_rChip + 5 * gap;
   int ph;
   if(g_ex_collapsed)
      ph = g_cx_hTitle;
   else
      ph = g_cx_hTitle + gap + g_cx_hStat + gap + g_cx_hTf + gap + g_cx_hBs + gap +
           g_cx_hStep + gap + g_cx_hAct + gap + g_cx_hTab + gap + g_cx_hCont + pad;
   ExPanelOrigin(pw, ph, g_ex_px, g_ex_py);
   g_ex_cw = pw;
   g_ex_ch = ph;
   g_ly_head = g_cx_hTitle;
   g_ly_tab = g_cx_hTab; g_ly_mid = 0; g_ly_bot = 0;
   g_ly_left = pw / 2; g_ly_right = pw - g_ly_left;
   g_ly_hx = 0; g_ly_hy = g_ly_head; g_ly_hw = pw; g_ly_hh = 0;
  }

void ExLayout()
  {
   int W = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int H = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   if(W < 200) W = 200;
   if(H < 200) H = 200;
   g_ex_chart_w = W;
   g_ex_chart_h = H;
   ExLoadCollapsed();
   if(ExIsFullUi())
      ExLayoutFull(W, H);
   else
      ExLayoutPanel(W, H);
  }

void ExDestroyMarks()
  {
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, EX_MARK) == 0 || StringFind(name, EX_BTN) == 0)
         ObjectDelete(0, name);
     }
  }

void ExDestroy()
  {
   if(g_ex_ready)
     {
      g_cv_h.Destroy(); g_cv_l.Destroy(); g_cv_r.Destroy();
      g_cv_m.Destroy(); g_cv_b.Destroy(); g_cv_t.Destroy(); g_cv_tag.Destroy(); g_cv_hud.Destroy();
      g_ex_ready = false;
     }
   string names[8] = {EX_H,EX_L,EX_R,EX_M,EX_B,EX_T,EX_TAG,EX_HUD};
   for(int i = 0; i < 8; i++)
      if(ObjectFind(0, names[i]) >= 0)
         ObjectDelete(0, names[i]);
   if(ObjectFind(0, EX_LIVE) >= 0)
      ObjectDelete(0, EX_LIVE);
   ExRestoreHostChart();
   ExDestroyMarks();
   g_ex_sig = "";
   g_ex_cw = 0; g_ex_ch = 0;
   g_dc = NULL;
   ChartRedraw(0);
  }

bool ExMake(CCanvas &c, const string name, const int x, const int y, const int w, const int h)
  {
   if(w < 8 || h < 8) return(false);
   if(ObjectFind(0, name) >= 0)
      ObjectDelete(0, name);
   if(!c.CreateBitmapLabel(name, x, y, w, h, COLOR_FORMAT_ARGB_NORMALIZE))
     {
      Print("MolidoExpert: canvas ", name, " failed ", GetLastError());
      return(false);
     }
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 80);
   return(true);
  }

void ExHideHostChart()
  {
   if(!g_ex_host_saved)
     {
      g_host_bg   = (color)ChartGetInteger(0, CHART_COLOR_BACKGROUND);
      g_host_fg   = (color)ChartGetInteger(0, CHART_COLOR_FOREGROUND);
      g_host_grid = (color)ChartGetInteger(0, CHART_COLOR_GRID);
      g_host_up   = (color)ChartGetInteger(0, CHART_COLOR_CHART_UP);
      g_host_dn   = (color)ChartGetInteger(0, CHART_COLOR_CHART_DOWN);
      g_host_bull = (color)ChartGetInteger(0, CHART_COLOR_CANDLE_BULL);
      g_host_bear = (color)ChartGetInteger(0, CHART_COLOR_CANDLE_BEAR);
      g_host_show_grid  = (bool)ChartGetInteger(0, CHART_SHOW_GRID);
      g_host_show_date  = (bool)ChartGetInteger(0, CHART_SHOW_DATE_SCALE);
      g_host_show_price = (bool)ChartGetInteger(0, CHART_SHOW_PRICE_SCALE);
      g_ex_host_saved = true;
     }
   color bg = EX_NAVY;
   ChartSetInteger(0, CHART_COLOR_BACKGROUND, bg);
   ChartSetInteger(0, CHART_COLOR_FOREGROUND, bg);
   ChartSetInteger(0, CHART_COLOR_GRID, bg);
   ChartSetInteger(0, CHART_COLOR_CHART_UP, bg);
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN, bg);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, bg);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, bg);
   ChartSetInteger(0, CHART_COLOR_CHART_LINE, bg);
   ChartSetInteger(0, CHART_COLOR_VOLUME, bg);
   ChartSetInteger(0, CHART_COLOR_BID, bg);
   ChartSetInteger(0, CHART_COLOR_ASK, bg);
   ChartSetInteger(0, CHART_COLOR_LAST, bg);
   ChartSetInteger(0, CHART_COLOR_STOP_LEVEL, bg);
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_SHOW_DATE_SCALE, false);
   ChartSetInteger(0, CHART_SHOW_PRICE_SCALE, false);
   ChartSetInteger(0, CHART_SHOW_OHLC, false);
   ChartSetInteger(0, CHART_SHOW_ASK_LINE, false);
   ChartSetInteger(0, CHART_SHOW_BID_LINE, false);
   ChartSetInteger(0, CHART_SHOW_LAST_LINE, false);
   ChartSetInteger(0, CHART_SHOW_PERIOD_SEP, false);
   ChartSetInteger(0, CHART_SHOW_VOLUMES, CHART_VOLUME_HIDE);
   ChartSetInteger(0, CHART_SHOW_OBJECT_DESCR, false);
  }

void ExRestoreHostChart()
  {
   if(!g_ex_host_saved) return;
   ChartSetInteger(0, CHART_COLOR_BACKGROUND, g_host_bg);
   ChartSetInteger(0, CHART_COLOR_FOREGROUND, g_host_fg);
   ChartSetInteger(0, CHART_COLOR_GRID, g_host_grid);
   ChartSetInteger(0, CHART_COLOR_CHART_UP, g_host_up);
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN, g_host_dn);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, g_host_bull);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, g_host_bear);
   ChartSetInteger(0, CHART_SHOW_GRID, g_host_show_grid);
   ChartSetInteger(0, CHART_SHOW_DATE_SCALE, g_host_show_date);
   ChartSetInteger(0, CHART_SHOW_PRICE_SCALE, g_host_show_price);
   g_ex_host_saved = false;
  }

void ExPlaceLiveChart()
  {
   if(g_ly_hw < 40 || g_ly_hh < 40)
      return;
   if(ObjectFind(0, EX_LIVE) < 0)
     {
      if(!ObjectCreate(0, EX_LIVE, OBJ_CHART, 0, 0, 0.0))
        {
         Print("MolidoExpert: live chart failed ", GetLastError());
         return;
        }
     }
   int inset = ExLy(4);
   int scale_w = ExLy(58); // MT5 draws the object-chart price scale to the right of the box
   ObjectSetInteger(0, EX_LIVE, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_XDISTANCE, g_ly_hx + inset);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_YDISTANCE, g_ly_hy + inset);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_XSIZE, g_ly_hw - inset * 2 - scale_w);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_YSIZE, g_ly_hh - inset * 2);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_BACK, false);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_ZORDER, 40);
   ObjectSetString(0, EX_LIVE, OBJPROP_SYMBOL, _Symbol);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_PERIOD, Period());
   ObjectSetInteger(0, EX_LIVE, OBJPROP_DATE_SCALE, true);
   ObjectSetInteger(0, EX_LIVE, OBJPROP_PRICE_SCALE, true);
   long cid = ObjectGetInteger(0, EX_LIVE, OBJPROP_CHART_ID);
   if(cid > 0)
     {
      ChartSetInteger(cid, CHART_MODE, CHART_CANDLES);
      ChartSetInteger(cid, CHART_SHOW_GRID, true);
      ChartSetInteger(cid, CHART_SHOW_DATE_SCALE, true);
      ChartSetInteger(cid, CHART_SHOW_PRICE_SCALE, true);
      ChartSetInteger(cid, CHART_SHOW_OHLC, false);
      ChartSetInteger(cid, CHART_SHOW_ASK_LINE, true);
      ChartSetInteger(cid, CHART_SHOW_VOLUMES, CHART_VOLUME_HIDE);
      ChartSetInteger(cid, CHART_SHIFT, true);
      ChartSetDouble(cid, CHART_SHIFT_SIZE, 8.0);
      ChartSetInteger(cid, CHART_COLOR_BACKGROUND, EX_NAVY);
      ChartSetInteger(cid, CHART_COLOR_FOREGROUND, EX_MUTED);
      ChartSetInteger(cid, CHART_COLOR_GRID, EX_LINE);
      ChartSetInteger(cid, CHART_COLOR_CHART_UP, EX_GREEN);
      ChartSetInteger(cid, CHART_COLOR_CANDLE_BULL, EX_GREEN);
      ChartSetInteger(cid, CHART_COLOR_CHART_DOWN, EX_CORAL);
      ChartSetInteger(cid, CHART_COLOR_CANDLE_BEAR, EX_CORAL);
      ChartSetInteger(cid, CHART_COLOR_BID, EX_BLUE);
      ChartSetInteger(cid, CHART_COLOR_ASK, EX_GOLD);
      ChartRedraw(cid);
     }
  }

void ExHudTagPos(int &tx, int &ty, int &tw, int &th, int &hx, int &hy, int &hw, int &hh)
  {
   tw = ExPx(86); th = ExPx(40);
   hw = ExPx(280); hh = ExPx(28);
   if(ExIsFullUi())
     {
      tx = g_ly_hx + g_ly_hw - tw - ExPx(8);
      ty = g_ly_hy + ExPx(8);
      hx = g_ly_hx + ExPx(8);
      hy = g_ly_hy + ExPx(6);
      if(hx + hw > tx - 8) hw = MathMax(ExPx(140), tx - hx - 8);
      return;
     }
   int cw = g_ex_chart_w, ch = g_ex_chart_h;
   int pad = 8;
   bool left = (DashCorner == CORNER_LEFT_UPPER || DashCorner == CORNER_LEFT_LOWER);
   bool top  = (DashCorner == CORNER_LEFT_UPPER || DashCorner == CORNER_RIGHT_UPPER);
   if(left)
     {
      hx = g_ex_px + g_ex_cw + pad;
      if(hx + hw > cw - pad) hx = MathMax(pad, cw - hw - pad);
      tx = cw - tw - pad;
     }
   else
     {
      hx = pad;
      tx = pad;
     }
   hy = top ? pad : MathMax(pad, ch - hh - pad);
   ty = top ? pad : MathMax(pad, ch - th - pad);
   if(left && tx < hx + hw + pad)
      tx = MathMax(pad, hx + hw + pad);
   if(!left && hx + hw > g_ex_px - pad && g_ex_px > pad)
      hw = MathMax(ExPx(140), g_ex_px - hx - pad);
  }

bool ExEnsure()
  {
   if(!ShowDashboard)
     { ExDestroy(); return(false); }
   ExLoadCollapsed();
   ExLayout();
   int W = g_ex_cw, H = g_ex_ch;
   if(g_ex_ready)
     {
      if(ExIsFullUi())
         ExPlaceLiveChart();
      else
        {
         if(ObjectFind(0, EX_LIVE) >= 0)
            ObjectDelete(0, EX_LIVE);
         ExRestoreHostChart();
        }
      return(true);
     }
   int ox = g_ex_px, oy = g_ex_py;
   int mid_y = oy + g_ly_hy + g_ly_hh;
   int bot_y = mid_y + g_ly_mid;
   int tab_y = oy + H - g_ly_tab;
   if(!ExIsFullUi())
     {
      if(!ExMake(g_cv_h, EX_H, ox, oy, W, H)) return(false);
      if(ObjectFind(0, EX_LIVE) >= 0) ObjectDelete(0, EX_LIVE);
      if(ObjectFind(0, EX_TAG) >= 0) ObjectDelete(0, EX_TAG);
      if(ObjectFind(0, EX_HUD) >= 0) ObjectDelete(0, EX_HUD);
      ExRestoreHostChart();
      g_ex_ready = true;
      g_ex_sig = "";
      return(true);
     }
   if(!ExMake(g_cv_h, EX_H, ox, oy, W, g_ly_head)) return(false);
   if(!g_ex_collapsed)
     {
      int side_h = mid_y - (oy + g_ly_head);
      if(!ExMake(g_cv_l, EX_L, ox, oy + g_ly_head, g_ly_left, side_h)) return(false);
      if(!ExMake(g_cv_r, EX_R, ox + W - g_ly_right, oy + g_ly_head, g_ly_right, side_h)) return(false);
      if(!ExMake(g_cv_m, EX_M, ox, mid_y, W, g_ly_mid)) return(false);
      if(!ExMake(g_cv_b, EX_B, ox, bot_y, W, g_ly_bot)) return(false);
      if(!ExMake(g_cv_t, EX_T, ox, tab_y, W, g_ly_tab)) return(false);
     }
   int tw, th, tx, ty, hw, hh, hx, hy;
   ExHudTagPos(tx, ty, tw, th, hx, hy, hw, hh);
   if(!ExMake(g_cv_tag, EX_TAG, tx, ty, tw, th)) return(false);
   if(!ExMake(g_cv_hud, EX_HUD, hx, hy, hw, hh)) return(false);
   if(ExIsFullUi())
     {
      ExHideHostChart();
      ExPlaceLiveChart();
     }
   else
     {
      if(ObjectFind(0, EX_LIVE) >= 0)
         ObjectDelete(0, EX_LIVE);
      ExRestoreHostChart();
     }
   g_ex_ready = true;
   g_ex_sig = "";
   return(true);
  }

void ExRelayout()
  {
   ExDestroy();
   ExEnsure();
  }

void ExText(const int x, const int y, const string s, const color c, const uchar a = 255)
  {
   if(g_dc == NULL) return;
   g_dc.TextOut(x, y, s, ExArgb(c, a), 0);
  }

int ExTw(const string s)
  {
   if(g_dc == NULL) return(0);
   return(g_dc.TextWidth(s));
  }

void ExPill(const int x, const int y, const int w, const int h, const color fill, const color fg,
            const string text, const bool glow)
  {
   double p = (glow ? ExPulse() : 0.4);
   uchar ga = (uchar)MathRound(40 + 80 * p);
   if(glow)
      ExRound(x - 2, y - 2, x + w + 2, y + h + 2, h / 2 + 2, ExArgb(fill, ga));
   ExRound(x, y, x + w, y + h, h / 2, ExArgb(fill, 40));
   ExRound(x + 1, y + 1, x + w - 1, y + h - 1, h / 2 - 1, ExArgb(EX_NAVY, 200));
   ExFont("Segoe UI Semibold", 9);
   int tw = ExTw(text);
   ExText(x + (w - tw) / 2, y + (h - ExFontSz(9)) / 2 - 1, text, fg);
  }

void ExHeartbeat(const int x, const int y, const color c, const bool live)
  {
   if(g_dc == NULL) return;
   double p = (live ? ExPulse() : 0.25);
   int r = (int)MathRound(ExPx(3) + ExPx(2) * p);
   g_dc.FillCircle(x, y, r + 2, ExArgb(c, (uchar)MathRound(40 + 70 * p)));
   g_dc.FillCircle(x, y, r, ExArgb(c, (uchar)MathRound(160 + 90 * p)));
  }

void ExLogoM(const int x, const int y, const int s)
  {
   if(g_dc == NULL) return;
   int r = s / 5;
   ExRound(x, y, x + s, y + s, r, ExArgb(EX_GOLD, 40));
   ExRound(x + 2, y + 2, x + s - 2, y + s - 2, r, ExArgb(EX_NAVY, 240));
   ExRound(x + 3, y + 3, x + s - 3, y + s - 3, r - 1, ExArgb(EX_GOLD, 200));
   ExFont("Segoe UI Bold", 16);
   string m = "M";
   int tw = ExTw(m);
   ExText(x + (s - tw) / 2, y + s / 2 - ExFontSz(16) / 2 - 1, m, EX_NAVY);
  }

void ExLockIcon(const int x, const int y, const color c)
  {
   if(g_dc == NULL) return;
   int s = ExPx(7);
   g_dc.FillRectangle(x - s, y, x + s, y + s + 2, ExArgb(c, 220));
   // shackle
   g_dc.FillCircle(x, y - 1, s - 1, ExArgb(c, 220));
   g_dc.FillCircle(x, y - 1, s - 3, ExArgb(EX_NAVY, 240));
   g_dc.FillCircle(x, y + s / 2, 2, ExArgb(EX_NAVY, 255));
  }

void ExRobot(const int x, const int y, const int w, const int h)
  {
   if(g_dc == NULL) return;
   int cx = x + w / 2;
   int cy = y + h / 2 + ExPx(4);
   int rx = w / 2 - ExPx(8);
   int ry = h / 2 - ExPx(6);
   double p = ExPulse();
   uchar glow = (uchar)MathRound(50 + 70 * p);
   g_dc.FillCircle(cx, cy, rx + 6, ExArgb(EX_BLUE, (uchar)(glow / 2)));
   g_dc.FillCircle(cx, cy, rx + 2, ExArgb(EX_BLUE, glow));
   // helmet
   g_dc.FillCircle(cx, cy - 2, rx - 2, ExArgb(C'20,40,70', 255));
   g_dc.FillCircle(cx, cy - 4, rx - 8, ExArgb(C'10,18,36', 255));
   // visor
   int vw = rx - ExPx(10);
   int vh = ExPx(10);
   ExRound(cx - vw, cy - ExPx(4), cx + vw, cy + vh, ExPx(5), ExArgb(EX_BLUE, (uchar)MathRound(80 + 120 * p)));
   ExRound(cx - vw + 2, cy - ExPx(2), cx + vw - 2, cy + vh - 2, ExPx(4), ExArgb(C'8,160,220', 220));
   // gold crest
   ExFont("Segoe UI Bold", 9);
   int tw = ExTw("M");
   ExText(cx - tw / 2, cy - rx + ExPx(6), "M", EX_GOLD2);
   // chin / collar
   ExRound(cx - ExPx(18), cy + ExPx(16), cx + ExPx(18), cy + ExPx(28), ExPx(6), ExArgb(EX_BLUE2, 180));
   g_dc.FillCircle(cx - rx / 2, cy + 2, 2, ExArgb(EX_BLUE, 200));
   g_dc.FillCircle(cx + rx / 2, cy + 2, 2, ExArgb(EX_BLUE, 200));
  }
void ExDrawAvatar(const int x, const int y, const int w, const int h)
  {
   if(g_dc == NULL) return;
   uint px[];
   uint iw = 0, ih = 0;
   if(!ResourceReadImage("::Images\\molido_avatar.bmp", px, iw, ih) || iw == 0 || ih == 0)
     {
      ExRobot(x, y, w, h);
      return;
     }
   double sc = MathMin((double)w / (double)iw, (double)h / (double)ih);
   int dw = (int)MathRound(iw * sc);
   int dh = (int)MathRound(ih * sc);
   if(dw < 8) dw = 8;
   if(dh < 8) dh = 8;
   int ox = x + (w - dw) / 2;
   int oy = y + (h - dh) / 2;
   for(int yy = 0; yy < dh; yy++)
     {
      int sy = yy * (int)ih / dh;
      if(sy < 0) sy = 0;
      if(sy >= (int)ih) sy = (int)ih - 1;
      for(int xx = 0; xx < dw; xx++)
        {
         int sx = xx * (int)iw / dw;
         if(sx < 0) sx = 0;
         if(sx >= (int)iw) sx = (int)iw - 1;
         g_dc.PixelSet(ox + xx, oy + yy, px[sy * (int)iw + sx]);
        }
     }
  }


void ExGaugeSemi(const int cx, const int cy, const int rad, const double shown, const int target)
  {
   if(g_dc == NULL) return;
   int thick = ExPx(6);
   double p = ExPulse();
   // track
   int steps = 36;
   for(int i = 0; i <= steps; i++)
     {
      double a = MathArctan(1.0) * 4.0 * (1.0 - (double)i / steps); // pi .. 0
      int x = cx + (int)MathRound(rad * MathCos(a));
      int y = cy - (int)MathRound(rad * MathSin(a));
      g_dc.FillCircle(x, y, thick, ExArgb(EX_LINE, 180));
     }
   double frac = shown / 100.0;
   if(frac < 0) frac = 0;
   if(frac > 1) frac = 1;
   color gc = (shown >= 70 ? EX_GREEN : shown >= 40 ? EX_AMBER : EX_CORAL);
   int lit = (int)MathRound(steps * frac);
   for(int i = 0; i <= lit; i++)
     {
      double a = MathArctan(1.0) * 4.0 * (1.0 - (double)i / steps);
      int x = cx + (int)MathRound(rad * MathCos(a));
      int y = cy - (int)MathRound(rad * MathSin(a));
      g_dc.FillCircle(x, y, thick + 1, ExArgb(gc, (uchar)MathRound(140 + 80 * p)));
      g_dc.FillCircle(x, y, thick - 1, ExArgb(gc, 255));
     }
   string pct = (target < 0 ? ExTr("dash") : IntegerToString((int)MathRound(shown)) + "%");
   ExFont("Segoe UI Bold", 14);
   int tw = ExTw(pct);
   ExText(cx - tw / 2, cy - ExFontSz(14) - 2, pct, EX_TEXT);
   ExFont("Segoe UI", 8);
   string lab = ExTr("sigpwr");
   int lw = ExTw(lab);
   ExText(cx - lw / 2, cy + ExPx(2), lab, EX_MUTED);
  }

void ExCheck(const int x, const int y, const bool on, const bool impl)
  {
   if(g_dc == NULL) return;
   int s = ExPx(7);
   color c = (!impl ? EX_MUTED : (on ? EX_GREEN : EX_LINE));
   ExRound(x, y, x + s * 2, y + s * 2, 3, ExArgb(c, impl && on ? 200 : 100));
   if(impl && on)
     {
      // simple tick
      g_dc.FillRectangle(x + 3, y + s, x + s - 1, y + s * 2 - 3, ExArgb(EX_NAVY, 255));
      g_dc.FillRectangle(x + s - 2, y + 3, x + s * 2 - 3, y + s * 2 - 3, ExArgb(EX_NAVY, 255));
     }
  }

void ExBtn3D(const string id, const int ax, const int ay, const int w, const int h,
             const string cap, const color c1, const color c2, const color fg, const bool danger)
  {
   if(g_dc == NULL) return;
   bool hover = (g_hover == id);
   bool press = (g_pressed == id);
   int r = (h < ExPx(28) ? ExPx(6) : ExPx(8));
   color glow = (danger ? EX_CORAL : c1);
   uchar gs = (uchar)(hover || press ? 160 : 70);
   if(hover || press)
      ExRound(ax - 2, ay - 2, ax + w + 2, ay + h + 2, r + 2, ExArgb(glow, gs));
   ExRound(ax, ay, ax + w, ay + h, r, ExArgb(c2, 255));
   if(!press)
      ExGradV(ax + 1, ay + 1, ax + w - 1, ay + h - 1, c1, c2, 255, 255, r - 1);
   else
      ExGradV(ax + 1, ay + 1, ax + w - 1, ay + h - 1, c2, c1, 255, 255, r - 1);
   g_dc.FillRectangle(ax + r, ay + 1, ax + w - r, ay + 2, ExArgb(EX_TEXT, press ? 20 : 70));
   int maxw = w - ExPx(8);
   if(maxw < 8) maxw = 8;
   int fs = (h >= ExPx(36) && w > ExPx(90) ? 11 : (h >= ExPx(26) ? 9 : 8));
   string l1 = cap, l2 = "";
   int br = StringFind(cap, "\n");
   if(br >= 0)
     {
      l1 = StringSubstr(cap, 0, br);
      l2 = StringSubstr(cap, br + 1);
     }
   ExFont("Segoe UI Bold", fs);
   if(l2 == "")
     {
      while(fs > 7 && ExTw(l1) > maxw)
        {
         fs--;
         ExFont("Segoe UI Bold", fs);
        }
      if(ExTw(l1) > maxw)
        {
         int best = -1;
         int mid = StringLen(l1) / 2;
         for(int i = 1; i < StringLen(l1) - 1; i++)
           {
            ushort ch = (ushort)StringGetCharacter(l1, i);
            if(ch == ' ' || ch == 0x200C)
              {
               if(best < 0 || MathAbs(i - mid) < MathAbs(best - mid))
                  best = i;
              }
           }
         if(best > 0)
           {
            l2 = StringSubstr(l1, best + 1);
            l1 = StringSubstr(l1, 0, best);
           }
        }
     }
   else
     {
      while(fs > 7 && (ExTw(l1) > maxw || ExTw(l2) > maxw))
        {
         fs--;
         ExFont("Segoe UI Bold", fs);
        }
     }
   int fh = ExFontSz(fs);
   int ty;
   if(l2 == "")
     {
      int tw = ExTw(l1);
      int tx = ax + (w - tw) / 2;
      ty = ay + (h - fh) / 2 - 1;
      if(press) { tx++; ty++; }
      ExText(tx, ty, l1, fg);
     }
   else
     {
      int tw1 = ExTw(l1);
      int tw2 = ExTw(l2);
      ty = ay + (h - 2 * fh - 2) / 2;
      int tx1 = ax + (w - tw1) / 2;
      int tx2 = ax + (w - tw2) / 2;
      if(press) { tx1++; tx2++; ty++; }
      ExText(tx1, ty, l1, fg);
      ExText(tx2, ty + fh + 1, l2, fg);
     }
   ExHitAdd(id, ax, ay, w, h);
  }

void ExStepper(const string id, const int ax, const int ay, const int w, const int h,
               const string label, const string value)
  {
   ExGlowCard(ax, ay, ax + w, ay + h, ExPx(8), EX_BLUE, 50);
   int bw = MathMin(ExPx(22), MathMax(ExPx(16), h - ExPx(16)));
   int bh = bw;
   int by = ay + (h - bh) / 2;
   ExBtn3D(id + "_dn", ax + ExPx(6), by, bw, bh, "-", EX_CARD, EX_NAVY, EX_TEXT, false);
   ExBtn3D(id + "_up", ax + w - bw - ExPx(6), by, bw, bh, "+", EX_CARD, EX_NAVY, EX_TEXT, false);
   ExFont("Segoe UI", 7);
   int lw = ExTw(label);
   ExText(ax + (w - lw) / 2, ay + ExPx(4), label, EX_MUTED);
   ExFont("Segoe UI Bold", 11);
   int tw = ExTw(value);
   int ty = ay + (h - ExFontSz(11)) / 2 + ExPx(4);
   ExText(ax + (w - tw) / 2, ty, value, EX_TEXT);
  }

void ExSafeBadge(const int x, const int y, const int s, const int level)
  {
   // level 0 safe, 1 caution, 2 danger
   color c = (level == 0 ? EX_GREEN : (level == 1 ? EX_AMBER : EX_CORAL));
   string lab = (level == 0 ? ExTr("safe") : (level == 1 ? ExTr("caution") : ExTr("danger")));
   double p = ExPulse();
   g_dc.FillCircle(x, y, s + 4, ExArgb(c, (uchar)MathRound(40 + 50 * p)));
   g_dc.FillCircle(x, y, s, ExArgb(c, 200));
   // shield body
   int sh = s - 4;
   ExRound(x - sh + 2, y - sh + 4, x + sh - 2, y + sh - 2, 4, ExArgb(EX_NAVY, 230));
   // check / ! 
   ExFont("Segoe UI Bold", 8);
   string ic = (level == 0 ? "OK" : "!");
   int tw = ExTw(ic);
   ExText(x - tw / 2, y - ExFontSz(8) / 2 - 2, ic, c);
   ExFont("Segoe UI Bold", 10);
   int lw = ExTw(lab);
   ExText(x - lw / 2, y + s + ExPx(2), lab, c);
  }

void ExSpark(const int x, const int y, const int w, const int h, const string sym)
  {
   if(g_dc == NULL) return;
   ExRound(x, y, x + w, y + h, 3, ExArgb(EX_NAVY, 200));
   if(StringLen(sym) == 0 || !SymbolSelect(sym, false))
      return;
   double cl[];
   ArraySetAsSeries(cl, true);
   int n = CopyClose(sym, PERIOD_M15, 0, 20, cl);
   if(n < 4)
      return;
   double mn = cl[0], mx = cl[0];
   for(int i = 1; i < n; i++)
     {
      if(cl[i] < mn) mn = cl[i];
      if(cl[i] > mx) mx = cl[i];
     }
   double rng = mx - mn;
   if(rng <= 0.0) rng = 1.0;
   int prevx = 0, prevy = 0;
   color sc = (cl[0] >= cl[n - 1] ? EX_GREEN : EX_CORAL);
   for(int i = 0; i < n; i++)
     {
      int px = x + 2 + (w - 4) * i / (n - 1);
      int py = y + h - 2 - (int)MathRound((h - 4) * (cl[n - 1 - i] - mn) / rng);
      if(i > 0)
         g_dc.Line(prevx, prevy, px, py, ExArgb(sc, 220));
      prevx = px; prevy = py;
     }
  }

int ExDailyBuckets(double &bars[], const int maxn)
  {
   ArrayInitialize(bars, 0);
   datetime now = TimeCurrent();
   datetime from = now - 86400 * maxn;
   if(!HistorySelect(from, now))
      return(0);
   int total = HistoryDealsTotal();
   int used = 0;
   datetime day0 = ExpertDayStart(now);
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if((int)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT &&
         (int)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_INOUT)
         continue;
      if(!ExpertIsOurs(HistoryDealGetInteger(ticket, DEAL_MAGIC), HistoryDealGetString(ticket, DEAL_COMMENT)))
         continue;
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      int idx = (int)((day0 - ExpertDayStart(t)) / 86400);
      if(idx < 0 || idx >= maxn) continue;
      int dest = maxn - 1 - idx;
      bars[dest] += HistoryDealGetDouble(ticket, DEAL_PROFIT)
                    + HistoryDealGetDouble(ticket, DEAL_SWAP)
                    + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      used++;
     }
   return(used);
  }

void ExPerfBars(const int x, const int y, const int w, const int h)
  {
   double bars[10];
   int used = ExDailyBuckets(bars, 10);
   ExRound(x, y, x + w, y + h, 3, ExArgb(EX_NAVY, 200));
   if(used <= 0)
     {
      ExFont("Segoe UI", 8);
      string nd = ExTr("nodata");
      ExText(x + ExPx(6), y + h / 2 - 6, nd, EX_AMBER);
      return;
     }
   double mx = 0.0;
   for(int i = 0; i < 10; i++)
      if(MathAbs(bars[i]) > mx) mx = MathAbs(bars[i]);
   if(mx <= 0.0) mx = 1.0;
   int gap = 2;
   int bw = (w - 11 * gap) / 10;
   if(bw < 2) bw = 2;
   int mid = y + h / 2;
   for(int i = 0; i < 10; i++)
     {
      int bh = (int)MathRound((h / 2 - 2) * MathAbs(bars[i]) / mx);
      if(bh < 1 && bars[i] != 0.0) bh = 1;
      int bx = x + gap + i * (bw + gap);
      color c = (bars[i] >= 0 ? EX_GREEN : EX_CORAL);
      if(bars[i] >= 0)
         g_dc.FillRectangle(bx, mid - bh, bx + bw, mid, ExArgb(c, 220));
      else
         g_dc.FillRectangle(bx, mid, bx + bw, mid + bh, ExArgb(c, 220));
     }
  }

string ExPriceStr(const double px)
  {
   if(px <= 0.0) return(ExTr("dash"));
   int d = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(d < 0) d = 2;
   if(d > 5) d = 5;
   return(DoubleToString(px, d));
  }

string ExSlPreview()
  {
   if(g_ex_smart_sl || g_ex_sl_pts <= 0.0) return(ExTr("smart"));
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(point <= 0.0 || bid <= 0.0) return(ExTr("dash"));
   return(ExPriceStr(bid - g_ex_sl_pts * point));
  }

string ExTpPreview()
  {
   if(g_ex_tp_pts <= 0.0)
      return(g_ex_smart_sl ? ExTr("smart") : ExTr("dash"));
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(point <= 0.0 || ask <= 0.0) return(ExTr("dash"));
   return(ExPriceStr(ask + g_ex_tp_pts * point));
  }

int ExRiskLevel(const double daily_used, const double dd_used, const bool killed, const bool blocked)
  {
   if(killed || blocked || daily_used >= 100.0 || dd_used >= 100.0 || ExpertSafeModeStopped())
      return(2);
   if(daily_used >= 70.0 || dd_used >= 70.0 || ExpertStopNew() || ExpertSafeModeState() >= 1)
      return(1);
   return(0);
  }

string ExMarketSym(const string kind)
  {
   if(kind == "gold")
     {
      if(SymbolSelect("XAUUSD", false)) return("XAUUSD");
      return("");
     }
   if(kind == "crypto")
     {
      if(SymbolSelect("BTCUSD", false)) return("BTCUSD");
      if(SymbolSelect("ETHUSD", false)) return("ETHUSD");
      return("");
     }
   if(SymbolSelect("EURUSD", false)) return("EURUSD");
   return(_Symbol);
  }

bool ExTickOk(const string sym)
  {
   if(StringLen(sym) == 0) return(false);
   datetime t = (datetime)SymbolInfoInteger(sym, SYMBOL_TIME);
   if(t == 0) return(false);
   return((TimeCurrent() - t) <= 120);
  }

void ExDrawHeaderButtons(const int W, const int H)
  {
   int bs = MathMax(ExPx(22), MathMin(ExPx(32), H - ExPx(8)));
   int ly = (H - bs) / 2;
   int cx = W - ExPx(6) - bs;
   ExBtn3D("collapse", cx, ly, bs, bs, (g_ex_collapsed ? "+" : "-"), EX_CARD, EX_NAVY, EX_GOLD2, false);
   int lx = cx - ExPx(4) - bs;
   string lang = "EN";
   int L = MolidoLangId();
   if(L == LANG_FA) lang = "FA";
   else if(L == LANG_AR) lang = "AR";
   else if(L == LANG_TR) lang = "TR";
   ExBtn3D("lang", lx, ly, bs, bs, lang, EX_CARD, EX_NAVY, EX_GOLD2, false);
  }

int ExHeaderButtonsWidth()
  {
   int bs = MathMax(ExPx(22), ExPx(32));
   return(ExPx(6) + bs + ExPx(4) + bs + ExPx(4));
  }

void ExDrawHeader(const bool ready, const bool linked, const bool blocked, const bool killed)
  {
   ExUse(g_cv_h);
   int W = g_ex_cw, H = g_ly_head;
   g_cv_h.Erase(ExArgb(EX_NAVY, 255));
   ExGradV(0, 0, W - 1, H - 1, EX_NAVY2, EX_BLACK, 255, 255, 0);
   g_cv_h.FillRectangle(0, H - 2, W - 1, H - 1, ExArgb(EX_BLUE, 80));
   g_cv_h.FillRectangle(0, 0, W - 1, 2, ExArgb(EX_GOLD, 180));
   int pad = ExPx(8);
   int right = ExHeaderButtonsWidth();
   string st = ExTr("ready");
   color sc = EX_GREEN;
   bool live = ready;
   if(blocked) { st = ExTr("real"); sc = EX_CORAL; live = false; }
   else if(killed) { st = ExTr("killed"); sc = EX_CORAL; live = false; }
   else if(!ready) { st = ExTr("notready"); sc = EX_AMBER; live = false; }
   if(!ExIsFullUi() || g_ex_collapsed)
     {
      int logo = MathMin(ExPx(36), H - ExPx(8));
      ExLogoM(pad, (H - logo) / 2, logo);
      int tx = pad + logo + ExPx(6);
      ExFont("Segoe UI Bold", g_ex_collapsed ? 11 : 13);
      string title = g_ex_collapsed ? ("Molido  " + MOLIDO_EA_VERSION) : "Molido Expert";
      ExText(tx, g_ex_collapsed ? (H - ExFontSz(11)) / 2 : ExPx(4), title, EX_GOLD2);
      ExFont("Segoe UI Semibold", 8);
      int pw = ExTw(st) + ExPx(20);
      if(g_ex_collapsed)
        {
         int px = tx + ExTw(title) + ExPx(8);
         int py = (H - ExPx(18)) / 2;
         if(px + pw + ExPx(4) < W - right)
           {
            ExPill(px, py, pw, ExPx(18), sc, sc, st, live);
            ExHeartbeat(px + ExPx(8), py + ExPx(9), sc, live);
           }
        }
      else
        {
         ExText(tx, ExPx(20), ExTr("subtitle") + "  v" + MOLIDO_EA_VERSION, EX_BLUE);
         int py = H - ExPx(20);
         if(tx + pw < W - right - ExPx(120))
           {
            ExPill(tx, py, pw, ExPx(16), sc, sc, st, live);
            ExHeartbeat(tx + ExPx(8), py + ExPx(8), sc, live);
           }
        }
      ExDrawHeaderButtons(W, H);
      if(g_ex_collapsed)
         ExHitAdd("expand", 0, 0, MathMax(8, W - right), H);
      return;
     }
   ExLogoM(pad, ExPx(8), ExPx(48));
   ExFont("Segoe UI Bold", 20);
   ExText(pad + ExPx(56), ExPx(6), "Molido Expert", EX_GOLD2);
   ExFont("Segoe UI Semibold", 10);
   ExText(pad + ExPx(56), ExPx(34), ExTr("subtitle"), EX_BLUE);
   ExFont("Segoe UI Semibold", 10);
   int pw = ExTw(st) + ExPx(28);
   int px = pad + ExPx(280);
   if(px + pw > W / 2) px = ExPx(260);
   int py = (H - ExPx(28)) / 2;
   ExPill(px, py, pw, ExPx(28), sc, sc, st, live);
   ExHeartbeat(px + ExPx(10), py + ExPx(14), sc, live);
   ExFont("Segoe UI Semibold", 10);
   string clab = ExTr("core");
   int cx = px + pw + ExPx(16);
   ExText(cx, py + ExPx(6), clab, EX_MUTED);
   int labw = ExTw(clab);
   string stw = linked ? ExTr("online") : ExTr("offline");
   color cc = linked ? EX_GREEN : EX_CORAL;
   ExFont("Segoe UI Bold", 10);
   int sw = ExTw(stw) + ExPx(28);
   int sx0 = cx + labw + ExPx(8);
   ExPill(sx0, py, sw, ExPx(28), cc, cc, stw, linked);
   int bx = sx0 + sw + ExPx(8);
   int sy = py + ExPx(20);
   int bars = (linked ? 4 : 1);
   for(int i = 0; i < 4; i++)
     {
      int bh = ExPx(4 + i * 3);
      uint col = ExArgb(i < bars ? cc : EX_MUTED, i < bars ? 230 : 80);
      g_cv_h.FillRectangle(bx + i * 4, sy - bh, bx + i * 4 + 3, sy, col);
     }
   string ts = TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS);
   ExFont("Segoe UI Semibold", 11);
   int tw = ExTw(ts);
   ExText(W - tw - right, ExPx(8), ts, EX_TEXT);
   ExFont("Segoe UI", 8);
   string up = ExTr("updated") + "  " + TimeToString(g_ex_updated, TIME_SECONDS);
   int uw = ExTw(up);
   ExText(W - uw - right, ExPx(30), up, EX_MUTED);
   ExDrawHeaderButtons(W, H);
  }

void ExDrawLeft(const int strength, const bool linked)
  {
   ExUse(g_cv_l);
   int W = g_ly_left, H = g_ly_hy + g_ly_hh - g_ly_head;
   g_cv_l.Erase(ExArgb(EX_NAVY, 255));
   ExGlowCard(ExPx(6), ExPx(4), W - ExPx(6), H - ExPx(4), ExPx(12), EX_BLUE, (uchar)MathRound(40 + 50 * ExPulse()));
   int row = ExLy(20);
   int strat_h = 6 * row + ExLy(6);
   int news_h = ExLy(16);
   int top_h = H - strat_h - news_h - ExLy(8);
   if(top_h < ExLy(120)) top_h = MathMax(ExLy(96), H - strat_h - ExLy(4));
   int ax = ExPx(14), ay = ExPx(6);
   int aw = W - ExPx(28);
   int ah = MathMin(ExLy(110), (int)MathRound(top_h * 0.42));
   if(ah < ExLy(56)) ah = ExLy(56);
   ExDrawAvatar(ax, ay, aw, ah);
   int y = ay + ah + ExPx(2);
   ExFont("Segoe UI Semibold", 8);
   string hy = ExTr("hybrid");
   int hw = ExTw(hy) + ExPx(28);
   if(hw > W - ExPx(20)) hw = W - ExPx(20);
   int hx = (W - hw) / 2;
   ExRound(hx - 2, y - 2, hx + hw + 2, y + ExPx(20) + 2, ExPx(10), ExArgb(EX_BLUE, (uchar)MathRound(30 + 40 * ExPulse())));
   ExRound(hx, y, hx + hw, y + ExPx(20), ExPx(10), ExArgb(EX_NAVY2, 255));
   g_cv_l.FillCircle(hx + ExPx(12), y + ExPx(10), ExPx(5), ExArgb(EX_BLUE, 220));
   ExText(hx + ExPx(22), y + ExPx(3), hy, EX_TEXT);
   y += ExPx(24);
   int gc = W / 2;
   int gy = y + MathMin(ExLy(34), (top_h - (y - ay)) / 2);
   int rad = MathMin(ExLy(42), MathMin(W / 3, (H - strat_h - y - ExLy(8)) * 2 / 3));
   if(rad < ExLy(22)) rad = ExLy(22);
   ExGaugeSemi(gc, gy, rad, g_gauge_shown, strength);
   // strategies are pinned to the bottom of the left card so they never vanish
   int y0 = H - news_h - strat_h;
   if(y0 < gy + ExLy(16)) y0 = gy + ExLy(16);
   bool sc = StratUseScalper();
   bool tr = StratUseTrend();
   string ids[6] = {"sc","tr","rk","sm","sp2l","fvg"};
   string keys[6] = {"sc","tf","rk","sm","sp2l","fvg"};
   bool ons[6];
   ons[0]=sc; ons[1]=tr; ons[2] = StratUseRocket(); ons[3] = StratUseSmc();
   ons[4]=InpUseSP2LFilter; ons[5]=InpUseFVGFilter;
   bool impl[6];
   impl[0]=true; impl[1]=true; impl[2] = true; impl[3] = true;
   impl[4]=true; impl[5]=true;
   for(int i = 0; i < 6; i++)
     {
      int ry = y0 + i * row;
      if(ry + row > H - ExLy(4)) break;
      ExCheck(ExPx(16), ry, ons[i], impl[i]);
      ExFont("Segoe UI Semibold", 9);
      color fc = (impl[i] ? EX_TEXT : EX_MUTED);
      ExText(ExPx(38), ry, ExTr(keys[i]), fc);
      ExHitAdd(ids[i], ExPx(12), ry, W - ExPx(24), row);
     }
   int ny = y0 + 6 * row;
   if(ny + ExPx(12) < H - ExPx(4))
     {
      ExFont("Segoe UI", 7);
      string news = DemoNextNewsLine();
      if(StringLen(news) > 0)
         ExText(ExPx(14), ny, news, EX_MUTED);
     }
  }

void ExDrawRight(const bool linked)
  {
   ExUse(g_cv_r);
   int W = g_ly_right;
   int H = g_ly_hy + g_ly_hh - g_ly_head;
   g_cv_r.Erase(ExArgb(EX_NAVY, 255));
   ExGlowCard(ExPx(4), ExPx(4), W - ExPx(6), H - ExPx(4), ExPx(12), EX_BLUE, (uchar)MathRound(50 + 60 * ExPulse()));
   int pad = ExPx(10);
   int gap = ExPx(6);
   int title_h = ExPx(30);
   int tfs = 16;
   ExFont("Segoe UI Bold", tfs);
   string title = ExTr("council");
   while(tfs > 10 && ExTw(title) > W - ExPx(24))
     { tfs--; ExFont("Segoe UI Bold", tfs); }
   int tw = ExTw(title);
   int tx = (W - tw) / 2;
   if(tx < pad) tx = pad;
   ExText(tx, ExPx(8), title, EX_GOLD2);
   g_cv_r.FillCircle(tx - ExPx(10), ExPx(18), 3, ExArgb(EX_GOLD, 200));
   int avail_h = H - title_h - pad;
   int btn_h = (avail_h - 3 * gap) / 4;
   if(btn_h < ExPx(24)) btn_h = ExPx(24);
   if(btn_h > ExPx(40)) btn_h = ExPx(40);
   int brain_d = MathMin(ExPx(130), MathMin(avail_h - ExPx(8), W / 3));
   if(brain_d < ExPx(90)) brain_d = ExPx(90);
   int btn_w = W / 2 - brain_d / 2 - pad - gap;
   if(btn_w < ExPx(78))
     {
      brain_d = MathMax(ExPx(80), W - 2 * (ExPx(78) + pad + gap));
      btn_w = W / 2 - brain_d / 2 - pad - gap;
     }
   if(btn_w < ExPx(70)) btn_w = ExPx(70);
   int col0 = pad;
   int col1 = W - pad - btn_w;
   int top = title_h;
   int cx = W / 2;
   int cy = title_h + avail_h / 2;
   int R = brain_d / 2 - ExPx(18);
   if(R < ExPx(28)) R = ExPx(28);
   int on = (linked ? g_ai_agents_on : 0);
   int tot = (g_ai_agents_total > 0 ? g_ai_agents_total : 51);
   if(tot > 51) tot = 51;
   double p = ExPulse();
   g_cv_r.FillCircle(cx, cy, R + 16, ExArgb(EX_BLUE, (uchar)MathRound(20 + 30 * p)));
   g_cv_r.FillCircle(cx, cy, R + 8, ExArgb(EX_BLUE, (uchar)MathRound(40 + 50 * p)));
   g_cv_r.FillCircle(cx, cy, R, ExArgb(EX_NAVY, 255));
   g_cv_r.FillCircle(cx - R / 3, cy - 2, R / 2, ExArgb(EX_BLUE, (uchar)MathRound(70 + 50 * p)));
   g_cv_r.FillCircle(cx + R / 3, cy - 2, R / 2, ExArgb(EX_BLUE, (uchar)MathRound(70 + 50 * p)));
   g_cv_r.FillCircle(cx, cy + R / 5, R / 3, ExArgb(EX_BLUE2, 180));
   int dots = 51;
   int ring = R + ExPx(16);
   for(int i = 0; i < dots; i++)
     {
      double a = -MathArctan(1.0)*2.0 + i * (MathArctan(1.0)*8.0 / dots);
      int dx = cx + (int)MathRound(ring * MathCos(a));
      int dy = cy + (int)MathRound(ring * MathSin(a));
      bool lit = (linked && i < on);
      color dc = (lit ? EX_GREEN : EX_LINE);
      g_cv_r.FillCircle(dx, dy, 2, ExArgb(dc, lit ? 230 : 100));
     }
   string num = (linked ? IntegerToString(on) + " / " + IntegerToString(tot) : ExTr("dash"));
   ExFont("Segoe UI Bold", 16);
   int nw = ExTw(num);
   ExText(cx - nw / 2, cy - ExFontSz(8), num, EX_TEXT);
   ExFont("Segoe UI", 8);
   string al = linked ? ExTr("agents") : ExTr("disc");
   int alw = ExTw(al);
   ExText(cx - alw / 2, cy + ExPx(12), al, linked ? EX_MUTED : EX_CORAL);
   string gk[8] = {"g0","g1","g2","g3","g4","g5","g6","g7"};
   int order_l[4] = {0,2,4,6};
   int order_r[4] = {1,3,5,7};
   int gmap[8] = {0,5,7,6,1,8,9,10};
   for(int i = 0; i < 4; i++)
     {
      int ly = top + i * (btn_h + gap);
      int idl = order_l[i], idr = order_r[i];
      int sl = gmap[idl], sr = gmap[idr];
      bool ok_l = (linked && sl < 11 && StringLen(g_ai_group_st[sl]) > 0 && StringFind(g_ai_group_st[sl], "Disconnected") < 0);
      bool ok_r = (linked && sr < 11 && StringLen(g_ai_group_st[sr]) > 0 && StringFind(g_ai_group_st[sr], "Disconnected") < 0);
      color c1l = ok_l ? EX_BLUE : EX_CARD;
      color c1r = ok_r ? EX_BLUE : EX_CARD;
      ExBtn3D("ag" + IntegerToString(idl), col0, ly, btn_w, btn_h, ExTr(gk[idl]), c1l, EX_NAVY, EX_TEXT, false);
      ExBtn3D("ag" + IntegerToString(idr), col1, ly, btn_w, btn_h, ExTr(gk[idr]), c1r, EX_NAVY, EX_TEXT, false);
     }
  }


void ExDrawHud()
  {
   ExUse(g_cv_hud);
   int W = ExPx(280), H = ExPx(28);
   // actual canvas size may be smaller — use object width if possible
   g_cv_hud.Erase(ExArgb(EX_NAVY, 255));
   ExRound(0, 0, W - 1, H - 1, ExPx(6), ExArgb(EX_NAVY, 200));
   ExFont("Segoe UI Bold", 9);
   ExText(ExPx(6), ExPx(6), _Symbol, EX_GOLD2);
   int x = ExPx(6) + ExTw(_Symbol) + ExPx(8);
   string labs[9] = {"M1","M5","M15","M30","H1","H4","D1","W1","MN"};
   ENUM_TIMEFRAMES tfs[9] = {PERIOD_M1,PERIOD_M5,PERIOD_M15,PERIOD_M30,PERIOD_H1,PERIOD_H4,PERIOD_D1,PERIOD_W1,PERIOD_MN1};
   ENUM_TIMEFRAMES cur = (ENUM_TIMEFRAMES)Period();
   int bw = ExPx(22), bh = ExPx(18);
   for(int i = 0; i < 9; i++)
     {
      bool on = (cur == tfs[i]);
      if(x + bw > W - 2) break;
      ExBtn3D("tf" + labs[i], x, ExPx(4), bw, bh, labs[i],
              on ? EX_BLUE : EX_CARD, EX_NAVY, on ? EX_NAVY : EX_TEXT, false);
      x += bw + 2;
     }
  }

void ExDrawTag()
  {
   ExUse(g_cv_tag);
   int W = ExPx(86), H = ExPx(40);
   g_cv_tag.Erase(ExArgb(EX_NAVY, 255));
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   bool ok = (ask > 0.0);
   ExRound(0, 0, W - 1, H - 1, ExPx(6), ExArgb(EX_GREEN, 40));
   ExRound(1, 1, W - 2, H - 2, ExPx(6), ExArgb(EX_NAVY, 235));
   ExFont("Segoe UI Bold", 8);
   ExText(ExPx(6), ExPx(2), "BUY", EX_GREEN);
   ExFont("Segoe UI Bold", 11);
   ExText(ExPx(6), ExPx(16), ok ? ExPriceStr(ask) : ExTr("dash"), EX_TEXT);
  }

void ExDrawMid()
  {
   ExUse(g_cv_m);
   int W = g_ex_cw, H = g_ly_mid;
   g_cv_m.Erase(ExArgb(EX_NAVY, 255));
   ExGradV(0, 0, W - 1, H - 1, EX_NAVY, EX_BLACK, 255, 255, 0);
   int pad = ExPx(8);
   int gap = ExPx(6);
   int y = ExPx(6);
   int h = H - ExPx(12);
   if(h < ExPx(40)) h = ExPx(40);
   if(!ExIsFullUi() || W < 720)
     {
      if(gap > ExPx(4)) gap = ExPx(4);
      int row_h = (h - gap) / 2;
      if(row_h < ExPx(26)) row_h = ExPx(26);
      int x = pad;
      int bw = (W - 2 * pad - 3 * gap) / 4;
      ExBtn3D("buy", x, y, bw, row_h, ExTr("buy") + "  BUY", EX_GREEN, EX_GREEN2, EX_TEXT, false);
      x += bw + gap;
      ExBtn3D("sell", x, y, bw, row_h, ExTr("sell") + "  SELL", EX_CORAL, EX_RED, EX_TEXT, true);
      x += bw + gap;
      ExBtn3D("close", x, y, bw, row_h, ExTr("close"), EX_CARD, EX_NAVY2, EX_TEXT, false);
      x += bw + gap;
      int last = W - pad - x;
      ExBtn3D("closeall", x, y, last, row_h, ExTr("closeall"), EX_CARD, EX_NAVY2, EX_MUTED, false);
      int y2 = y + row_h + gap;
      int sw = (W - 2 * pad - 2 * gap) / 3;
      x = pad;
      ExStepper("lot", x, y2, sw, row_h, ExTr("lot"), DoubleToString(g_ex_lot, 2));
      x += sw + gap;
      ExStepper("sl", x, y2, sw, row_h, ExTr("sl"), ExSlPreview());
      x += sw + gap;
      int last2 = W - pad - x;
      ExStepper("tp", x, y2, last2, row_h, ExTr("tp"), ExTpPreview());
      return;
     }
   // 7 equal-row cells: BUY, SELL, lot, SL, TP, close, close-all
   double units = 1.25 + 1.25 + 1.05 + 1.05 + 1.05 + 1.0 + 1.0;
   int avail = W - 2 * pad - 6 * gap;
   if(avail < ExPx(400)) avail = W - 2 * pad - 6 * ExPx(4);
   double unit = (double)avail / units;
   int bw = (int)MathRound(unit * 1.25);
   int sw = (int)MathRound(unit * 1.05);
   int cw = (int)MathRound(unit * 1.0);
   int x = pad;
   ExBtn3D("buy", x, y, bw, h, ExTr("buy") + "  BUY", EX_GREEN, EX_GREEN2, EX_TEXT, false);
   x += bw + gap;
   ExBtn3D("sell", x, y, bw, h, ExTr("sell") + "  SELL", EX_CORAL, EX_RED, EX_TEXT, true);
   x += bw + gap;
   ExStepper("lot", x, y, sw, h, ExTr("lot"), DoubleToString(g_ex_lot, 2));
   x += sw + gap;
   ExStepper("sl", x, y, sw, h, ExTr("sl"), ExSlPreview());
   x += sw + gap;
   ExStepper("tp", x, y, sw, h, ExTr("tp"), ExTpPreview());
   x += sw + gap;
   ExBtn3D("close", x, y, cw, h, ExTr("close"), EX_CARD, EX_NAVY2, EX_TEXT, false);
   x += cw + gap;
   int last = W - pad - x;
   if(last < ExPx(70)) last = cw;
   ExBtn3D("closeall", x, y, last, h, ExTr("closeall"), EX_CARD, EX_NAVY2, EX_MUTED, false);
  }

void ExDrawBotTrade(const ExpertPerf &perf, const ExpertReport &rep,
                    const double daily_used, const double dd_used,
                    const bool killed, const bool blocked)
  {
   ExUse(g_cv_b);
   int W = g_ex_cw, H = g_ly_bot;
   g_cv_b.Erase(ExArgb(EX_NAVY, 255));
   int pad = ExPx(8);
   int gap = ExPx(6);
   int y = ExPx(6);
   bool compact = (!ExIsFullUi() || W < 800);
   int ch = H - ExPx(12);
   int cw = (W - 2 * pad - 3 * gap) / 4;
   if(compact)
     {
      if(gap > ExPx(4)) gap = ExPx(4);
      cw = (W - 2 * pad - gap) / 2;
      ch = (H - ExPx(12) - gap) / 2;
      if(ch < ExPx(70)) ch = ExPx(70);
     }
   int x = pad;
   int y0 = y;
   // RISK
   ExGlowCard(x, y, x + cw, y + ch, ExPx(10), EX_GREEN, 60);
   ExLockIcon(x + ExPx(16), y + ExPx(18), EX_GOLD);
   ExFont("Segoe UI Bold", 14);
   ExText(x + ExPx(30), y + ExPx(8), ExTr("risk"), EX_GOLD2);
   int level = ExRiskLevel(daily_used, dd_used, killed, blocked);
   ExSafeBadge(x + cw - ExPx(40), y + ExPx(14), ExPx(22), level);
   ExFont("Segoe UI", 8);
   int ly = y + ExPx(32);
   int row = (ch - ExPx(40)) / 4;
   if(row < ExPx(14)) row = ExPx(14);
   string r1 = ExTr("r_trade") + "   " + DoubleToString(DemoActiveRiskPct(), 2) + "%";
   string r2 = ExTr("r_daily") + "   " + DoubleToString(DemoActiveDailyPct(), 2) + "%";
   string r3 = ExTr("r_dd") + "   " + (DemoActiveMaxDdPct() > 0 ? DoubleToString(DemoActiveMaxDdPct(), 2) + "%" : ExTr("dash"));
   int sm = ExpertSafeModeState();
   int losses = ExpertTodayLossStreak();
   string rsm;
   color csm = EX_GREEN;
   if(sm == 2)
     {
      rsm = ExTr("safemode") + "  " + ExTr("sm_stop") + "  " +
            TimeToString(ExpertSafeModeClearsAt(), TIME_DATE | TIME_MINUTES);
      csm = EX_CORAL;
     }
   else if(sm == 1)
     {
      rsm = ExTr("safemode") + "  " + ExTr("sm_reduce") + "  " + IntegerToString(losses);
      csm = EX_AMBER;
     }
   else if(losses > 0)
     {
      rsm = ExTr("safemode") + "  " + IntegerToString(losses) + "  " + ExTr("sm_today");
      csm = EX_AMBER;
     }
   else
      rsm = ExTr("safemode") + "  " + ExTr("sm_off");
   string r4 = ExTr("r_open") + "   " + IntegerToString(rep.open_count) + " / " + IntegerToString(DemoActiveMaxPositions());
   int row5 = (ch - ExPx(40)) / 5;
   if(row5 < ExPx(12)) row5 = ExPx(12);
   row = row5;
   ExFont("Segoe UI", 8);
   ExText(x + ExPx(12), ly, r1, EX_TEXT); ly += row;
   ExText(x + ExPx(12), ly, r2, EX_TEXT); ly += row;
   ExText(x + ExPx(12), ly, r3, EX_TEXT); ly += row;
   ExText(x + ExPx(12), ly, r4, EX_TEXT); ly += row;
   ExText(x + ExPx(12), ly, rsm, csm);
   // PERF
   x += cw + gap;
   ExGlowCard(x, y, x + cw, y + ch, ExPx(10), EX_BLUE, 55);
   ExFont("Segoe UI Bold", 14);
   ExText(x + ExPx(12), y + ExPx(8), ExTr("perf"), EX_GOLD2);
   ExPerfBars(x + ExPx(10), y + ExPx(32), cw / 2 - ExPx(16), ch - ExPx(44));
   int tx = x + cw / 2;
   ExFont("Segoe UI", 8);
   ExText(tx, y + ExPx(32), ExTr("today"), EX_MUTED);
   ExFont("Segoe UI Bold", 12);
   string tv;
   if(!perf.has_data && rep.today_trades == 0 && rep.history_trades == 0)
      tv = ExTr("nodata");
   else
      tv = IntegerToString(rep.today_trades);
   ExText(tx, y + ExPx(46), tv, EX_TEXT);
   ExFont("Segoe UI", 8);
   ExText(tx, y + ExPx(66), ExTr("win"), EX_MUTED);
   ExFont("Segoe UI Bold", 12);
   string wv = perf.has_data ? DoubleToString(perf.winpct, 1) + "%" : ExTr("nodata");
   ExText(tx, y + ExPx(80), wv, EX_TEXT);
   ExFont("Segoe UI", 8);
   ExText(tx, y + ExPx(100), ExTr("net"), EX_MUTED);
   ExFont("Segoe UI Bold", 11);
   string nv = perf.has_data ? ExpertMoney(perf.pnl) : ExTr("nodata");
   ExText(tx, y + ExPx(112), nv, perf.has_data && perf.pnl < 0 ? EX_CORAL : EX_GREEN);
   // MARKETS
   if(compact)
     { x = pad; y = y0 + ch + gap; }
   else
      x += cw + gap;
   ExGlowCard(x, y, x + cw, y + ch, ExPx(10), EX_BLUE, 55);
   ExFont("Segoe UI Bold", 14);
   ExText(x + ExPx(12), y + ExPx(8), ExTr("markets"), EX_GOLD2);
   string kinds[3] = {"forex","gold","crypto"};
   string labs[3];
   labs[0] = ExTr("forex");
   string gs = ExMarketSym("gold");
   if(StringLen(gs) > 0) labs[1] = ExTr("gold") + " (" + gs + ")";
   else labs[1] = ExTr("gold");
   labs[2] = "Crypto";
   int mrow = (ch - ExPx(36)) / 3;
   for(int i = 0; i < 3; i++)
     {
      int ry = y + ExPx(32) + i * mrow;
      string sym = ExMarketSym(kinds[i]);
      bool ok = (StringLen(sym) > 0);
      bool m_live = ok && ExTickOk(sym);
      string st = (!ok ? ExTr("nodata") : (m_live ? ExTr("active") : ExTr("closed")));
      color sc = (!ok ? EX_AMBER : (m_live ? EX_GREEN : EX_MUTED));
      ExFont("Segoe UI Semibold", 9);
      ExText(x + ExPx(12), ry, labs[i], EX_TEXT);
      ExFont("Segoe UI", 8);
      ExText(x + ExPx(12), ry + ExPx(12), st, sc);
      if(ok)
         ExSpark(x + cw - ExPx(70), ry, ExPx(56), ExPx(22), sym);
     }
   // EMERGENCY STOP — fixed rightmost cell of the 4-column grid (or 2x2 in compact)
   x += cw + gap;
   int kx = x;
   int kill_w = compact ? cw : (W - pad - kx);
   ExRound(kx - 3, y - 2, kx + kill_w + 2, y + ch + 2, ExPx(10), ExArgb(EX_CORAL, (uchar)MathRound(50 + 60 * ExPulse())));
   ExBtn3D("kill", kx, y, kill_w, ch, ExTr("kill") + "\n" + ExTr("killsub"), EX_CORAL, EX_RED, EX_TEXT, true);
  }

void ExDrawBotReport(const ExpertPerf &perf, const ExpertReport &rep)
  {
   ExUse(g_cv_b);
   int W = g_ex_cw, H = g_ly_bot;
   g_cv_b.Erase(ExArgb(EX_NAVY, 255));
   ExGlowCard(ExPx(8), ExPx(4), W - ExPx(8), H - ExPx(4), ExPx(10), EX_BLUE, 50);
   ExFont("Segoe UI Bold", 12);
   ExText(ExPx(18), ExPx(10), ExTr("tab3"), EX_GOLD2);
   int y = ExPx(32);
   int col = ExPx(260);
   if(col > W / 2) col = W / 2;
   ExFont("Segoe UI", 9);
   ExText(ExPx(18), y, ExTr("today") + "  " + IntegerToString(rep.today_trades) + "   " + (rep.today_trades==0 && !perf.has_data ? ExTr("nodata") : ExpertMoney(rep.today_pnl)), EX_TEXT);
   y += ExPx(18);
   ExText(ExPx(18), y, (MolidoLangId()==LANG_FA?"موجودی  ":"Balance  ") + DoubleToString(rep.balance, 2), EX_TEXT);
   y += ExPx(18);
   ExText(ExPx(18), y, (MolidoLangId()==LANG_FA?"دارایی  ":"Equity  ") + DoubleToString(rep.equity, 2), EX_TEXT);
   y += ExPx(18);
   ExText(ExPx(18), y, (MolidoLangId()==LANG_FA?"مارجین آزاد  ":"Free margin  ") + DoubleToString(rep.free_margin, 2), EX_TEXT);
   int x2 = col;
   y = ExPx(32);
   ExText(x2, y, (MolidoLangId()==LANG_FA?"هفته  ":"Week  ") + (perf.has_data || rep.week_pnl != 0 ? ExpertMoney(rep.week_pnl) : ExTr("nodata")), EX_TEXT);
   y += ExPx(18);
   ExText(x2, y, (MolidoLangId()==LANG_FA?"ماه  ":"Month  ") + (perf.has_data || rep.month_pnl != 0 ? ExpertMoney(rep.month_pnl) : ExTr("nodata")), EX_TEXT);
   y += ExPx(18);
   ExText(x2, y, (MolidoLangId()==LANG_FA?"باز  ":"Open  ") + IntegerToString(rep.open_count), EX_TEXT);
   y += ExPx(18);
   ExText(x2, y, perf.has_data ? ("P/L  " + ExpertMoney(perf.pnl) + "   win " + DoubleToString(perf.winpct, 1) + "%") : ExTr("nodata"), EX_TEXT);
  }

void ExDrawBotSignals(const int strength)
  {
   ExUse(g_cv_b);
   int W = g_ex_cw, H = g_ly_bot;
   g_cv_b.Erase(ExArgb(EX_NAVY, 255));
   ExGlowCard(ExPx(8), ExPx(4), W - ExPx(8), H - ExPx(4), ExPx(10), EX_BLUE, 50);
   ExFont("Segoe UI Bold", 12);
   ExText(ExPx(18), ExPx(10), ExTr("tab2"), EX_GOLD2);
   ExFont("Segoe UI", 9);
   int y = ExPx(36);
   ExText(ExPx(18), y, ExTr("sigpwr") + "  " + IntegerToString(strength), EX_TEXT);
   y += ExPx(18);
   if(g_ex_last_entry > 0.0 && StringLen(g_ex_last_side) > 0)
     {
      ExText(ExPx(18), y, g_ex_last_side + "  " + ExPriceStr(g_ex_last_entry)
             + "   SL " + ExPriceStr(g_ex_last_sl) + "   TP " + ExPriceStr(g_ex_last_tp), EX_TEXT);
      y += ExPx(18);
     }
   else
     {
      ExText(ExPx(18), y, ExTr("nodata"), EX_AMBER);
      y += ExPx(18);
     }
   if(StringLen(g_ex_last_msg) > 0)
      ExText(ExPx(18), y, g_ex_last_msg, EX_AMBER);
  }

void ExDrawBotSettings()
  {
   ExUse(g_cv_b);
   int W = g_ex_cw, H = g_ly_bot;
   g_cv_b.Erase(ExArgb(EX_NAVY, 255));
   ExGlowCard(ExPx(8), ExPx(4), W - ExPx(8), H - ExPx(4), ExPx(10), EX_BLUE, 50);
   ExFont("Segoe UI Bold", 12);
   ExText(ExPx(18), ExPx(10), ExTr("tab4"), EX_GOLD2);
   int y = ExPx(36);
   int bw = ExPx(120), bh = ExPx(28);
   bool auto_on = ExpertAutoOn();
   bool stop = ExpertStopNew();
   ExBtn3D("auto", ExPx(18), y, bw, bh, ExTr("auto") + " " + (auto_on ? ExTr("on") : ExTr("off")),
           auto_on ? EX_BLUE : EX_CARD, EX_NAVY, auto_on ? EX_TEXT : EX_MUTED, false);
   ExBtn3D("stop", ExPx(18) + bw + ExPx(8), y, bw + ExPx(20), bh, ExTr("stopnew"),
           stop ? EX_CORAL : EX_CARD, EX_NAVY, stop ? EX_TEXT : EX_MUTED, stop);
   y += bh + ExPx(10);
   ExFont("Segoe UI", 9);
   ExText(ExPx(18), y, "Risk%  " + DoubleToString(g_ex_risk_ui, 2)
          + "    Max  " + IntegerToString(g_ex_max_pos)
          + "    Lot  " + DoubleToString(g_ex_lot, 2), EX_TEXT);
   y += ExPx(18);
   ExText(ExPx(18), y, "Smart TP/SL  " + (g_ex_smart_sl ? ExTr("on") : ExTr("off"))
          + "    " + ExTr("about1"), EX_MUTED);
   y += ExPx(18);
   ExText(ExPx(18), y, ExTr("sp2l") + "  " + (InpUseSP2LFilter ? ExTr("on") : ExTr("off"))
          + "    " + ExTr("fvg") + "  " + (InpUseFVGFilter ? ExTr("on") : ExTr("off")),
          EX_TEXT);
  }

void ExDrawBotAbout()
  {
   ExUse(g_cv_b);
   int W = g_ex_cw, H = g_ly_bot;
   g_cv_b.Erase(ExArgb(EX_NAVY, 255));
   ExGlowCard(ExPx(8), ExPx(4), W - ExPx(8), H - ExPx(4), ExPx(10), EX_GOLD, 40);
   ExFont("Segoe UI Bold", 13);
   ExText(ExPx(18), ExPx(12), "Molido Expert  " + MOLIDO_EA_VERSION, EX_GOLD2);
   ExFont("Segoe UI", 9);
   ExText(ExPx(18), ExPx(36), ExTr("subtitle") + "    v" + MOLIDO_EA_VERSION + "    magic " + IntegerToString((int)MOLIDO_MAGIC), EX_TEXT);
   ExText(ExPx(18), ExPx(54), ExTr("about1"), EX_AMBER);
   ExText(ExPx(18), ExPx(72), ExTr("updated") + "  " + TimeToString(g_ex_updated, TIME_DATE | TIME_SECONDS), EX_MUTED);
  }

void ExDrawTabs()
  {
   ExUse(g_cv_t);
   int W = g_ex_cw, H = g_ly_tab;
   g_cv_t.Erase(ExArgb(EX_NAVY, 255));
   ExGradV(0, 0, W - 1, H - 1, EX_NAVY2, EX_BLACK, 255, 255, 0);
   g_cv_t.FillRectangle(0, 0, W - 1, 2, ExArgb(EX_GOLD, 120));
   int n = 6;
   int pad = ExPx(8);
   int gap = ExPx(6);
   int bw = (W - pad * 2 - gap * (n - 1)) / n;
   int bh = H - ExPx(10);
   if(bh < ExPx(28)) bh = ExPx(28);
   string keys[6] = {"tab0","tab1","tab2","tab3","tab4","tab5"};
   for(int i = 0; i < n; i++)
     {
      int x = pad + i * (bw + gap);
      bool on = (g_ex_tab == i);
      ExBtn3D("tab" + IntegerToString(i), x, ExPx(5), bw, bh, ExTr(keys[i]),
              on ? EX_BLUE : EX_CARD, EX_NAVY, on ? EX_GOLD2 : EX_MUTED, false);
     }
  }

//+------------------------------------------------------------------+
//| Compact panel: strict-grid renderer on ONE opaque canvas          |
//| 6 equal columns, equal pad/gap, RTL-aware label/value columns     |
//+------------------------------------------------------------------+
bool CxRtl() { int L = MolidoLangId(); return(L == LANG_FA || L == LANG_AR); }
int  CxTh()  { return(g_dc == NULL ? 12 : g_dc.TextHeight("Ag")); }
int  CxSpan(const int n) { return(n * g_cx_colw + (n - 1) * g_cx_pad); }

int CxX(const int col, const int sp, const bool mirror)
  {
   int off = col * (g_cx_colw + g_cx_pad);
   int w = CxSpan(sp);
   if(mirror && CxRtl())
      return(g_ex_cw - g_cx_pad - off - w);
   return(g_cx_pad + off);
  }

void CxFit(string &s, const int maxw)
  {
   if(maxw <= 0) { s = ""; return; }
   if(ExTw(s) <= maxw) return;
   string t = s;
   while(StringLen(t) > 1)
     {
      t = StringSubstr(t, 0, StringLen(t) - 1);
      if(ExTw(t + "...") <= maxw) { s = t + "..."; return; }
     }
   s = t;
  }

// align: -1 left, 0 center, 1 right. Text is vertically centred in the box and never exceeds w.
void CxTxt(const int x, const int y, const int w, const int h, const string text,
           const color c, const int base, const bool bold, const int align)
  {
   if(w <= 0) return;
   string face = (bold ? "Segoe UI Bold" : "Segoe UI");
   int fs = base + 1;
   ExFont(face, fs);
   while(ExFontSz(fs) > 11 && ExTw(text) > w) { fs--; ExFont(face, fs); }
   string s = text;
   CxFit(s, w);
   int tw = ExTw(s);
   int tx = (align < 0 ? x : (align > 0 ? x + w - tw : x + (w - tw) / 2));
   int ty = y + (h - CxTh()) / 2;
   ExText(tx, ty, s, c);
  }

// label + value in two columns; RTL: label on the right, value on the left
void CxKV(const int x, const int y, const int w, const int h, const string label,
          const string value, const color vc, const bool line = true)
  {
   bool rtl = CxRtl();
   int gp = g_cx_pad / 2 + 2;
   ExFont("Segoe UI Bold", 15);
   int vw = ExTw(value);
   ExFont("Segoe UI", 14);
   int lw = ExTw(label);
   int vmax = MathMax(w / 2, w - lw - gp);
   if(vw > vmax) vw = vmax;
   int lmax = w - vw - gp;
   if(rtl)
     {
      CxTxt(x + w - lmax, y, lmax, h, label, CX_LBL, 13, false, 1);
      CxTxt(x, y, vw, h, value, vc, 14, true, -1);
     }
   else
     {
      CxTxt(x, y, lmax, h, label, CX_LBL, 13, false, -1);
      CxTxt(x + w - vw, y, vw, h, value, vc, 14, true, 1);
     }
   if(line)
      g_dc.FillRectangle(x, y + h - 1, x + w - 1, y + h - 1, ExArgb(EX_LINE, 150));
  }

void CxKV2(const int x, const int y, const int w, const int h,
           const string l1, const string v1, const color c1,
           const string l2, const string v2, const color c2, const bool line = true)
  {
   int cw = (w - g_cx_pad) / 2;
   int xa = (CxRtl() ? x + w - cw : x);
   int xb = (CxRtl() ? x : x + w - cw);
   CxKV(xa, y, cw, h, l1, v1, c1, line);
   CxKV(xb, y, cw, h, l2, v2, c2, line);
  }

//--- anti-aliased rounded rect on an opaque canvas (blends against what is already drawn)
void CxPx(const int x, const int y, const color c, const double cov)
  {
   if(x < 0 || y < 0 || x >= g_ex_cw || y >= g_ex_ch || cov <= 0.02) return;
   uint cc = ((uint)c & 0xFF) << 16 | (((uint)c >> 8) & 0xFF) << 8 | (((uint)c >> 16) & 0xFF);
   if(cov >= 0.98) { g_dc.PixelSet(x, y, 0xFF000000 | cc); return; }
   uint d = g_dc.PixelGet(x, y);
   double dr = (double)((d >> 16) & 0xFF), dg = (double)((d >> 8) & 0xFF), db = (double)(d & 0xFF);
   double cr = (double)((cc >> 16) & 0xFF), cg = (double)((cc >> 8) & 0xFF), cb = (double)(cc & 0xFF);
   uint ro = (uint)MathRound(dr + (cr - dr) * cov);
   uint go = (uint)MathRound(dg + (cg - dg) * cov);
   uint bo = (uint)MathRound(db + (cb - db) * cov);
   g_dc.PixelSet(x, y, 0xFF000000 | (ro << 16) | (go << 8) | bo);
  }

void CxRRg(const int x1, const int y1, const int x2, const int y2, const int r0, const color c1, const color c2)
  {
   int h = y2 - y1 + 1, w = x2 - x1 + 1;
   if(h <= 0 || w <= 0) return;
   int r = r0;
   if(r * 2 > h) r = h / 2;
   if(r * 2 > w) r = w / 2;
   for(int row = 0; row < h; row++)
     {
      double t = (h > 1 ? (double)row / (double)(h - 1) : 0.0);
      color c = ExLerp(c1, c2, t);
      double inset = 0.0;
      if(r > 0 && (row < r || row >= h - r))
        {
         double yc = (row < r ? row + 0.5 : (h - row) - 0.5);
         double dv = r - yc;
         inset = r - MathSqrt(MathMax(0.0, (double)r * r - dv * dv));
        }
      double xl = x1 + inset;
      double xr = x2 + 1 - inset;
      int pl = (int)MathFloor(xl);
      int pr = (int)MathFloor(xr);
      int y = y1 + row;
      CxPx(pl, y, c, 1.0 - (xl - pl));
      if(pr - 1 >= pl + 1)
         g_dc.FillRectangle(pl + 1, y, pr - 1, y, ExArgb(c, 255));
      CxPx(pr, y, c, xr - pr);
     }
  }

string CxNoDot(const string s)
  {
   int n = StringLen(s);
   if(n > 0 && StringGetCharacter(s, n - 1) == '.') return(StringSubstr(s, 0, n - 1));
   return(s);
  }

void CxHair(const int y)
  {
   g_dc.FillRectangle(g_cx_pad, y, g_ex_cw - 1 - g_cx_pad, y, ExArgb(EX_LINE, 170));
  }

int CxCardHdr() { return(g_cx_pad / 2 + CP(22) + 3); }

void CxCard(const int x, const int y, const int w, const int h, const string title, const color accent)
  {
   int r = CP(8);
   color bd = ExLerp(EX_NAVY, accent, 0.8);
   CxRRg(x, y, x + w - 1, y + h - 1, r, bd, bd);
   CxRRg(x + 1, y + 1, x + w - 2, y + h - 2, r - 1, EX_NAVY2, EX_BLACK);
   if(StringLen(title) > 0)
     {
      int ip = g_cx_pad;
      int th = CP(22);
      CxTxt(x + ip, y + ip / 2, w - 2 * ip, th, title, EX_GOLD2, 15, true, CxRtl() ? 1 : -1);
      g_dc.FillRectangle(x + ip, y + ip / 2 + th + 1, x + w - 1 - ip, y + ip / 2 + th + 1, ExArgb(EX_LINE, 255));
     }
  }

void CxBtn(const string id, const int x, const int y, const int w, const int h, const string cap,
           const color c1, const color c2, const color fg, const bool danger, const int fs = 13)
  {
   bool hover = (g_hover == id);
   bool press = (g_pressed == id);
   int r = CP(6);
   bool plain = (c1 == EX_CARD || c1 == EX_NAVY2);
   color bd = (hover || press ? (danger ? EX_CORAL : EX_BLUE) : (plain ? CX_BD : ExLerp(c2, EX_BLACK, 0.35)));
   CxRRg(x, y, x + w - 1, y + h - 1, r, bd, bd);
   if(press)
      CxRRg(x + 1, y + 1, x + w - 2, y + h - 2, r - 1, c2, c1);
   else
      CxRRg(x + 1, y + 1, x + w - 2, y + h - 2, r - 1, c1, c2);
   if(!press)
      g_dc.FillRectangle(x + r, y + 1, x + w - 1 - r, y + 1, ExArgb(ExLerp(c1, EX_TEXT, 0.22), 255));
   CxTxt(x + 2, y + (press ? 1 : 0), w - 4, h, cap, fg, fs, true, 0);
   ExHitAdd(id, x, y, w, h);
  }

void CxPill(const int x, const int y, const int w, const int h, const color c, const string text, const bool live)
  {
   int r = h / 2;
   CxRRg(x, y, x + w - 1, y + h - 1, r, ExLerp(EX_NAVY, c, 0.6), ExLerp(EX_NAVY, c, 0.6));
   CxRRg(x + 1, y + 1, x + w - 2, y + h - 2, r - 1, EX_NAVY2, EX_NAVY2);
   bool rtl = CxRtl();
   int ip = g_cx_pad;
   int rad = CP(3) + (live && ExPulse() > 0.6 ? 1 : 0);
   int dcx = (rtl ? x + w - ip - rad : x + ip + rad);
   g_dc.FillCircle(dcx, y + h / 2, rad, ExArgb(c, 255));
   int tpad = ip + rad * 2 + g_cx_pad / 2;
   int tx = (rtl ? x + g_cx_pad / 2 : x + tpad);
   CxTxt(tx, y, w - tpad - g_cx_pad / 2, h, text, c, 13, true, rtl ? 1 : -1);
  }

void CxChip(const string id, const int x, const int y, const int w, const int h,
            const string label, const bool on, const bool impl)
  {
   bool hover = (g_hover == id);
   color bc = (impl && on ? EX_GREEN : EX_LINE);
   int r = CP(6);
   color cb = (hover ? EX_BLUE : ExLerp(EX_NAVY, bc, 0.7));
   CxRRg(x, y, x + w - 1, y + h - 1, r, cb, cb);
   color cf = (impl && on ? ExLerp(EX_NAVY, EX_GREEN, 0.14) : EX_NAVY2);
   CxRRg(x + 1, y + 1, x + w - 2, y + h - 2, r - 1, cf, cf);
   bool rtl = CxRtl();
   int ip = g_cx_pad - 2;
   int s = CP(14);
   int ix = (rtl ? x + w - ip - s : x + ip);
   int iy = y + (h - s) / 2;
   color ic = (!impl ? CX_LBL : (on ? EX_GREEN : EX_LINE));
   CxRRg(ix, iy, ix + s - 1, iy + s - 1, 3, ic, ic);
   if(impl && on)
     {
      g_dc.Line(ix + 3, iy + s / 2, ix + s / 2 - 1, iy + s - 4, ExArgb(EX_NAVY, 255));
      g_dc.Line(ix + 3, iy + s / 2 + 1, ix + s / 2 - 1, iy + s - 3, ExArgb(EX_NAVY, 255));
      g_dc.Line(ix + s / 2 - 1, iy + s - 4, ix + s - 4, iy + 3, ExArgb(EX_NAVY, 255));
      g_dc.Line(ix + s / 2 - 1, iy + s - 3, ix + s - 4, iy + 4, ExArgb(EX_NAVY, 255));
     }
   else
      CxRRg(ix + 2, iy + 2, ix + s - 3, iy + s - 3, 2, EX_NAVY, EX_NAVY);
   int tpad = ip + s + g_cx_pad / 2;
   int tx = (rtl ? x + ip : x + tpad);
   CxTxt(tx, y, w - tpad - ip, h, label, impl ? EX_TEXT : CX_LBL, 13, false, rtl ? 1 : -1);
   ExHitAdd(id, x, y, w, h);
  }

void CxStepper(const string id, const int x, const int y, const int w, const int h,
               const string label, const string value)
  {
   CxCard(x, y, w, h, "", EX_BLUE);
   int ip = g_cx_pad / 2;
   int bs = h - 2 * ip;
   CxBtn(id + "_dn", x + ip, y + ip, bs, bs, "-", EX_CARD, EX_NAVY, EX_TEXT, false, 15);
   CxBtn(id + "_up", x + w - ip - bs, y + ip, bs, bs, "+", EX_CARD, EX_NAVY, EX_TEXT, false, 15);
   int tx = x + ip + bs + ip;
   int tw = w - 2 * (ip + bs + ip);
   CxTxt(tx, y + 1, tw, h / 2, label, CX_LBL, 12, false, 0);
   CxTxt(tx, y + h / 2 - 2, tw, h / 2, value, EX_TEXT, 14, true, 0);
  }

void CxLogo(const int x, const int y, const int s)
  {
   int r = s / 5;
   CxRRg(x, y, x + s - 1, y + s - 1, r, EX_GOLD, EX_GOLD);
   CxRRg(x + 2, y + 2, x + s - 3, y + s - 3, r - 1, EX_NAVY, EX_NAVY);
   CxRRg(x + 3, y + 3, x + s - 4, y + s - 4, r - 1, EX_GOLD2, EX_GOLD);
   CxTxt(x, y, s, s, "M", EX_NAVY, 17, true, 0);
  }

void CxFlatRect(const int x0, const int y0, const int w0, const int h0)
  {
   CCanvas *c = g_dc;
   int x1 = MathMax(0, x0), y1 = MathMax(0, y0);
   int w = MathMin(g_ex_cw, x0 + w0), h = MathMin(g_ex_ch, y0 + h0);
   color n = EX_NAVY;
   int nr = (n & 0xFF), ng = ((n >> 8) & 0xFF), nb = ((n >> 16) & 0xFF);
   for(int yy = y1; yy < h; yy++)
      for(int xx = x1; xx < w; xx++)
        {
         uint p = c.PixelGet(xx, yy);
         uint a = (p >> 24);
         if(a == 255) continue;
         uint r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
         uint ro = (r * a + nr * (255 - a)) / 255;
         uint go = (g * a + ng * (255 - a)) / 255;
         uint bo = (b * a + nb * (255 - a)) / 255;
         c.PixelSet(xx, yy, 0xFF000000 | (ro << 16) | (go << 8) | bo);
        }
  }

//--- tab content ------------------------------------------------------
void CxTabTrade(const int y, const ExpertPerf &perf, const ExpertReport &rep,
                const double daily_used, const double dd_used, const bool killed, const bool blocked)
  {
   int gap = g_cx_pad;
   int rMk = CP(46);
   int cardH = g_cx_hCont - gap - rMk;
   int hdr = CxCardHdr();
   int rowH = (cardH - hdr - g_cx_pad / 2) / 5;
   int ip = g_cx_pad;
   int level = ExRiskLevel(daily_used, dd_used, killed, blocked);
   color lc = (level == 0 ? EX_GREEN : (level == 1 ? EX_AMBER : EX_CORAL));
   // RISK card
   int xr = CxX(0, 3, true), wr = CxSpan(3);
   CxCard(xr, y, wr, cardH, ExTr("risk"), lc);
   int ry = y + hdr;
   int kx = xr + ip, kw = wr - 2 * ip;
   CxKV(kx, ry, kw, rowH, ExTr("r_trade"), DoubleToString(DemoActiveRiskPct(), 2) + "%", EX_TEXT); ry += rowH;
   CxKV(kx, ry, kw, rowH, ExTr("r_daily"), DoubleToString(DemoActiveDailyPct(), 2) + "%", EX_TEXT); ry += rowH;
   CxKV(kx, ry, kw, rowH, ExTr("r_dd"),
        DemoActiveMaxDdPct() > 0 ? DoubleToString(DemoActiveMaxDdPct(), 2) + "%" : ExTr("dash"), EX_TEXT); ry += rowH;
   CxKV(kx, ry, kw, rowH, ExTr("r_open"),
        IntegerToString(rep.open_count) + " / " + IntegerToString(DemoActiveMaxPositions()), EX_TEXT); ry += rowH;
   int sm = ExpertSafeModeState();
   int losses = ExpertTodayLossStreak();
   string sv = ExTr("sm_off");
   color sc = EX_GREEN;
   if(sm == 2) { sv = ExTr("sm_stop") + " " + TimeToString(ExpertSafeModeClearsAt(), TIME_MINUTES); sc = EX_CORAL; }
   else if(sm == 1) { sv = ExTr("c_reduced") + " (" + IntegerToString(losses) + ")"; sc = EX_AMBER; }
   else if(losses > 0) { sv = IntegerToString(losses) + " " + ExTr("sm_today"); sc = EX_AMBER; }
   else sv = ExTr("off");
   CxKV(kx, ry, kw, rowH, ExTr("safemode"), sv, sc, false);
   // PERF card
   int xp = CxX(3, 3, true), wp = CxSpan(3);
   CxCard(xp, y, wp, cardH, ExTr("perf"), EX_BLUE);
   int px = xp + ip, pw2 = wp - 2 * ip;
   int py = y + hdr;
   string tv = (!perf.has_data && rep.today_trades == 0 && rep.history_trades == 0) ? ExTr("nodata") : IntegerToString(rep.today_trades);
   string wv = perf.has_data ? DoubleToString(perf.winpct, 1) + "%" : ExTr("nodata");
   string nv = perf.has_data ? ExpertMoney(perf.pnl) : ExTr("nodata");
   CxKV(px, py, pw2, rowH, ExTr("today"), tv, EX_TEXT); py += rowH;
   CxKV(px, py, pw2, rowH, ExTr("win"), wv, EX_TEXT); py += rowH;
   CxKV(px, py, pw2, rowH, ExTr("net"), nv, (perf.has_data && perf.pnl < 0) ? EX_CORAL : EX_GREEN, false); py += rowH;
   int bh = y + cardH - g_cx_pad / 2 - py - 2;
   if(bh >= CP(10))
     {
      ExPerfBars(px, py + 2, pw2 - 1, bh);
      CxFlatRect(px - 1, py + 1, pw2 + 2, bh + 3);
     }
   // MARKETS strip: 3 equal cells
   int my = y + cardH + gap;
   string kinds[3] = {"forex", "gold", "crypto"};
   string labs[3];
   labs[0] = ExTr("forex");
   string gs = ExMarketSym("gold");
   labs[1] = (StringLen(gs) > 0 ? ExTr("gold") + " (" + gs + ")" : ExTr("gold"));
   labs[2] = "Crypto";
   bool rtl = CxRtl();
   for(int i = 0; i < 3; i++)
     {
      int mx = CxX(i * 2, 2, true), mw = CxSpan(2);
      CxCard(mx, my, mw, rMk, "", EX_BLUE);
      string sym = ExMarketSym(kinds[i]);
      bool ok = (StringLen(sym) > 0);
      bool live = ok && ExTickOk(sym);
      string st = (!ok ? ExTr("nodata") : (live ? ExTr("active") : ExTr("closed")));
      color stc = (!ok ? EX_AMBER : (live ? EX_GREEN : CX_LBL));
      int sw = CP(40), ipp = g_cx_pad - 2;
      int sh = rMk - 2 * ipp;
      int spx = (rtl ? mx + ipp : mx + mw - ipp - sw);
      int tx = (rtl ? mx + ipp + sw + ipp : mx + ipp);
      int tw = mw - 3 * ipp - sw;
      CxTxt(tx, my + ipp / 2, tw, (rMk - ipp) / 2, labs[i], EX_TEXT, 13, true, rtl ? 1 : -1);
      CxTxt(tx, my + rMk / 2 - 1, tw, (rMk - ipp) / 2, st, stc, 12, false, rtl ? 1 : -1);
      if(ok)
        {
         ExSpark(spx, my + ipp, sw - 1, sh - 1, sym);
         CxFlatRect(spx - 1, my + ipp - 1, sw + 2, sh + 2);
        }
     }
  }

void CxTabHistory(const int y, const ExpertPerf &perf, const ExpertReport &rep)
  {
   int gap = g_cx_pad, ip = g_cx_pad;
   int rowH = CP(22);
   int hdr = CxCardHdr();
   int hA = hdr + 3 * rowH + g_cx_pad / 2;
   int xa = g_cx_pad, wa = CxSpan(6);
   CxCard(xa, y, wa, hA, ExTr("tab1"), EX_BLUE);
   int kx = xa + ip, kw = wa - 2 * ip, ry = y + hdr;
   string nd = ExTr("nodata");
   string t1 = (rep.today_trades == 0 && !perf.has_data) ? nd : IntegerToString(rep.today_trades) + "  " + ExpertMoney(rep.today_pnl);
   CxKV2(kx, ry, kw, rowH, ExTr("today"), t1, EX_TEXT,
         ExTr("win"), perf.has_data ? DoubleToString(perf.winpct, 1) + "%" : nd, EX_TEXT); ry += rowH;
   CxKV2(kx, ry, kw, rowH, ExTr("net"), perf.has_data ? ExpertMoney(perf.pnl) : nd,
         (perf.has_data && perf.pnl < 0) ? EX_CORAL : EX_GREEN,
         ExTr("c_wk"), (perf.has_data || rep.week_pnl != 0) ? ExpertMoney(rep.week_pnl) : nd, EX_TEXT); ry += rowH;
   CxKV2(kx, ry, kw, rowH, ExTr("c_mo"), (perf.has_data || rep.month_pnl != 0) ? ExpertMoney(rep.month_pnl) : nd, EX_TEXT,
         ExTr("c_op"), IntegerToString(rep.open_count), EX_TEXT, false);
   int yb = y + hA + gap;
   int hB = g_cx_hCont - hA - gap;
   CxCard(xa, yb, wa, hB, ExTr("c_daily"), EX_BLUE);
   int by = yb + hdr + 2;
   int bh = yb + hB - g_cx_pad / 2 - by;
   if(bh >= CP(10))
     {
      ExPerfBars(kx, by, kw - 1, bh);
      CxFlatRect(kx - 1, by - 1, kw + 2, bh + 3);
     }
  }

void CxTabReports(const int y, const ExpertPerf &perf, const ExpertReport &rep,
                  const double daily_used, const double dd_used, const bool killed, const bool blocked)
  {
   int gap = g_cx_pad, ip = g_cx_pad;
   int rowH = CP(22);
   int hdr = CxCardHdr();
   int hA = hdr + 3 * rowH + g_cx_pad / 2;
   int xa = g_cx_pad, wa = CxSpan(6);
   CxCard(xa, y, wa, hA, ExTr("tab3"), EX_BLUE);
   int kx = xa + ip, kw = wa - 2 * ip, ry = y + hdr;
   string nd = ExTr("nodata");
   CxKV2(kx, ry, kw, rowH, ExTr("c_bal"), DoubleToString(rep.balance, 2), EX_TEXT,
         ExTr("c_eq"), DoubleToString(rep.equity, 2), EX_TEXT); ry += rowH;
   CxKV2(kx, ry, kw, rowH, ExTr("c_fm"), DoubleToString(rep.free_margin, 2), EX_TEXT,
         ExTr("c_op"), IntegerToString(rep.open_count), EX_TEXT); ry += rowH;
   CxKV2(kx, ry, kw, rowH, ExTr("c_pl"), perf.has_data ? ExpertMoney(perf.pnl) : nd,
         (perf.has_data && perf.pnl < 0) ? EX_CORAL : EX_GREEN,
         ExTr("win"), perf.has_data ? DoubleToString(perf.winpct, 1) + "%" : nd, EX_TEXT, false);
   int yb = y + hA + gap;
   int hB = g_cx_hCont - hA - gap;
   int level = ExRiskLevel(daily_used, dd_used, killed, blocked);
   color lc = (level == 0 ? EX_GREEN : (level == 1 ? EX_AMBER : EX_CORAL));
   CxCard(xa, yb, wa, hB, ExTr("risk"), lc);
   int rh = (hB - hdr - g_cx_pad / 2) / 3;
   ry = yb + hdr;
   CxKV2(kx, ry, kw, rh, ExTr("r_trade"), DoubleToString(DemoActiveRiskPct(), 2) + "%", EX_TEXT,
         ExTr("r_daily"), DoubleToString(DemoActiveDailyPct(), 2) + "%", EX_TEXT); ry += rh;
   CxKV2(kx, ry, kw, rh, ExTr("r_dd"), DemoActiveMaxDdPct() > 0 ? DoubleToString(DemoActiveMaxDdPct(), 2) + "%" : ExTr("dash"), EX_TEXT,
         ExTr("r_open"), IntegerToString(rep.open_count) + " / " + IntegerToString(DemoActiveMaxPositions()), EX_TEXT); ry += rh;
   string news = DemoNextNewsLine();
   CxKV(kx, ry, kw, rh, ExTr("c_news"), StringLen(news) > 0 ? news : ExTr("dash"), CX_LBL, false);
  }

void CxTabSignals(const int y, const int strength, const bool linked)
  {
   int gap = g_cx_pad, rKV = g_cx_rKV, rC = g_cx_rChip;
   int wl = CxSpan(3);
   int xl = CxX(0, 3, true), xr2 = CxX(3, 3, true);
   string lastv = "";
   color lastc = EX_TEXT;
   bool has = (g_ex_last_entry > 0.0 && StringLen(g_ex_last_side) > 0);
   if(has) lastv = g_ex_last_side + " " + ExPriceStr(g_ex_last_entry);
   else { lastv = ExTr("nodata"); lastc = EX_AMBER; }
   CxKV(xl, y, wl, rKV, ExTr("sigpwr"), IntegerToString(strength), EX_TEXT);
   CxKV(xr2, y, wl, rKV, ExTr("c_last"), lastv, lastc);
   if(has)
     {
      CxKV(xl, y + rKV, wl, rKV, ExTr("c_sl"), ExPriceStr(g_ex_last_sl), EX_CORAL);
      CxKV(xr2, y + rKV, wl, rKV, ExTr("c_tp"), ExPriceStr(g_ex_last_tp), EX_GREEN);
     }
   else
     {
      string news = DemoNextNewsLine();
      if(StringLen(g_ex_last_msg) > 0)
         CxKV(g_cx_pad, y + rKV, CxSpan(6), rKV, ExTr("c_last"), g_ex_last_msg, EX_AMBER, false);
      else
         CxKV(g_cx_pad, y + rKV, CxSpan(6), rKV, ExTr("c_news"), StringLen(news) > 0 ? news : ExTr("dash"), CX_LBL, false);
     }
   int sy = y + 2 * rKV + gap;
   string ids[6] = {"sc", "tr", "rk", "sm", "sp2l", "fvg"};
   string keys[6] = {"sc", "tf", "rk", "sm", "sp2l", "fvg"};
   bool ons[6];
   ons[0] = StratUseScalper(); ons[1] = StratUseTrend(); ons[2] = StratUseRocket(); ons[3] = StratUseSmc();
   ons[4] = InpUseSP2LFilter;  ons[5] = InpUseFVGFilter;
   bool impl[6];
   impl[0] = true; impl[1] = true; impl[2] = true; impl[3] = true; impl[4] = true; impl[5] = true;
   for(int i = 0; i < 6; i++)
     {
      int cx = CxX((i % 3) * 2, 2, true);
      int cy = sy + (i / 3) * (rC + gap);
      CxChip(ids[i], cx, cy, CxSpan(2), rC, ExTr(keys[i]), ons[i], impl[i]);
     }
   int gy = sy + 2 * rC + gap + gap;
   string gk[8] = {"g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7"};
   int gmap[8] = {0, 5, 7, 6, 1, 8, 9, 10};
   for(int i = 0; i < 9; i++)
     {
      int cx = CxX((i % 3) * 2, 2, true);
      int cy = gy + (i / 3) * (rC + gap);
      if(i < 8)
        {
         int sl = gmap[i];
         bool ok = (linked && sl < 11 && StringLen(g_ai_group_st[sl]) > 0 && StringFind(g_ai_group_st[sl], "Disconnected") < 0);
         CxBtn("ag" + IntegerToString(i), cx, cy, CxSpan(2), rC, ExTr(gk[i]), ok ? EX_BLUE : EX_CARD, EX_NAVY, EX_TEXT, false, 12);
        }
      else
        {
         int on = (linked ? g_ai_agents_on : 0);
         int tot = (g_ai_agents_total > 0 ? g_ai_agents_total : 51);
         if(tot > 51) tot = 51;
         string txt = (linked ? IntegerToString(on) + " / " + IntegerToString(tot) + "  " + ExTr("agents") : ExTr("disc"));
         CxCard(cx, cy, CxSpan(2), rC, "", linked ? EX_GREEN : EX_CORAL);
         CxTxt(cx + 2, cy, CxSpan(2) - 4, rC, txt, linked ? EX_GREEN : EX_CORAL, 12, true, 0);
        }
     }
  }

void CxTabSettings(const int y)
  {
   int gap = g_cx_pad, ip = g_cx_pad;
   int bh = CP(30);
   bool auto_on = ExpertAutoOn();
   bool stop = ExpertStopNew();
   CxBtn("auto", CxX(0, 3, true), y, CxSpan(3), bh, ExTr("auto") + " " + (auto_on ? ExTr("on") : ExTr("off")),
         auto_on ? EX_BLUE : EX_CARD, EX_NAVY, auto_on ? EX_TEXT : CX_LBL, false, 13);
   CxBtn("stop", CxX(3, 3, true), y, CxSpan(3), bh, ExTr("stopnew"),
         stop ? EX_CORAL : EX_CARD, EX_NAVY, stop ? EX_TEXT : CX_LBL, stop, 13);
   int cy = y + bh + gap;
   int rowH = CP(22);
   int hdr = CxCardHdr();
   int note = g_cx_rKV;
   int hC = g_cx_hCont - bh - gap - gap - note;
   int xa = g_cx_pad, wa = CxSpan(6);
   CxCard(xa, cy, wa, hC, ExTr("tab4"), EX_BLUE);
   int kx = xa + ip, kw = wa - 2 * ip, ry = cy + hdr;
   int rh = (hC - hdr - g_cx_pad / 2) / 3;
   CxKV2(kx, ry, kw, rh, ExTr("c_riskp"), DoubleToString(g_ex_risk_ui, 2), EX_TEXT,
         ExTr("c_maxpos"), IntegerToString(g_ex_max_pos), EX_TEXT); ry += rh;
   CxKV2(kx, ry, kw, rh, ExTr("lot"), DoubleToString(g_ex_lot, 2), EX_TEXT,
         ExTr("c_smart"), g_ex_smart_sl ? ExTr("on") : ExTr("off"), g_ex_smart_sl ? EX_GREEN : CX_LBL); ry += rh;
   CxKV2(kx, ry, kw, rh, ExTr("sp2l"), InpUseSP2LFilter ? ExTr("on") : ExTr("off"), InpUseSP2LFilter ? EX_GREEN : CX_LBL,
         ExTr("fvg"), InpUseFVGFilter ? ExTr("on") : ExTr("off"), InpUseFVGFilter ? EX_GREEN : CX_LBL, false);
   CxTxt(g_cx_pad, cy + hC + gap, CxSpan(6), note, CxNoDot(ExTr("about1")), CX_LBL, 12, false, CxRtl() ? 1 : -1);
  }

void CxTabAbout(const int y)
  {
   int ip = g_cx_pad;
   int hdr = CxCardHdr();
   int xa = g_cx_pad, wa = CxSpan(6), hC = g_cx_hCont;
   CxCard(xa, y, wa, hC, "Molido Expert  " + MOLIDO_EA_VERSION, EX_GOLD);
   int kx = xa + ip, kw = wa - 2 * ip, ry = y + hdr;
   int rh = (hC - hdr - g_cx_pad / 2) / 4;
   CxKV(kx, ry, kw, rh, ExTr("subtitle"), "v" + MOLIDO_EA_VERSION, EX_TEXT); ry += rh;
   CxKV(kx, ry, kw, rh, ExTr("c_magic"), IntegerToString((int)MOLIDO_MAGIC), EX_TEXT); ry += rh;
   CxTxt(kx, ry, kw, rh, CxNoDot(ExTr("about1")), EX_AMBER, 12, false, CxRtl() ? 1 : -1);
   g_dc.FillRectangle(kx, ry + rh - 1, kx + kw - 1, ry + rh - 1, ExArgb(EX_LINE, 150)); ry += rh;
   CxKV(kx, ry, kw, rh, ExTr("updated"), TimeToString(g_ex_updated, TIME_DATE | TIME_SECONDS), CX_LBL, false);
  }

void ExDrawCompact(const bool ready, const bool linked, const bool blocked, const bool killed,
                   const ExpertPerf &perf, const ExpertReport &rep,
                   const double daily_used, const double dd_used, const int strength)
  {
   ExUse(g_cv_h);
   int W = g_ex_cw, H = g_ex_ch;
   int pad = g_cx_pad, gap = g_cx_pad;
   bool rtl = CxRtl();
   g_cv_h.Erase(ExArgb(EX_NAVY, 255));
   // title band
   int hT = g_cx_hTitle;
   ExGradV(1, 1, W - 2, hT - 1, EX_NAVY2, EX_BLACK, 255, 255, 0);
   g_dc.FillRectangle(0, 0, W - 1, 1, ExArgb(EX_GOLD, 255));
   g_dc.FillRectangle(1, hT - 1, W - 2, hT - 1, ExArgb(EX_BLUE, 255));
   string st = ExTr("ready");
   color sc = EX_GREEN;
   bool live = ready;
   if(blocked) { st = ExTr("real"); sc = EX_CORAL; live = false; }
   else if(killed) { st = ExTr("killed"); sc = EX_CORAL; live = false; }
   else if(!ready) { st = ExTr("notready"); sc = EX_AMBER; live = false; }
   int bs = CP(26);
   int by = (hT - bs) / 2;
   int xc = W - pad - bs;
   int xl = xc - pad / 2 - bs;
   string lang = "EN";
   int L = MolidoLangId();
   if(L == LANG_FA) lang = "FA";
   else if(L == LANG_AR) lang = "AR";
   else if(L == LANG_TR) lang = "TR";
   if(g_ex_collapsed)
      ExHitAdd("expand", 0, 0, W, hT);
   int ls = CP(28);
   CxLogo(pad, (hT - ls) / 2, ls);
   int tx = pad + ls + pad;
   string brand = "Molido Expert";
   ExFont("Segoe UI Bold", 16);
   int brw = ExTw(brand);
   CxTxt(tx, 2, brw + 4, hT / 2, brand, EX_GOLD2, 16, true, -1);
   CxTxt(tx, hT / 2 - 1, W / 2 - tx, hT / 2 - 2, ExTr("subtitle") + "  v" + MOLIDO_EA_VERSION, EX_BLUE, 11, false, -1);
   int qx = tx + MathMax(brw, ExTw(ExTr("subtitle") + "  v" + MOLIDO_EA_VERSION)) + pad;
   int qw = xl - pad - qx;
   if(g_ex_collapsed)
     {
      if(qw > CP(60))
         CxPill(xl - pad - MathMin(qw, CP(150)), (hT - CP(22)) / 2, MathMin(qw, CP(150)), CP(22), sc, st, live);
     }
   else if(qw > CP(40))
     {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      CxTxt(qx, 2, qw, hT / 2, _Symbol, EX_GOLD2, 14, true, 1);
      CxTxt(qx, hT / 2 - 1, qw, hT / 2 - 2, ask > 0.0 ? ExPriceStr(ask) : ExTr("dash"), EX_TEXT, 12, false, 1);
     }
   CxBtn("lang", xl, by, bs, bs, lang, EX_CARD, EX_NAVY, EX_GOLD2, false, 12);
   CxBtn("collapse", xc, by, bs, bs, (g_ex_collapsed ? "+" : "-"), EX_CARD, EX_NAVY, EX_GOLD2, false, 15);
   g_dc.Rectangle(0, 0, W - 1, H - 1, ExArgb(EX_LINE, 255));
   if(g_ex_collapsed)
      return;

   int y = hT + gap;
   // status row: two equal cells
   int hS = g_cx_hStat;
   CxPill(CxX(0, 3, true), y, CxSpan(3), hS, sc, st, live);
   string lk = ExTr("core") + "  " + (linked ? ExTr("online") : ExTr("offline"));
   CxPill(CxX(3, 3, true), y, CxSpan(3), hS, linked ? EX_GREEN : EX_CORAL, lk, linked);
   y += hS + gap;
   // timeframe row: 9 equal buttons
   string labs[9] = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"};
   ENUM_TIMEFRAMES tfs[9] = {PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1, PERIOD_H4, PERIOD_D1, PERIOD_W1, PERIOD_MN1};
   ENUM_TIMEFRAMES cur = (ENUM_TIMEFRAMES)Period();
   int hTf = g_cx_hTf;
   for(int i = 0; i < 9; i++)
     {
      bool on = (cur == tfs[i]);
      CxBtn("tf" + labs[i], pad + i * (g_cx_tfw + gap), y, g_cx_tfw, hTf, labs[i],
            on ? EX_BLUE : EX_CARD, EX_NAVY, on ? EX_GOLD2 : EX_TEXT, false, 12);
     }
   CxHair(y + hTf + gap / 2);
   y += hTf + gap;
   // trade row: BUY | SELL (equal)
   int hB = g_cx_hBs;
   bool fa = rtl;
   CxBtn("buy", pad, y, CxSpan(3), hB, fa ? ExTr("buy") + "  BUY" : "BUY", EX_GREEN, EX_GREEN2, EX_TEXT, false, 15);
   CxBtn("sell", pad + CxSpan(3) + gap, y, CxSpan(3), hB, fa ? ExTr("sell") + "  SELL" : "SELL", EX_CORAL, EX_RED, EX_TEXT, true, 15);
   y += hB + gap;
   // steppers: lot | SL | TP
   int hP = g_cx_hStep;
   CxStepper("lot", CxX(0, 2, true), y, CxSpan(2), hP, ExTr("lot"), DoubleToString(g_ex_lot, 2));
   CxStepper("sl",  CxX(2, 2, true), y, CxSpan(2), hP, ExTr("c_sl"), ExSlPreview());
   CxStepper("tp",  CxX(4, 2, true), y, CxSpan(2), hP, ExTr("c_tp"), ExTpPreview());
   y += hP + gap;
   // actions: close | close all | kill
   int hA = g_cx_hAct;
   CxBtn("close", CxX(0, 2, true), y, CxSpan(2), hA, ExTr("close"), EX_CARD, EX_NAVY2, EX_TEXT, false, 13);
   CxBtn("closeall", CxX(2, 2, true), y, CxSpan(2), hA, ExTr("closeall"), EX_CARD, EX_NAVY2, EX_TEXT, false, 13);
   CxBtn("kill", CxX(4, 2, true), y, CxSpan(2), hA, ExTr("kill"), EX_CORAL, EX_RED, EX_TEXT, true, 13);
   CxHair(y + hA + gap / 2);
   y += hA + gap;
   // tabs: 6 equal
   int hTb = g_cx_hTab;
   string tk[6] = {"tab0", "tab1", "tab2", "tab3", "tab4", "tab5"};
   for(int i = 0; i < 6; i++)
     {
      bool on = (g_ex_tab == i);
      CxBtn("tab" + IntegerToString(i), CxX(i, 1, true), y, g_cx_colw, hTb, ExTr(tk[i]),
            on ? EX_BLUE : EX_CARD, EX_NAVY, on ? EX_GOLD2 : CX_LBL, false, 12);
     }
   CxHair(y + hTb + gap / 2);
   y += hTb + gap;
   // tab content (fixed height)
   if(g_ex_tab == 0)      CxTabTrade(y, perf, rep, daily_used, dd_used, killed, blocked);
   else if(g_ex_tab == 1) CxTabHistory(y, perf, rep);
   else if(g_ex_tab == 2) CxTabSignals(y, strength, linked);
   else if(g_ex_tab == 3) CxTabReports(y, perf, rep, daily_used, dd_used, killed, blocked);
   else if(g_ex_tab == 4) CxTabSettings(y);
   else                   CxTabAbout(y);
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

void ExCapture()
  {
   static string captured = "";
   if(captured == MOLIDO_EA_VERSION) return;
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
   g_ex_sig = "";
   g_ex_tab = 0;
   g_gauge_shown = 0;
   ExLoadCollapsed();
   ChartSetInteger(0, CHART_EVENT_MOUSE_MOVE, true);
   if(ShowDashboard)
     {
      ExEnsure();
      if(ExIsFullUi())
        {
         ExHideHostChart();
         ExPlaceLiveChart();
        }
     }
  }

void MolidoDashOnDeinit()
  {
   ChartSetInteger(0, CHART_EVENT_MOUSE_MOVE, false);
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
   int W = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int H = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   if(g_ex_ready && (W != g_ex_chart_w || H != g_ex_chart_h))
      ExRelayout();
   if(!ExEnsure())
      return;

   bool blocked = MolidoRealBlocked();
   bool linked = ExpertBridgeConnected();
   bool killed = DemoKillEngaged();
   bool ea_on = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && AllowTrading && !blocked && !killed;
   ExpertPerf perf;
   ExpertReport rep;
   ExpertScanHistory(perf, rep);
   int strength = DemoSignalStrength();
   // ease the gauge toward the live strength (1s frames)
   g_gauge_shown = g_gauge_shown + (strength - g_gauge_shown) * 0.4;
   if(MathAbs(g_gauge_shown - strength) < 0.5)
      g_gauge_shown = strength;
   g_ex_updated = TimeLocal();

   double daily_pct = 0.0;
   DemoDailyPnlPct(daily_pct);
   double daily_loss = -MathMin(0.0, daily_pct);
   double daily_cap = DemoActiveDailyPct();
   double daily_used = (daily_cap > 0.0 ? 100.0 * daily_loss / daily_cap : 0.0);
   double dd_pct = 0.0, start_eq = 0.0;
   double dd_used = 0.0;
   if(DemoActiveMaxDdPct() > 0.0 && DemoMaxDdPct(dd_pct, start_eq))
      dd_used = 100.0 * dd_pct / DemoActiveMaxDdPct();

   string clock = TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS);
   string sig = MOLIDO_EA_VERSION + IntegerToString((int)MolidoLangId()) +
                IntegerToString((int)linked) + IntegerToString(g_ai_agents_on) +
                IntegerToString((int)ea_on) + IntegerToString((int)killed) +
                clock + _Symbol + IntegerToString(Period()) +
                IntegerToString(g_ex_tab) + g_hover + g_pressed +
                IntegerToString(W) + IntegerToString(H) +
                IntegerToString((int)ExpertAutoOn()) + IntegerToString((int)ExpertStopNew()) +
                IntegerToString((int)StratUseScalper()) + IntegerToString((int)StratUseTrend()) +
                IntegerToString((int)InpUseSP2LFilter) + IntegerToString((int)InpUseFVGFilter) +
                IntegerToString((int)g_ex_collapsed) + IntegerToString((int)DashboardUiSize) +
                DoubleToString(rep.equity, 2) + IntegerToString(rep.open_count) +
                IntegerToString(perf.trades) + g_ex_last_msg +
                IntegerToString((int)blocked) + IntegerToString(strength) +
                DoubleToString(g_ex_lot, 2) + DoubleToString(g_ex_sl_pts, 0) +
                DoubleToString(g_ex_tp_pts, 0) + DoubleToString(g_gauge_shown, 1) +
                IntegerToString((int)(ExPulse() * 10));
   if(sig == g_ex_sig)
      return;
   g_ex_sig = sig;

   if(!ExIsFullUi())
     {
      ExHitsClear();
      ExSetOrigin(0, 0);
      ExDrawCompact(ea_on, linked, blocked, killed, perf, rep, daily_used, dd_used, strength);
      g_cv_h.Update();
      ExMarkSync();
      ChartRedraw(0);
      ExCapture();
      return;
     }

   ExHitsClear();
   int mid_y = g_ly_hy + g_ly_hh;
   int bot_y = mid_y + g_ly_mid;

   // origins for hit tests (canvas origin on the chart)
   ExSetOrigin(0, 0);
   ExDrawHeader(ea_on, linked, blocked, killed);
   ExUse(g_cv_h);
   int chip_w = ExPx(70), chip_h = ExPx(20);
   int btnw = ExHeaderButtonsWidth();
   if(ExIsFullUi() && g_ex_cw >= 1100)
     {
      int hx = g_ex_cw - btnw - ExTw(TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS)) - ExPx(8) - chip_w * 2 - ExPx(8);
      if(hx < g_ex_cw / 2) hx = g_ex_cw - btnw - ExPx(200);
      ExBtn3D("auto", hx, ExPx(20), chip_w, chip_h,
              ExTr("auto"), ExpertAutoOn() ? EX_BLUE : EX_CARD, EX_NAVY,
              ExpertAutoOn() ? EX_TEXT : EX_MUTED, false);
      ExBtn3D("stop", hx + chip_w + ExPx(4), ExPx(20), chip_w, chip_h,
              ExTr("stopnew"), ExpertStopNew() ? EX_CORAL : EX_CARD, EX_NAVY,
              ExpertStopNew() ? EX_TEXT : EX_MUTED, ExpertStopNew());
     }
   else if(!g_ex_collapsed && !ExIsFullUi())
     {
      chip_w = ExPx(54); chip_h = ExPx(16);
      int hx = g_ex_cw - btnw - chip_w * 2 - ExPx(6);
      if(hx > ExPx(80))
        {
         ExBtn3D("auto", hx, g_ly_head - chip_h - ExPx(4), chip_w, chip_h,
                 ExTr("auto"), ExpertAutoOn() ? EX_BLUE : EX_CARD, EX_NAVY,
                 ExpertAutoOn() ? EX_TEXT : EX_MUTED, false);
         ExBtn3D("stop", hx + chip_w + ExPx(4), g_ly_head - chip_h - ExPx(4), chip_w, chip_h,
                 ExTr("stopnew"), ExpertStopNew() ? EX_CORAL : EX_CARD, EX_NAVY,
                 ExpertStopNew() ? EX_TEXT : EX_MUTED, ExpertStopNew());
        }
     }

   if(!g_ex_collapsed)
     {
      ExSetOrigin(0, g_ly_head);
      ExDrawLeft(strength, linked);

      ExSetOrigin(g_ex_cw - g_ly_right, g_ly_head);
      ExDrawRight(linked);

      ExSetOrigin(0, mid_y);
      ExDrawMid();

      ExSetOrigin(0, bot_y);
      if(g_ex_tab == 1 || g_ex_tab == 3)
         ExDrawBotReport(perf, rep);
      else if(g_ex_tab == 2)
         ExDrawBotSignals(strength);
      else if(g_ex_tab == 4)
         ExDrawBotSettings();
      else if(g_ex_tab == 5)
         ExDrawBotAbout();
      else
         ExDrawBotTrade(perf, rep, daily_used, dd_used, killed, blocked);

      ExSetOrigin(0, g_ex_ch - g_ly_tab);
      ExDrawTabs();
     }

   int tw, th, tx, ty, hw, hh, hx, hy;
   ExHudTagPos(tx, ty, tw, th, hx, hy, hw, hh);
   g_ox = tx; g_oy = ty;
   ExDrawTag();
   g_ox = hx; g_oy = hy;
   ExDrawHud();

   g_cv_h.Update();
   if(!g_ex_collapsed)
     {
      g_cv_l.Update();
      g_cv_r.Update();
      g_cv_m.Update();
      g_cv_b.Update();
      g_cv_t.Update();
     }
   g_cv_tag.Update();
   g_cv_hud.Update();
   ExMarkSync();
   ChartRedraw(0);
   ExCapture();
  }

void ExDoAction(const string idb)
  {
   if(idb == "") return;
   if(idb == "collapse" || idb == "expand")
     {
      ExToggleCollapsed();
      ExRelayout();
      MolidoDashRedraw();
      return;
     }
   if(idb == "lang" || idb == "fa" || idb == "en")
     {
      if(MolidoLangId() == LANG_FA)
         g_ui_lang = LANG_EN;
      else
         g_ui_lang = LANG_FA;
      g_i18n_fallback = false;
      MolidoI18nInit();
      g_ex_sig = "";
      MolidoDashRedraw();
      return;
     }
   if(idb == "auto") { ExpertSetAuto(!ExpertAutoOn()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "stop") { ExpertSetStopNew(!ExpertStopNew()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "kill")
     {
      if(DemoKillEngaged()) DemoKillSet(false);
      else DemoKillSet(true);
      g_ex_sig = ""; MolidoDashRedraw(); return;
     }
   if(idb == "buy")  { ExpertManualTrade("buy");  g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "sell") { ExpertManualTrade("sell"); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "close"){ ExpertCloseChart();        g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "closeall"){ ExpertCloseAll();       g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "sc") { StratSet("scalper", !StratUseScalper()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "tr") { StratSet("trend", !StratUseTrend()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "rk") { StratSetRocket(!StratUseRocket()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "sm") { StratSetSmc(!StratUseSmc()); g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(StringFind(idb, "tab") == 0)
     {
      g_ex_tab = (int)StringToInteger(StringSubstr(idb, 3));
      if(g_ex_tab < 0) g_ex_tab = 0;
      if(g_ex_tab > 5) g_ex_tab = 5;
      g_ex_sig = ""; MolidoDashRedraw(); return;
     }
   if(idb == "lot_up")
     {
      double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      if(step <= 0.0) step = 0.01;
      g_ex_lot += step;
      if(g_ex_lot > DemoActiveMaxLotsCap()) g_ex_lot = DemoActiveMaxLotsCap();
      g_ex_sig = ""; MolidoDashRedraw(); return;
     }
   if(idb == "lot_dn")
     {
      double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      if(step <= 0.0) step = 0.01;
      double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      g_ex_lot -= step;
      if(g_ex_lot < mn) g_ex_lot = mn;
      if(g_ex_lot < 0.0) g_ex_lot = 0.0;
      g_ex_sig = ""; MolidoDashRedraw(); return;
     }
   if(idb == "sl_up") { g_ex_smart_sl = false; g_ex_sl_pts += 50; g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "sl_dn")
     {
      g_ex_sl_pts -= 50;
      if(g_ex_sl_pts <= 0) { g_ex_sl_pts = 0; g_ex_smart_sl = true; }
      g_ex_sig = ""; MolidoDashRedraw(); return;
     }
   if(idb == "tp_up") { g_ex_tp_pts += 50; g_ex_sig = ""; MolidoDashRedraw(); return; }
   if(idb == "tp_dn")
     {
      g_ex_tp_pts -= 50;
      if(g_ex_tp_pts < 0) g_ex_tp_pts = 0;
      g_ex_sig = ""; MolidoDashRedraw(); return;
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
   if(StringFind(idb, "ag") == 0)
     return;
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
   if(id == CHARTEVENT_MOUSE_MOVE)
     {
      string over = ExHitAt((int)lparam, (int)dparam);
      int flags = (int)StringToInteger(sparam);
      bool left = ((flags & 1) == 1);
      string press = (left ? over : "");
      if(over == g_hover && press == g_pressed)
         return;
      g_hover = over;
      g_pressed = press;
      g_ex_sig = "";
      MolidoDashRedraw();
      return;
     }
   if(id == CHARTEVENT_CLICK)
     {
      string over = ExHitAt((int)lparam, (int)dparam);
      g_pressed = "";
      if(over != "")
         ExDoAction(over);
      return;
     }
  }

#endif

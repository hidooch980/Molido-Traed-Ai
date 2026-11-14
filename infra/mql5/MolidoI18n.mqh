//+------------------------------------------------------------------+
//| MolidoI18n.mqh - dashboard/message language pack.                |
//| Persian default; English, Arabic, Turkish. If the selected       |
//| script cannot render, fall back to English.                      |
//+------------------------------------------------------------------+
#ifndef MOLIDO_I18N_MQH
#define MOLIDO_I18N_MQH

string g_i18n_face = "Segoe UI";
bool   g_i18n_fallback = false;
int    g_ui_lang = -1;  // -1 = Language input; header FA/EN may override

int MolidoLangId()
  {
   if(g_i18n_fallback)
      return(LANG_EN);
   if(g_ui_lang >= 0)
      return(g_ui_lang);
   return((int)Language);
  }

bool MolidoFontAvailable(const string face)
  {
   string name = "MolidoFontProbe";
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0))
         return(false);
     }
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, name, OBJPROP_FONT, face);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
   string got = ObjectGetString(0, name, OBJPROP_FONT);
   ObjectDelete(0, name);
   return(got == face && StringLen(face) > 0);
  }

void MolidoI18nInit()
  {
   g_i18n_fallback = false;
   g_i18n_face = "Segoe UI";
   int lang = (int)Language;
   //--- Turkish and English use Latin; Segoe UI / Tahoma are enough.
   //--- Persian and Arabic need a font with Arabic-script glyphs.
   string faces[];
   if(lang == LANG_FA || lang == LANG_AR)
     {
      ArrayResize(faces, 5);
      faces[0] = "Segoe UI";
      faces[1] = "Tahoma";
      faces[2] = "Arial Unicode MS";
      faces[3] = "Traditional Arabic";
      faces[4] = "Arial";
     }
   else
     {
      ArrayResize(faces, 3);
      faces[0] = "Segoe UI";
      faces[1] = "Tahoma";
      faces[2] = "Arial";
     }
   bool ok = false;
   for(int i = 0; i < ArraySize(faces); i++)
     {
      if(MolidoFontAvailable(faces[i]))
        {
         g_i18n_face = faces[i];
         ok = true;
         break;
        }
     }
   if(!ok || ((lang == LANG_FA || lang == LANG_AR) && !ok))
     {
      if(!ok)
        {
         g_i18n_fallback = true;
         g_i18n_face = "Tahoma";
        }
     }
   //--- If an Arabic-script language was requested but no Unicode font
   //--- accepted the face, fall back to English so the panel stays readable.
   if((lang == LANG_FA || lang == LANG_AR) && !ok)
      g_i18n_fallback = true;
  }

string MolidoUiFont(const bool emph)
  {
   if(emph && g_i18n_face == "Segoe UI")
      return("Segoe UI Semibold");
   if(emph && g_i18n_face == "Segoe UI")
      return("Segoe UI Bold");
   return(g_i18n_face);
  }

string MolidoUiFontBold()
  {
   if(g_i18n_face == "Segoe UI")
      return("Segoe UI Bold");
   return(g_i18n_face);
  }

string Tr(const string key)
  {
   int L = MolidoLangId();
   // FA, EN, AR, TR
   if(key == "sec_account")
      return(L==LANG_FA ? "حساب" : L==LANG_AR ? "الحساب" : L==LANG_TR ? "Hesap" : "ACCOUNT");
   if(key == "sec_challenge")
      return(L==LANG_FA ? "چالش" : L==LANG_AR ? "التحدي" : L==LANG_TR ? "Challenge" : "CHALLENGE");
   if(key == "sec_profile")
      return(L==LANG_FA ? "پروفایل" : L==LANG_AR ? "الملف" : L==LANG_TR ? "Profil" : "PROFILE");
   if(key == "sec_risk")
      return(L==LANG_FA ? "ریسک" : L==LANG_AR ? "المخاطر" : L==LANG_TR ? "Risk" : "RISK");
   if(key == "sec_signal")
      return(L==LANG_FA ? "سیگنال" : L==LANG_AR ? "الإشارة" : L==LANG_TR ? "Sinyal" : "SIGNAL");
   if(key == "sec_market")
      return(L==LANG_FA ? "بازار" : L==LANG_AR ? "السوق" : L==LANG_TR ? "Piyasa" : "MARKET");
   if(key == "sec_smart")
      return(L==LANG_FA ? "فیلتر هوشمند" : L==LANG_AR ? "الفلاتر" : L==LANG_TR ? "Akıllı filtre" : "SMART");
   if(key == "account")
      return(L==LANG_FA ? "حساب" : L==LANG_AR ? "الحساب" : L==LANG_TR ? "Hesap" : "Account");
   if(key == "balance")
      return(L==LANG_FA ? "موجودی" : L==LANG_AR ? "الرصيد" : L==LANG_TR ? "Bakiye" : "Balance");
   if(key == "float_pl")
      return(L==LANG_FA ? "سود/زیان شناور" : L==LANG_AR ? "الربح العائم" : L==LANG_TR ? "Açık P/L" : "Float P/L");
   if(key == "target")
      return(L==LANG_FA ? "هدف" : L==LANG_AR ? "الهدف" : L==LANG_TR ? "Hedef" : "Target");
   if(key == "progress")
      return(L==LANG_FA ? "پیشرفت" : L==LANG_AR ? "التقدم" : L==LANG_TR ? "İlerleme" : "Progress");
   if(key == "dd")
      return(L==LANG_FA ? "دراوداون" : L==LANG_AR ? "التراجع" : L==LANG_TR ? "DD" : "DD");
   if(key == "daily")
      return(L==LANG_FA ? "روزانه" : L==LANG_AR ? "يومي" : L==LANG_TR ? "Günlük" : "Daily");
   if(key == "days")
      return(L==LANG_FA ? "روزها" : L==LANG_AR ? "الأيام" : L==LANG_TR ? "Gün" : "Days");
   if(key == "profile")
      return(L==LANG_FA ? "پروفایل" : L==LANG_AR ? "الملف" : L==LANG_TR ? "Profil" : "Profile");
   if(key == "dd_left")
      return(L==LANG_FA ? "دراوداون باقی" : L==LANG_AR ? "التراجع المتبقي" : L==LANG_TR ? "Kalan DD" : "DD left");
   if(key == "day_pl")
      return(L==LANG_FA ? "سود/زیان روز" : L==LANG_AR ? "ربح اليوم" : L==LANG_TR ? "Günlük P/L" : "Day P/L");
   if(key == "daily_cap")
      return(L==LANG_FA ? "سقف روزانه" : L==LANG_AR ? "الحد اليومي" : L==LANG_TR ? "Günlük tavan" : "Daily cap");
   if(key == "scalper")
      return(L==LANG_FA ? "اسکلپر" : L==LANG_AR ? "السكالبر" : L==LANG_TR ? "Scalper" : "Scalper");
   if(key == "brain")
      return(L==LANG_FA ? "مغز ریسک" : L==LANG_AR ? "عقل المخاطر" : L==LANG_TR ? "Risk beyni" : "Brain");
   if(key == "strength")
      return(L==LANG_FA ? "قدرت سیگنال" : L==LANG_AR ? "قوة الإشارة" : L==LANG_TR ? "Sinyal gücü" : "Strength");
   if(key == "positions")
      return(L==LANG_FA ? "پوزیشن‌ها" : L==LANG_AR ? "الصفقات" : L==LANG_TR ? "Pozisyonlar" : "Positions");
   if(key == "spread")
      return(L==LANG_FA ? "اسپرد" : L==LANG_AR ? "السبريد" : L==LANG_TR ? "Spread" : "Spread");
   if(key == "next")
      return(L==LANG_FA ? "کندل بعد" : L==LANG_AR ? "الشمعة التالية" : L==LANG_TR ? "Sonraki" : "Next");
   if(key == "news")
      return(L==LANG_FA ? "خبر" : L==LANG_AR ? "الأخبار" : L==LANG_TR ? "Haber" : "News");
   if(key == "auto")
      return(L==LANG_FA ? "خودکار" : L==LANG_AR ? "تلقائي" : L==LANG_TR ? "Otomatik" : "Auto");
   if(key == "eq")
      return(L==LANG_FA ? "دارایی" : L==LANG_AR ? "حقوق" : L==LANG_TR ? "Equity" : "eq");
   if(key == "lots")
      return(L==LANG_FA ? "لات" : L==LANG_AR ? "لوت" : L==LANG_TR ? "Lot" : "lots");
   if(key == "pts")
      return(L==LANG_FA ? "نقطه" : L==LANG_AR ? "نقطة" : L==LANG_TR ? "puan" : "pts");
   if(key == "kill")
      return(L==LANG_FA ? "توقف" : L==LANG_AR ? "إيقاف" : L==LANG_TR ? "DURDUR" : "KILL");
   if(key == "kill_on")
      return(L==LANG_FA ? "توقف فعال" : L==LANG_AR ? "الإيقاف فعال" : L==LANG_TR ? "DURDUR AÇIK" : "KILL ON");
   if(key == "update_now")
      return(L==LANG_FA ? "به‌روزرسانی؟" : L==LANG_AR ? "تحديث الآن؟" : L==LANG_TR ? "Güncelle?" : "Update now?");
   if(key == "updating")
      return(L==LANG_FA ? "در حال به‌روزرسانی..." : L==LANG_AR ? "جاري التحديث..." : L==LANG_TR ? "Güncelleniyor..." : "Updating...");
   if(key == "real_unsupported")
      return(L==LANG_FA ? "حساب واقعی فعلاً پشتیبانی نمی‌شود" : L==LANG_AR ? "الحساب الحقيقي غير مدعوم بعد" : L==LANG_TR ? "Gerçek hesap henüz desteklenmiyor" : "Real account not supported yet");
   if(key == "safe_disconnect")
      return(L==LANG_FA ? "قطع ایمن — فقط مدیریت پوزیشن‌ها" : L==LANG_AR ? "فصل آمن — إدارة الصفقات فقط" : L==LANG_TR ? "Güvenli kopuş — yalnızca pozisyon yönetimi" : "SAFE DISCONNECT - managing only");
   if(key == "detected")
      return(L==LANG_FA ? "تشخیص" : L==LANG_AR ? "اكتشاف" : L==LANG_TR ? "Algılanan" : "Detected");
   if(key == "rehearsal")
      return(L==LANG_FA ? "تمرین" : L==LANG_AR ? "تدريب" : L==LANG_TR ? "Prova" : "REHEARSAL");
   if(key == "auto_tag")
      return(L==LANG_FA ? "خودکار" : L==LANG_AR ? "تلقائي" : L==LANG_TR ? "otomatik" : "auto");
   if(key == "manual_tag")
      return(L==LANG_FA ? "دستی" : L==LANG_AR ? "يدوي" : L==LANG_TR ? "manuel" : "manual");
   if(key == "manual_override")
      return(L==LANG_FA ? "بازنویسی دستی" : L==LANG_AR ? "تجاوز يدوي" : L==LANG_TR ? "manuel geçersiz kılma" : "manual override");
   if(key == "on")
      return(L==LANG_FA ? "روشن" : L==LANG_AR ? "تشغيل" : L==LANG_TR ? "AÇIK" : "ON");
   if(key == "off")
      return(L==LANG_FA ? "خاموش" : L==LANG_AR ? "إيقاف" : L==LANG_TR ? "KAPALI" : "off");
   if(key == "link")
      return(L==LANG_FA ? "ارتباط" : L==LANG_AR ? "الاتصال" : L==LANG_TR ? "Bağlantı" : "Link");
   if(key == "demo")
      return(L==LANG_FA ? "دمو" : L==LANG_AR ? "تجريبي" : L==LANG_TR ? "Demo" : "Demo");
   if(key == "live")
      return(L==LANG_FA ? "واقعی" : L==LANG_AR ? "حقيقي" : L==LANG_TR ? "Canlı" : "LIVE");
   return(key);
  }

#endif

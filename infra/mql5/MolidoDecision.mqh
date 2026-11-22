//+------------------------------------------------------------------+
//| MolidoDecision.mqh - Molido Expert 3.0 analysis modules and the  |
//| smart decision layer. Additive; every module defaults OFF.       |
//|  Market Analysis : multi-timeframe EMA50/200 confluence (M15/H1/ |
//|                    H4) + H1 ADX/ATR regime + server "analysis"   |
//|  News Analysis   : MT5 calendar high-impact window = veto        |
//|  Sentiment       : server bridge "sentiment" field only          |
//|  Opportunity Hunt: ranks the traded universe by confluence and   |
//|                    allows entries only on the top-K symbols      |
//|  Decision layer  : weighted score of strategy + modules + regime |
//|                    fit; Risk Brain review always runs after it   |
//|                    and keeps the final veto.                     |
//| Missing data never creates a trade: the module votes WAIT (0).   |
//| Rules and status: docs/smc-rocket-fa.md                          |
//+------------------------------------------------------------------+
#ifndef MOLIDO_DECISION_MQH
#define MOLIDO_DECISION_MQH

input group "Expert 3.0 analysis modules + decision layer (default off)"
input bool   InpUseMarketAnalysis = false; // Market Analysis: MTF EMA50/200 confluence + regime
input bool   InpUseNewsAnalysis   = false; // News Analysis: high-impact calendar window = WAIT
input bool   InpUseSentiment      = false; // Sentiment: server bridge field (WAIT when missing)
input bool   InpUseOpportunity    = false; // Opportunity Hunting: only top-K ranked symbols
input bool   InpUseDecisionLayer  = false; // Final decision: weighted score gate
input bool   InpAutoPilot         = false; // 3.0 auto: pick strategies by regime (manual toggles ignored while on)
input double InpDecMinScore       = 0.5;   // decision: minimum weighted score
input double InpDecWMarket        = 1.0;   // weight: Market Analysis vote (-1..+1)
input double InpDecWSentiment     = 0.5;   // weight: Sentiment vote
input double InpDecWRegime        = 0.5;   // weight: strategy/regime fit (-1..+1)
input int    InpOppTopK           = 3;     // Opportunity: number of symbols allowed
input int    InpRegimeAdxTrend    = 25;    // H1 ADX >= this = trend regime
input int    InpRegimeAdxRange    = 18;    // H1 ADX <= this = range regime
input bool   InpSmcKillzones      = false; // ICT killzones for SMC/Rocket entries (London 7-10, NY 12-15 GMT)

bool   g_md_market = false, g_md_news = false, g_md_sent = false, g_md_opp = false, g_md_dec = false;
bool   g_md_sp2l = false, g_md_fvg = false;
string g_mx_last_strat = "";      // which strategy produced the current candidate
string g_md_last = "";            // last decision text for the dashboard/log
double g_md_last_score = 0.0;
string g_md_ai_analysis = "";     // set by MolidoExpertBridge when the server link is up
string g_md_ai_sentiment = "";
bool   g_md_ai_linked = false;


//--- runtime toggles (GV-persisted outside the tester) ---------------------------
bool MdGv(const string k, const bool def)
  {
   if(MQLInfoInteger(MQL_TESTER) || !GlobalVariableCheck(k)) return(def);
   return(GlobalVariableGet(k) > 0.5);
  }
void MdSetGv(const string k, const bool on)
  {
   if(!MQLInfoInteger(MQL_TESTER)) GlobalVariableSet(k, on ? 1.0 : 0.0);
  }
void MdInit()
  {
   g_md_market = MdGv("Molido.Mod.Market", InpUseMarketAnalysis);
   g_md_news   = MdGv("Molido.Mod.News", InpUseNewsAnalysis);
   g_md_sent   = MdGv("Molido.Mod.Sentiment", InpUseSentiment);
   g_md_opp    = MdGv("Molido.Mod.Opportunity", InpUseOpportunity);
   g_md_dec    = MdGv("Molido.Mod.Decision", InpUseDecisionLayer);
   g_md_sp2l   = MdGv("Molido.Mod.SP2L", InpUseSP2LFilter);
   g_md_fvg    = MdGv("Molido.Mod.FVG", InpUseFVGFilter);
  }
bool MdUseMarket()   { return(g_md_market); }
bool MdUseNews()     { return(g_md_news); }
bool MdUseSent()     { return(g_md_sent); }
bool MdUseOpp()      { return(g_md_opp); }
bool MdUseDecision() { return(g_md_dec); }
bool MxUseSp2l()     { return(g_md_sp2l); }
bool MxUseFvg()      { return(g_md_fvg); }
void MdToggle(const string id)
  {
   if(id == "market")  { g_md_market = !g_md_market; MdSetGv("Molido.Mod.Market", g_md_market); }
   if(id == "news")    { g_md_news = !g_md_news;     MdSetGv("Molido.Mod.News", g_md_news); }
   if(id == "sent")    { g_md_sent = !g_md_sent;     MdSetGv("Molido.Mod.Sentiment", g_md_sent); }
   if(id == "opp")     { g_md_opp = !g_md_opp;       MdSetGv("Molido.Mod.Opportunity", g_md_opp); }
   if(id == "dec")     { g_md_dec = !g_md_dec;       MdSetGv("Molido.Mod.Decision", g_md_dec); }
   if(id == "sp2l")    { g_md_sp2l = !g_md_sp2l;     MdSetGv("Molido.Mod.SP2L", g_md_sp2l); }
   if(id == "fvg")     { g_md_fvg = !g_md_fvg;       MdSetGv("Molido.Mod.FVG", g_md_fvg); }
  }
//--- dashboard analysis buttons ag0..ag7 -> module id ("" = display only)
string MdAgModule(const int i)
  {
   if(i == 0) return("market");
   if(i == 1) return("news");
   if(i == 3) return("sent");
   if(i == 4) return("opp");
   if(i == 7) return("dec");
   return("");
  }
bool MdAgOn(const int i)
  {
   string m = MdAgModule(i);
   if(m == "market") return(g_md_market);
   if(m == "news")   return(g_md_news);
   if(m == "sent")   return(g_md_sent);
   if(m == "opp")    return(g_md_opp);
   if(m == "dec")    return(g_md_dec);
   return(false);
  }

//--- indicator helpers (handles cached per symbol/tf) ----------------------------
double MdBuf(const int h, const int buf, const int shift)
  {
   if(h == INVALID_HANDLE) return(0.0);
   double v[];
   if(CopyBuffer(h, buf, shift, 1, v) != 1) return(0.0);
   return(v[0]);
  }
double MdEma(const string s, const ENUM_TIMEFRAMES tf, const int p)
  {
   int h = iMA(s, tf, p, 0, MODE_EMA, PRICE_CLOSE);
   return(MdBuf(h, 0, 1));
  }
double MdAdx(const string s, const ENUM_TIMEFRAMES tf)
  {
   int h = iADX(s, tf, 14);
   return(MdBuf(h, 0, 1));
  }
double MdAtrRatio(const string s, const ENUM_TIMEFRAMES tf)
  {
   int h = iATR(s, tf, 14);
   if(h == INVALID_HANDLE) return(0.0);
   double v[];
   if(CopyBuffer(h, 0, 1, 100, v) != 100) return(0.0);
   double avg = 0.0;
   for(int i = 0; i < 100; i++) avg += v[i];
   avg /= 100.0;
   return(avg > 0.0 ? v[99] / avg : 0.0);
  }

//--- regime: +1 trend, 0 normal, -1 range, -2 missing / extreme volatility
int MdRegime(const string s, string &txt)
  {
   double adx = MdAdx(s, PERIOD_H1);
   double ar = MdAtrRatio(s, PERIOD_H1);
   if(adx <= 0.0 || ar <= 0.0) { txt = "regime: missing"; return(-2); }
   if(ar > 2.5) { txt = "regime: extreme volatility (ATR " + DoubleToString(ar, 1) + "x)"; return(-2); }
   if(adx >= InpRegimeAdxTrend) { txt = "regime: trend ADX " + DoubleToString(adx, 0); return(1); }
   if(adx <= InpRegimeAdxRange) { txt = "regime: range ADX " + DoubleToString(adx, 0); return(-1); }
   txt = "regime: normal ADX " + DoubleToString(adx, 0);
   return(0);
  }

//--- Market Analysis vote for side: mean of M15/H1/H4 EMA50/200 + close>EMA50 alignment
double MdMarketVote(const string s, const string side, bool &ok)
  {
   ENUM_TIMEFRAMES tfs[3] = {PERIOD_M15, PERIOD_H1, PERIOD_H4};
   double sum = 0.0;
   int n = 0;
   for(int i = 0; i < 3; i++)
     {
      double f = MdEma(s, tfs[i], 50), sl = MdEma(s, tfs[i], 200), c = iClose(s, tfs[i], 1);
      if(f <= 0.0 || sl <= 0.0 || c <= 0.0) continue;
      int v = 0;
      if(f > sl && c > f) v = 1;
      else if(f < sl && c < f) v = -1;
      sum += v;
      n++;
     }
   ok = (n == 3);
   if(!ok) return(0.0);
   double vote = sum / 3.0;
   return(side == "buy" ? vote : -vote);
  }

//--- server bridge text votes ("buy"/"bull" vs "sell"/"bear"), 0 when missing
double MdTextVote(const string t, const string side)
  {
   string u = t;
   StringToLower(u);
   int b = (StringFind(u, "buy") >= 0 || StringFind(u, "bull") >= 0 || StringFind(u, "long") >= 0) ? 1 : 0;
   int s = (StringFind(u, "sell") >= 0 || StringFind(u, "bear") >= 0 || StringFind(u, "short") >= 0) ? 1 : 0;
   double v = (double)(b - s);
   return(side == "buy" ? v : -v);
  }

bool MdInKillzone()
  {
   MqlDateTime d;
   TimeToStruct(ExpertGmtNow(), d);
   return((d.hour >= 7 && d.hour < 10) || (d.hour >= 12 && d.hour < 15));
  }

//--- News Analysis: MT5 calendar high-impact event for the symbol currencies within
//--- ExpertNewsMinsBefore/After. Independent of ExpertUseNewsFilter. Empty calendar
//--- (tester or no feed) = no veto, reported as "no calendar data".
bool ExpertNewsBlockedAny(const string symbol, string &why)
  {
   int before = (ExpertNewsMinsBefore > 0 ? ExpertNewsMinsBefore : 30);
   int after  = (ExpertNewsMinsAfter > 0 ? ExpertNewsMinsAfter : 30);
   datetime now = TimeGMT();
   MqlCalendarValue values[];
   int got = CalendarValueHistory(values, now - after * 60, now + before * 60, NULL, NULL);
   if(got <= 0) { why = "no calendar data"; return(false); }
   for(int i = 0; i < got; i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev) || ev.importance < CALENDAR_IMPORTANCE_HIGH) continue;
      MqlCalendarCountry co;
      string cur = "";
      if(CalendarCountryById(ev.country_id, co)) cur = co.currency;
      if(!ExpertCurrencyMatch(symbol, cur)) continue;
      why = "high-impact " + cur + " " + ev.name;
      return(true);
     }
   return(false);
  }

//--- strategy kind vs regime: trend-type in trend +1, scalper in range +1, mismatch -1
double MdRegimeFit(const string strat, const int regime)
  {
   bool trendy = (strat == "trend" || strat == "rocket" || strat == "smc");
   if(regime == 1)  return(trendy ? 1.0 : -0.5);
   if(regime == -1) return(trendy ? -0.5 : 1.0);
   return(0.0);
  }

//--- AutoPilot: which strategies may run for this symbol right now
void MdAutoPick(const string s, bool &smc, bool &rk, bool &trend, bool &scalp)
  {
   string t;
   int r = MdRegime(s, t);
   smc = false; rk = false; trend = false; scalp = false;
   if(r == -2) return;                  // missing data or extreme volatility: WAIT
   if(r == 1)  { smc = true; rk = true; trend = true; return; }
   if(r == -1) { smc = true; scalp = true; return; }
   smc = true; rk = true; trend = true; // normal regime
  }

//--- Opportunity Hunting: confluence rank of the symbol inside the traded universe
string g_md_opp_syms[];
datetime g_md_opp_bar = 0;
double MdOppScore(const string s)
  {
   bool ok;
   double m = MathAbs(MdMarketVote(s, "buy", ok));
   if(!ok) return(-1.0);
   string t;
   int r = MdRegime(s, t);
   if(r == -2) return(-1.0);
   return(m + (r == 1 ? 0.5 : 0.0));
  }
bool MdOppAllows(const string s, const string &universe[], const int n, string &why)
  {
   datetime bar = iTime(_Symbol, PERIOD_M15, 0);
   if(bar != g_md_opp_bar || ArraySize(g_md_opp_syms) == 0)
     {
      g_md_opp_bar = bar;
      double sc[]; string nm[];
      ArrayResize(sc, n); ArrayResize(nm, n);
      for(int i = 0; i < n; i++) { nm[i] = universe[i]; sc[i] = MdOppScore(universe[i]); }
      for(int i = 0; i < n; i++)
         for(int j = i + 1; j < n; j++)
            if(sc[j] > sc[i]) { double a = sc[i]; sc[i] = sc[j]; sc[j] = a; string b = nm[i]; nm[i] = nm[j]; nm[j] = b; }
      int k = MathMax(1, MathMin(InpOppTopK, n));
      ArrayResize(g_md_opp_syms, 0);
      for(int i = 0; i < k; i++)
         if(sc[i] >= 0.0) { int m = ArraySize(g_md_opp_syms); ArrayResize(g_md_opp_syms, m + 1); g_md_opp_syms[m] = nm[i]; }
     }
   for(int i = 0; i < ArraySize(g_md_opp_syms); i++)
      if(g_md_opp_syms[i] == s) return(true);
   why = "Opportunity: " + s + " not in top " + IntegerToString(InpOppTopK);
   return(false);
  }

//--- the decision gate: true = pass to Protect/Risk Brain/Expert policy -----------
bool MdDecide(const string s, const string side, const string &universe[], const int n, string &why)
  {
   why = "";
   string ai_analysis = g_md_ai_analysis, ai_sentiment = g_md_ai_sentiment;
   bool ai_linked = g_md_ai_linked;
   string rtxt;
   int regime = MdRegime(s, rtxt);
   if((g_mx_last_strat == "smc" || g_mx_last_strat == "rocket") && InpSmcKillzones && !MdInKillzone())
     { why = "killzone: outside London/NY window"; return(false); }
   if(g_md_news)
     {
      string nw;
      if(ExpertNewsBlockedAny(s, nw)) { why = "News Analysis WAIT: " + nw; return(false); }
     }
   if(g_md_opp && !MdOppAllows(s, universe, n, why))
      return(false);
   double score = 1.0;             // the strategy candidate itself
   string parts = g_mx_last_strat + "=1";
   bool mok = true;
   double mv = 0.0;
   if(g_md_market)
     {
      mv = MdMarketVote(s, side, mok);
      if(ai_linked && StringLen(ai_analysis) > 0) mv = 0.75 * mv + 0.25 * MdTextVote(ai_analysis, side);
      if(!mok && !g_md_dec) { why = "Market Analysis WAIT: missing MTF data"; return(false); }
      if(!g_md_dec && mv < 0.0) { why = "Market Analysis against " + side + " (" + DoubleToString(mv, 2) + ")"; return(false); }
      score += InpDecWMarket * mv;
      parts += " mk=" + DoubleToString(mv, 2);
     }
   if(g_md_sent)
     {
      double sv = (ai_linked && StringLen(ai_sentiment) > 0) ? MdTextVote(ai_sentiment, side) : 0.0;
      if(!g_md_dec && sv < 0.0) { why = "Sentiment against " + side; return(false); }
      score += InpDecWSentiment * sv;
      parts += " se=" + DoubleToString(sv, 1) + (ai_linked && StringLen(ai_sentiment) > 0 ? "" : "(WAIT:no feed)");
     }
   double fit = MdRegimeFit(g_mx_last_strat, regime);
   score += InpDecWRegime * fit;
   parts += " fit=" + DoubleToString(fit, 1) + " " + rtxt;
   g_md_last_score = score;
   g_md_last = "score " + DoubleToString(score, 2) + " [" + parts + "]";
   if(g_md_dec)
     {
      if(regime == -2) { why = "Decision WAIT: " + rtxt; return(false); }
      if(!mok) { why = "Decision WAIT: missing MTF data"; return(false); }
      if(score < InpDecMinScore) { why = "Decision " + g_md_last + " < " + DoubleToString(InpDecMinScore, 2); return(false); }
     }
   return(true);
  }

#endif

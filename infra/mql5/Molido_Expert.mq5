//+------------------------------------------------------------------+
//| Molido_Expert.mq5 - Molido Expert – AI Trading Power v2.3        |
//| Upgrade of Molido_Master: same safety, auto-detect, real block.  |
//+------------------------------------------------------------------+
#property copyright   "MolidoTrade AI"
#property version     "2.30"
#property description "Molido Expert – AI Trading Power. Demo only; real accounts blocked."
#define MOLIDO_EXPERT_UI
#define MOLIDO_EA_NAME          "Molido_Expert"
#define MOLIDO_MAGIC            685409
#define MOLIDO_DEFAULT_PROFILE  PROFILE_AUTO
#define MOLIDO_DEFAULT_STRATEGY STRAT_AUTO
#define MOLIDO_DEFAULT_AUTO     true
#define MOLIDO_DEFAULT_NEWS     NEWS_AVOID
#define MOLIDO_DEFAULT_TOPN     5
#define MOLIDO_USE_SCALPER      true
#define MOLIDO_USE_NEWS         false
#define MOLIDO_USE_TREND        true
#define MOLIDO_USE_AUTO         true
#define MOLIDO_DEFAULT_REHEARSAL true
#define MOLIDO_USE_FIBO         false
#define MOLIDO_REAL_SUPPORTED   false
#define MOLIDO_EA_VERSION       "2.30"
//--- Expert 2.30 safety (demo). These only tighten shared Risk Brain caps.
input group "Expert 2.30 safety"
input double ExpertMetalRiskPct         = 0.15;  // XAU/XAG risk % (never above the 0.5% hard cap)
input bool   ExpertBlockMetalsInLondon  = true;  // block new metal entries in London
input int    ExpertMetalLondonOpenGMT   = 7;
input int    ExpertMetalLondonCloseGMT  = 16;
input double ExpertMaxLossPct           = 0.25;  // per-trade loss cap, % of balance
input double ExpertMaxLossUsd           = 300.0; // per-trade loss cap, USD
input double ExpertMaxLots              = 0.50;  // overall Expert lot ceiling
input double ExpertMaxLotsMetal         = 0.20;
input double ExpertMaxLotsIndex         = 0.50;
input double ExpertMaxLotsFx            = 0.50;
input bool   ExpertUsePartialTP         = false; // default off: take full TP
input bool   ExpertUseTrailing          = false;
input bool   ExpertUseBreakEven         = false;
input double ExpertMinTpR               = 1.5;   // require TP >= this R
input bool   ExpertSingleInstance       = true;  // one Molido_Expert per account
input group "Expert 2.30 quality"
input bool   ExpertUseTrendFilter       = true;  // only with H1/H4 EMA trend
input int    ExpertTrendFastEma         = 50;
input int    ExpertTrendSlowEma         = 200;
input bool   ExpertTrendRequireBoth     = true;  // H1 and H4 must agree
input bool   ExpertUseSpreadFilter      = true;
input double ExpertMaxSpreadAtrFrac     = 0.10;  // block if spread > this fraction of ATR
input int    ExpertMaxSpreadPts         = 0;     // 0 = off; extra cap in points
input bool   ExpertUseAtrFilter         = true;
input double ExpertAtrMinMult           = 0.50;  // skip if ATR < this * average ATR
input double ExpertAtrMaxMult           = 2.00;  // skip if ATR > this * average ATR
input int    ExpertAtrAvgBars           = 50;
input bool   ExpertUseNewsFilter        = false; // off by default: calendar feed is often empty
input int    ExpertNewsMinsBefore       = 30;
input int    ExpertNewsMinsAfter        = 30;
input bool   ExpertUseBeAtR             = true;  // move SL to break-even at +1R
input double ExpertBreakEvenR           = 1.0;
input bool   ExpertUseAtrTrail          = true;  // modest ATR trail after +1.5R; TP stays
input double ExpertTrailStartR          = 1.5;
input double ExpertTrailAtrMult         = 1.0;
input int    ExpertSafeModeCooldownHours= 24;    // also clear this many hours after a stop
input group "Expert 2.30 V2 confirmation (optional, default off)"
input bool   InpUseSP2LFilter           = false; // confirm with SP2L structure (closed bars)
input bool   InpUseFVGFilter            = false; // confirm with unmitigated FVG reaction
#include "MolidoRuntime.mqh"

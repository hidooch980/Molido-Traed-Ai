//+------------------------------------------------------------------+
//| Molido_Expert.mq5 - Molido Expert – AI Trading Power v2.0        |
//| Upgrade of Molido_Master: same safety, auto-detect, real block.  |
//+------------------------------------------------------------------+
#property copyright   "MolidoTrade AI"
#property version     "2.10"
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
#define MOLIDO_EA_VERSION       "2.10"
#include "MolidoRuntime.mqh"

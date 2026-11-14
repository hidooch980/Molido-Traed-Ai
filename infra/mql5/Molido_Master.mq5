//+------------------------------------------------------------------+
//| Molido_Master.mq5 - Molido Master: one EA, automatic account type, no real-account trading yet
//+------------------------------------------------------------------+
#property copyright   "MolidoTrade AI"
#property version     "1.45"
#property description "Molido Master: one EA, automatic account type, no real-account trading yet"
#define MOLIDO_EA_NAME          "Molido_Master"
#define MOLIDO_MAGIC            685408
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
#define MOLIDO_EA_VERSION       "1.45"
#include "MolidoRuntime.mqh"

//+------------------------------------------------------------------+
//| Molido_Live.mq5 - Molido Live: real account (hard-locked until unlocked)
//+------------------------------------------------------------------+
#property copyright   "MolidoTrade AI"
#property version     "1.46"
#property description "Molido Live: real account (hard-locked until unlocked)"
#define MOLIDO_EA_NAME          "Molido_Live"
#define MOLIDO_MAGIC            685403
#define MOLIDO_DEFAULT_PROFILE  PROFILE_LIVE_REAL
#define MOLIDO_DEFAULT_STRATEGY STRAT_SCALPER
#define MOLIDO_DEFAULT_AUTO     true
#define MOLIDO_DEFAULT_NEWS     NEWS_AVOID
#define MOLIDO_DEFAULT_TOPN     3
#define MOLIDO_USE_SCALPER      true
#define MOLIDO_USE_NEWS         false
#define MOLIDO_USE_TREND        false
#define MOLIDO_USE_AUTO         true
#define MOLIDO_DEFAULT_REHEARSAL false
#define MOLIDO_REAL_SUPPORTED   true
#define MOLIDO_EA_VERSION       "1.46"
#include "MolidoRuntime.mqh"

//+------------------------------------------------------------------+
//| Molido_Prop.mq5 - Molido Prop: FTMO/generic challenge, conservative DD protection
//+------------------------------------------------------------------+
#property copyright   "MolidoTrade AI"
#property version     "1.46"
#property description "Molido Prop: FTMO/generic challenge, conservative DD protection"
#define MOLIDO_EA_NAME          "Molido_Prop"
#define MOLIDO_MAGIC            685402
#define MOLIDO_DEFAULT_PROFILE  PROFILE_PROP_FTMO
#define MOLIDO_DEFAULT_STRATEGY STRAT_SCALPER
#define MOLIDO_DEFAULT_AUTO     true
#define MOLIDO_DEFAULT_NEWS     NEWS_AVOID
#define MOLIDO_DEFAULT_TOPN     3
#define MOLIDO_USE_SCALPER      true
#define MOLIDO_USE_NEWS         false
#define MOLIDO_USE_TREND        false
#define MOLIDO_USE_AUTO         true
#define MOLIDO_DEFAULT_REHEARSAL true
#define MOLIDO_EA_VERSION       "1.46"
#include "MolidoRuntime.mqh"

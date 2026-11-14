//+------------------------------------------------------------------+
//| MolidoShared.mqh - magic numbers, identity, account coordinator  |
//| (GlobalVariables). Compiled into every Molido EA.                |
//+------------------------------------------------------------------+
#ifndef MOLIDO_SHARED_MQH
#define MOLIDO_SHARED_MQH

#define MOLIDO_MAGIC_BRIDGE   685317
#define MOLIDO_MAGIC_DEMO     685401
#define MOLIDO_MAGIC_PROP     685402
#define MOLIDO_MAGIC_LIVE     685403
#define MOLIDO_MAGIC_SCALPER  685404
#define MOLIDO_MAGIC_NEWS     685405
#define MOLIDO_MAGIC_TREND    685406
#define MOLIDO_MAGIC_AUTO     685407
#define MOLIDO_MAGIC_MASTER   685408
#define MOLIDO_MAGIC_EXPERT   685409

#ifndef MOLIDO_MAGIC
#define MOLIDO_MAGIC MOLIDO_MAGIC_BRIDGE
#endif
#ifndef MOLIDO_EA_NAME
#define MOLIDO_EA_NAME "MolidoBridge"
#endif
#ifndef MOLIDO_EA_VERSION
#define MOLIDO_EA_VERSION "1.46"
#endif
#ifndef MOLIDO_DEFAULT_PROFILE
#define MOLIDO_DEFAULT_PROFILE PROFILE_DEMO
#endif
#ifndef MOLIDO_DEFAULT_STRATEGY
#define MOLIDO_DEFAULT_STRATEGY STRAT_SCALPER
#endif
#ifndef MOLIDO_DEFAULT_AUTO
#define MOLIDO_DEFAULT_AUTO true
#endif
#ifndef MOLIDO_DEFAULT_NEWS
#define MOLIDO_DEFAULT_NEWS NEWS_AVOID
#endif
#ifndef MOLIDO_DEFAULT_TOPN
#define MOLIDO_DEFAULT_TOPN 3
#endif
#ifndef MOLIDO_USE_SCALPER
#define MOLIDO_USE_SCALPER true
#endif
#ifndef MOLIDO_USE_NEWS
#define MOLIDO_USE_NEWS false
#endif
#ifndef MOLIDO_USE_TREND
#define MOLIDO_USE_TREND false
#endif
#ifndef MOLIDO_USE_AUTO
#define MOLIDO_USE_AUTO MOLIDO_DEFAULT_AUTO
#endif
#ifndef MOLIDO_DEFAULT_REHEARSAL
#define MOLIDO_DEFAULT_REHEARSAL false
#endif
#ifndef MOLIDO_USE_FIBO
#define MOLIDO_USE_FIBO false
#endif
#ifndef MOLIDO_REAL_SUPPORTED
#define MOLIDO_REAL_SUPPORTED false
#endif

#define DEMO_SCALPER_MAGIC    MOLIDO_MAGIC

bool MolidoIsTester()
  {
   return(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION)
          || MQLInfoInteger(MQL_FORWARD));
  }

#define COORD_LOCK  "Molido.Coord.Lock"
#define COORD_POS   "Molido.Coord.Positions"
#define COORD_LOTS  "Molido.Coord.Lots"
#define COORD_EA    "Molido.Coord.EA."

bool IsMolidoMagic(const long magic)
  {
   if(magic == MOLIDO_MAGIC) return(true);
   if(magic == MOLIDO_MAGIC_BRIDGE) return(true);
   if(magic == MOLIDO_MAGIC_DEMO) return(true);
   if(magic == MOLIDO_MAGIC_PROP) return(true);
   if(magic == MOLIDO_MAGIC_LIVE) return(true);
   if(magic == MOLIDO_MAGIC_SCALPER) return(true);
   if(magic == MOLIDO_MAGIC_NEWS) return(true);
   if(magic == MOLIDO_MAGIC_TREND) return(true);
   if(magic == MOLIDO_MAGIC_AUTO) return(true);
   if(magic == MOLIDO_MAGIC_MASTER) return(true);
   if(magic == MOLIDO_MAGIC_EXPERT) return(true);
   return(false);
  }

int CoordCountPositions(double &lots)
  {
   lots = 0.0;
   int count = 0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(!IsMolidoMagic((long)PositionGetInteger(POSITION_MAGIC)))
         continue;
      count++;
      lots += PositionGetDouble(POSITION_VOLUME);
     }
   GlobalVariableSet(COORD_POS, (double)count);
   GlobalVariableSet(COORD_LOTS, lots);
   GlobalVariableSet(COORD_EA + IntegerToString(MOLIDO_MAGIC), (double)count);
   return(count);
  }

int CoordOpenCount()
  {
   double lots = 0.0;
   return(CoordCountPositions(lots));
  }

bool CoordCanOpen(const int cap)
  {
   if(cap <= 0)
      return(false);
   return(CoordOpenCount() < cap);
  }

bool CoordLock()
  {
   datetime now = TimeCurrent();
   if(GlobalVariableCheck(COORD_LOCK))
     {
      double until = GlobalVariableGet(COORD_LOCK);
      if(until > (double)now)
         return(false);
     }
   GlobalVariableSet(COORD_LOCK, (double)(now + 3));
   return(true);
  }

void CoordUnlock()
  {
   if(GlobalVariableCheck(COORD_LOCK))
      GlobalVariableDel(COORD_LOCK);
  }

#endif

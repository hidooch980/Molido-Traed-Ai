//+------------------------------------------------------------------+
//| MolidoExpertRisk.mqh - Balanced risk profile for Expert UI.      |
//| Never loosens hard caps from the shared Risk Brain.              |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_RISK_MQH
#define MOLIDO_EXPERT_RISK_MQH

enum ENUM_EXPERT_RISK
  {
   EXP_RISK_CONSERVATIVE = 0,
   EXP_RISK_BALANCED     = 1,
   EXP_RISK_AGGRESSIVE   = 2
  };

ENUM_EXPERT_RISK g_ex_risk_mode = EXP_RISK_BALANCED;

string ExpertRiskName()
  {
   if(g_ex_risk_mode == EXP_RISK_CONSERVATIVE)
      return("Conservative");
   if(g_ex_risk_mode == EXP_RISK_AGGRESSIVE)
      return("Aggressive");
   return("Balanced");
  }

//--- UI risk% may only tighten the active profile cap, never loosen it.
double ExpertRiskPctCap(const double ui_pct)
  {
   double cap = DemoActiveRiskPct();
   double v = ui_pct;
   if(v <= 0.0)
      v = cap;
   if(g_ex_risk_mode == EXP_RISK_CONSERVATIVE)
      v = MathMin(v, cap * 0.6);
   else if(g_ex_risk_mode == EXP_RISK_AGGRESSIVE)
      v = MathMin(v, cap);  // still cannot exceed the hard cap
   if(v > cap)
      v = cap;
   if(v < 0.05)
      v = 0.05;
   return(v);
  }

int ExpertMaxPosCap(const int ui_n)
  {
   int cap = DemoActiveMaxPositions();
   int n = ui_n;
   if(n <= 0)
      n = cap;
   if(n > cap)
      n = cap;
   if(n < 1)
      n = 1;
   return(n);
  }

#endif

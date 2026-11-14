//+------------------------------------------------------------------+
//| MolidoExpertReport.mqh - live account and history reporting.     |
//| Figures come from the terminal only; empty history => "no data". |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_REPORT_MQH
#define MOLIDO_EXPERT_REPORT_MQH

struct ExpertPerf
  {
   int    trades;
   int    wins;
   int    losses;
   double winpct;
   double pnl;
   double avg_win;
   double avg_loss;
   double max_dd;
   bool   has_data;
  };

struct ExpertReport
  {
   int    today_trades;
   double today_pnl;
   double week_pnl;
   double month_pnl;
   double balance;
   double equity;
   double free_margin;
   int    open_count;
   int    history_trades;
  };

bool ExpertIsOurs(const long magic, const string comment)
  {
   if(IsMolidoMagic(magic))
      return(true);
   if(StringFind(comment, "molido") == 0)
      return(true);
   return(false);
  }

datetime ExpertDayStart(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return(StructToTime(dt));
  }

void ExpertPerfReset(ExpertPerf &p)
  {
   p.trades = 0; p.wins = 0; p.losses = 0;
   p.winpct = 0; p.pnl = 0; p.avg_win = 0; p.avg_loss = 0;
   p.max_dd = 0; p.has_data = false;
  }

void ExpertScanHistory(ExpertPerf &perf, ExpertReport &rep)
  {
   ExpertPerfReset(perf);
   ZeroMemory(rep);
   rep.balance = AccountInfoDouble(ACCOUNT_BALANCE);
   rep.equity = AccountInfoDouble(ACCOUNT_EQUITY);
   rep.free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   int open_n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!ExpertIsOurs(PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_COMMENT)))
         continue;
      open_n++;
     }
   rep.open_count = open_n;

   datetime now = TimeCurrent();
   datetime day0 = ExpertDayStart(now);
   MqlDateTime dt;
   TimeToStruct(now, dt);
   int dow = (int)dt.day_of_week;  // 0=Sun
   int since_mon = (dow == 0 ? 6 : dow - 1);
   datetime week0 = day0 - since_mon * 86400;
   dt.day = 1; dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime month0 = StructToTime(dt);

   if(!HistorySelect(now - 400 * 86400, now + 60))
      return;

   double eq = 0.0, peak = 0.0, maxdd = 0.0;
   double win_sum = 0.0, loss_sum = 0.0;
   int deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT &&
         HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT_BY)
         continue;
      long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
      string comment = HistoryDealGetString(ticket, DEAL_COMMENT);
      if(!ExpertIsOurs(magic, comment))
         continue;
      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT) +
                   HistoryDealGetDouble(ticket, DEAL_SWAP) +
                   HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      perf.trades++;
      perf.pnl += pnl;
      if(pnl >= 0.0) { perf.wins++; win_sum += pnl; }
      else { perf.losses++; loss_sum += pnl; }
      eq += pnl;
      if(eq > peak) peak = eq;
      double dd = peak - eq;
      if(dd > maxdd) maxdd = dd;
      if(t >= day0) { rep.today_trades++; rep.today_pnl += pnl; }
      if(t >= week0) rep.week_pnl += pnl;
      if(t >= month0) rep.month_pnl += pnl;
     }
   rep.history_trades = perf.trades;
   if(perf.trades <= 0)
      return;
   perf.has_data = true;
   perf.winpct = 100.0 * perf.wins / perf.trades;
   if(perf.wins > 0) perf.avg_win = win_sum / perf.wins;
   if(perf.losses > 0) perf.avg_loss = loss_sum / perf.losses;
   if(rep.balance > 0.0)
      perf.max_dd = 100.0 * maxdd / rep.balance;
   else
      perf.max_dd = maxdd;
  }

string ExpertMoney(const double v)
  {
   return((v >= 0.0 ? "+" : "") + DoubleToString(v, 2));
  }

#endif

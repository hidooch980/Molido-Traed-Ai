//+------------------------------------------------------------------+
//| MolidoExpertBridge.mqh - AI file/WebRequest bridge.              |
//| Token is never hardcoded: input or Common Files token file.      |
//+------------------------------------------------------------------+
#ifndef MOLIDO_EXPERT_BRIDGE_MQH
#define MOLIDO_EXPERT_BRIDGE_MQH

input group "Advanced (no need to change)"
input string AiBridgeUrl   = "";  // optional HTTPS status URL (Allow WebRequest)
input string AiBridgeToken = "";  // empty = read Common Files molido_ai_token.txt
input int    AiStaleSec    = 180; // status older than this => Disconnected

#define AI_STATUS_FILE  "molido_ai_status.json"
#define AI_SIGNAL_FILE  "molido_ai_signals.json"
#define AI_TOKEN_FILE   "molido_ai_token.txt"
#define AI_SEEN_FILE    "molido_ai_seen.txt"
#define AI_AGENT_CAP    51
#define AI_SEEN_MAX     64

bool     g_ai_connected      = false;
int      g_ai_agents_on      = 0;
int      g_ai_agents_total   = AI_AGENT_CAP;
string   g_ai_mode           = "HYBRID";
string   g_ai_council        = "";
string   g_ai_analysis       = "";
string   g_ai_learning       = "";
string   g_ai_risk           = "";
string   g_ai_reason         = "no link";
datetime g_ai_last_ok        = 0;
string   g_ai_groups[11];
string   g_ai_group_st[11];
string   g_ai_seen[AI_SEEN_MAX];
int      g_ai_seen_n         = 0;

string ExpertToken()
  {
   if(StringLen(AiBridgeToken) > 0)
      return(AiBridgeToken);
   int h = FileOpen(AI_TOKEN_FILE, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return("");
   string t = FileReadString(h);
   FileClose(h);
   StringTrimLeft(t);
   StringTrimRight(t);
   return(t);
  }

string AiJsonString(const string body, const string key)
  {
   string pat = "\"" + key + "\"";
   int at = StringFind(body, pat);
   if(at < 0)
      return("");
   int c = StringFind(body, ":", at);
   if(c < 0)
      return("");
   int i = c + 1;
   int n = StringLen(body);
   while(i < n && (StringGetCharacter(body, i) == ' ' || StringGetCharacter(body, i) == '\t'))
      i++;
   if(i < n && StringGetCharacter(body, i) == '"')
     {
      i++;
      int start = i;
      while(i < n && StringGetCharacter(body, i) != '"')
         i++;
      return(StringSubstr(body, start, i - start));
     }
   int start = i;
   while(i < n)
     {
      ushort ch = StringGetCharacter(body, i);
      if(ch == ',' || ch == '}' || ch == ' ' || ch == '\n' || ch == '\r')
         break;
      i++;
     }
   return(StringSubstr(body, start, i - start));
  }

int AiJsonInt(const string body, const string key, const int defv)
  {
   string s = AiJsonString(body, key);
   if(StringLen(s) == 0)
      return(defv);
   return((int)StringToInteger(s));
  }

bool AiJsonBool(const string body, const string key)
  {
   string s = AiJsonString(body, key);
   StringToLower(s);
   return(s == "true" || s == "1");
  }

void ExpertBridgeDefaults()
  {
   string names[11] = {"Market Analysis","Rocket Hunter","Scalping","Trend","Smart Money",
                       "News","Sentiment","Risk","Capital","Learning","Council"};
   for(int i = 0; i < 11; i++)
     {
      g_ai_groups[i] = names[i];
      g_ai_group_st[i] = "Disconnected";
     }
  }

void ExpertBridgeDisconnect(const string why)
  {
   g_ai_connected = false;
   g_ai_agents_on = 0;
   g_ai_reason = why;
   g_md_ai_linked = false;
   g_md_ai_analysis = "";
   g_md_ai_sentiment = "";
   ExpertBridgeDefaults();
  }

bool ExpertBridgeParse(const string body)
  {
   if(StringLen(body) < 2)
      return(false);
   bool connected = AiJsonBool(body, "connected") || AiJsonBool(body, "ok");
   if(!connected)
     {
      ExpertBridgeDisconnect("status says disconnected");
      return(true);
     }
   g_ai_connected = true;
   g_ai_last_ok = TimeCurrent();
   g_ai_reason = "ok";
   int on = AiJsonInt(body, "agents_on", AiJsonInt(body, "connected_agents", 0));
   int tot = AiJsonInt(body, "agents_total", AI_AGENT_CAP);
   if(tot <= 0 || tot > AI_AGENT_CAP)
      tot = AI_AGENT_CAP;
   if(on < 0) on = 0;
   if(on > tot) on = tot;
   g_ai_agents_on = on;
   g_ai_agents_total = tot;
   string mode = AiJsonString(body, "mode");
   if(StringLen(mode) > 0)
      g_ai_mode = mode;
   g_ai_council  = AiJsonString(body, "council");
   g_ai_analysis = AiJsonString(body, "analysis");
   g_ai_learning = AiJsonString(body, "learning");
   g_ai_risk     = AiJsonString(body, "risk");
   g_md_ai_linked    = true;                      // 3.0 decision layer inputs
   g_md_ai_analysis  = g_ai_analysis;
   g_md_ai_sentiment = AiJsonString(body, "sentiment");
   ExpertBridgeDefaults();
   //--- optional "groups":{"Scalping":"ok",...} — unknown groups stay Disconnected
   for(int i = 0; i < 11; i++)
     {
      string st = AiJsonString(body, g_ai_groups[i]);
      if(StringLen(st) == 0)
         continue;
      g_ai_group_st[i] = st;
     }
   return(true);
  }

string ExpertBridgeReadFile(const string name)
  {
   if(!FileIsExist(name, FILE_COMMON))
      return("");
   int h = FileOpen(name, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return("");
   string body = "";
   while(!FileIsEnding(h))
      body += FileReadString(h);
   FileClose(h);
   return(body);
  }

bool ExpertBridgeFetchUrl(string &body)
  {
   body = "";
   if(StringLen(AiBridgeUrl) == 0)
      return(false);
   string token = ExpertToken();
   string headers = "Accept: application/json\r\n";
   if(StringLen(token) > 0)
      headers += "Authorization: Bearer " + token + "\r\n";
   char data[], result[];
   string resp;
   ArrayResize(data, 0);
   int status = WebRequest("GET", AiBridgeUrl, headers, 8000, data, result, resp);
   if(status != 200)
      return(false);
   body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return(StringLen(body) > 0);
  }

bool ExpertSeen(const string id)
  {
   if(StringLen(id) == 0)
      return(true);
   for(int i = 0; i < g_ai_seen_n; i++)
      if(g_ai_seen[i] == id)
         return(true);
   return(false);
  }

void ExpertRemember(const string id)
  {
   if(StringLen(id) == 0 || ExpertSeen(id))
      return;
   if(g_ai_seen_n < AI_SEEN_MAX)
     {
      g_ai_seen[g_ai_seen_n] = id;
      g_ai_seen_n++;
      return;
     }
   for(int i = 1; i < AI_SEEN_MAX; i++)
      g_ai_seen[i - 1] = g_ai_seen[i];
   g_ai_seen[AI_SEEN_MAX - 1] = id;
  }

bool ExpertBridgeConnected()
  {
   if(!g_ai_connected)
      return(false);
   if(AiStaleSec > 0 && g_ai_last_ok > 0 && (TimeCurrent() - g_ai_last_ok) > AiStaleSec)
     {
      ExpertBridgeDisconnect("heartbeat stale");
      return(false);
     }
   return(true);
  }

void ExpertBridgeOnTimer()
  {
   string body = "";
   bool got = false;
   if(StringLen(AiBridgeUrl) > 0)
      got = ExpertBridgeFetchUrl(body);
   if(!got)
      body = ExpertBridgeReadFile(AI_STATUS_FILE);
   if(StringLen(body) == 0)
     {
      if(g_ai_connected && (TimeCurrent() - g_ai_last_ok) > AiStaleSec)
         ExpertBridgeDisconnect("no status");
      else if(!g_ai_connected)
         ExpertBridgeDisconnect("no link");
      return;
     }
   ExpertBridgeParse(body);
  }

void ExpertBridgeInit()
  {
   ExpertBridgeDefaults();
   ExpertBridgeOnTimer();
  }

#endif

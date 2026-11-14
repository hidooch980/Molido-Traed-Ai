# MT5 install guide — Molido Expert 2.0

1. Copy these files into the terminal `MQL5\Experts` folder (same directory is fine; quoted includes resolve next to the `.mq5`):
   - `Molido_Expert.mq5`
   - `MolidoRuntime.mqh`, `MolidoShared.mqh`, `MolidoI18n.mqh`
   - `MolidoDemoScalper.mqh`, `MolidoFibo.mqh`, `MolidoNews.mqh`, `MolidoSmart.mqh`, `MolidoProtect.mqh`, `MolidoUniverse.mqh`
   - `MolidoExpertBridge.mqh`, `MolidoExpertRisk.mqh`, `MolidoExpertReport.mqh`, `MolidoExpertExec.mqh`, `MolidoExpertUI.mqh`
2. In MetaEditor, compile `Molido_Expert.mq5`. Confirm **0 errors** (warnings are OK).
3. In the terminal: remove any previous Molido EA from the chart, press Refresh in Navigator, drag `Molido_Expert` onto the XAUUSD chart.
4. Enable Algo Trading (toolbar green). Tools > Options > Expert Advisors: Allow Algo Trading.
5. Leave AutoTrading on. Real accounts stay blocked even if you try to override.
6. Optional Advanced inputs: `Language` (AR/TR), `AiBridgeUrl`, `AiBridgeToken`. You do not need to change account type; detection is automatic.

import { Empty, Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * A prop-firm rulebook, and what it says about an account at the edges.
 *
 * The account states below are not a demonstration of the happy path. They sit
 * where a challenge is actually lost: the day you are 4.5% down and the trade
 * looks good, and the day the total floor binds because the provider measures
 * from the starting balance rather than from your peak. A page showing a
 * healthy account being approved would teach nothing anyone needs.
 *
 * Every rulebook carries `confirmed_by_holder: false` and this page repeats it
 * loudly. The numbers were transcribed from a published page on a stated date;
 * a marketing page and one account's contract are not guaranteed to be the
 * same document, and only the person who signed up can close that gap.
 */
export default async function ChallengePage() {
  const { t } = await getT();

  const START = 100_000;
  const STATES: { key: string; equity: number; dayOpen: number }[] = [
    { key: "fresh", equity: 100_000, dayOpen: 100_000 },
    { key: "downTwo", equity: 98_000, dayOpen: 100_000 },
    { key: "nearDaily", equity: 95_500, dayOpen: 100_000 },
    { key: "pastDaily", equity: 94_900, dayOpen: 100_000 },
    { key: "nearTotal", equity: 91_000, dayOpen: 91_000 },
    { key: "pastTotal", equity: 89_500, dayOpen: 89_500 },
    { key: "targetMet", equity: 111_000, dayOpen: 111_000 },
  ];

  const [books, ...verdicts] = await Promise.all([
    api.rulebooks(),
    ...STATES.map((state) =>
      api.challenge({
        starting_balance: START,
        current_equity: state.equity,
        daily_starting_equity: state.dayOpen,
        days_traded: 5,
        proposed_risk_r: 1,
        // Without this the drawdown allowance is money the sizer cannot turn
        // into a risk figure, so every state blocks and the table says nothing.
        currency_per_r: 200,
      }),
    ),
  ]);

  if (!books.ok) return <Offline error={books.error} />;

  const pct = (v: number | string) =>
    typeof v === "number" ? `${(v * 100).toFixed(v * 100 < 10 ? 1 : 0)}%` : String(v);

  const verdictTone = (verdict: string) =>
    verdict === "approve" ? "good" : verdict === "reduce" ? "warning" : "critical";

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("challenge.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("challenge.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("challenge.providers")}
          value={books.data.providers.join(", ") || "—"}
        />
        <Stat label={t("challenge.programs")} value={String(books.data.rulebooks.length)} />
        <Stat
          label={t("challenge.confirmed")}
          value={t("challenge.none")}
          tone="warning"
          hint={t("challenge.confirmedHint")}
        />
        <Stat
          label={t("challenge.retrieved")}
          value={books.data.rulebooks[0]?.retrieved ?? "—"}
          hint={t("challenge.retrievedHint")}
        />
      </div>

      <Panel title={t("challenge.rulebooks")} subtitle={t("challenge.rulebooksSubtitle")}>
        {books.data.rulebooks.length === 0 ? (
          <Empty>{t("challenge.noRulebooks")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("challenge.program")}</th>
                  <th>{t("challenge.phase")}</th>
                  <th>{t("challenge.target")}</th>
                  <th>{t("challenge.daily")}</th>
                  <th>{t("challenge.total")}</th>
                  <th>{t("challenge.trailing")}</th>
                  <th>{t("challenge.minDays")}</th>
                </tr>
              </thead>
              <tbody>
                {books.data.rulebooks.map((book) => (
                  <tr key={book.key}>
                    <td className="font-semibold">{book.program}</td>
                    <td className="ink-3">{book.phase}</td>
                    <td className="num ink-2">{pct(book.profit_target_pct)}</td>
                    <td className="num ink-2">{pct(book.max_daily_drawdown_pct)}</td>
                    <td className="num ink-2">{pct(book.max_total_drawdown_pct)}</td>
                    <td className="ink-3">
                      {book.total_drawdown_trailing === null
                        ? "—"
                        : book.total_drawdown_trailing
                          ? t("challenge.yes")
                          : t("challenge.no")}
                    </td>
                    <td className="num ink-3">{String(book.min_trading_days)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="p-4 text-xs ink-3 leading-relaxed">{books.data.note}</p>
      </Panel>

      <Panel title={t("challenge.atTheEdges")} subtitle={t("challenge.atTheEdgesSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("challenge.accountState")}</th>
                <th>{t("challenge.equity")}</th>
                <th>{t("challenge.verdict")}</th>
                <th>{t("challenge.status")}</th>
                <th>{t("challenge.newRisk")}</th>
                <th>{t("challenge.saidWhat")}</th>
              </tr>
            </thead>
            <tbody>
              {STATES.map((state, index) => {
                const answer = verdicts[index];
                if (!answer.ok) {
                  return (
                    <tr key={state.key}>
                      <td className="font-semibold">{t(`challenge.state.${state.key}`)}</td>
                      <td className="num ink-3" colSpan={5}>
                        {answer.error}
                      </td>
                    </tr>
                  );
                }
                const v = answer.data;
                const said =
                  v.breaches[0] ?? v.warnings[0] ?? v.unverified[0] ?? t("challenge.nothingToSay");
                return (
                  <tr key={state.key}>
                    <td className="font-semibold">{t(`challenge.state.${state.key}`)}</td>
                    <td className="num ink-3">{state.equity.toLocaleString("en-US")}</td>
                    <td>
                      <StatusBadge status={verdictTone(v.verdict)} label={v.verdict} />
                    </td>
                    <td className="ink-2">{v.status}</td>
                    <td className="num ink-2">
                      {v.max_additional_risk_r === null
                        ? t("challenge.noCap")
                        : `${v.max_additional_risk_r.toFixed(2)} R`}
                    </td>
                    <td className="ink-3 text-xs">{said}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("challenge.atTheEdgesBody")}</p>
      </Panel>

      <Panel title={t("challenge.rulesBeyondNumbers")}>
        <ul className="p-4 space-y-2 text-xs ink-3 leading-relaxed">
          {(books.data.rulebooks.find((b) => b.notes.length > 0)?.notes ?? []).map((note) => (
            <li key={note}>· {note}</li>
          ))}
        </ul>
      </Panel>

      <Panel title={t("challenge.whyUnconfirmed")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("challenge.whyUnconfirmedBody")}</p>
      </Panel>
    </div>
  );
}

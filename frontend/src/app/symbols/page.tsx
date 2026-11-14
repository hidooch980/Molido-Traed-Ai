import Link from "next/link";

import { Empty, Offline, Panel } from "@/components/ui";
import { api, type Instrument } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

const GROUPS: Array<{ key: string; match: (i: Instrument) => boolean }> = [
  { key: "symbols.gold", match: (i) => i.symbol.startsWith("XAU") || i.symbol.startsWith("XAG") },
  { key: "symbols.forex", match: (i) => i.asset_class.toLowerCase() === "forex" },
  { key: "symbols.crypto", match: (i) => i.asset_class.toLowerCase() === "crypto" },
  { key: "symbols.other", match: () => true },
];

export default async function Symbols() {
  const { t } = await getT();
  const res = await api.instruments();
  if (!res.ok) return <Offline error={res.error} />;
  const active = res.data.filter((i) => i.is_active).sort((a, b) => a.symbol.localeCompare(b.symbol));
  const seen = new Set<string>();
  const grouped = GROUPS.map((g) => {
    const items = active.filter((i) => !seen.has(i.id) && g.match(i));
    items.forEach((i) => seen.add(i.id));
    return { ...g, items };
  }).filter((g) => g.items.length > 0);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="display">{t("symbols.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("symbols.subtitle")}</p>
      </header>
      {grouped.length === 0 ? (
        <Panel>
          <Empty>{t("symbols.empty")}</Empty>
        </Panel>
      ) : (
        grouped.map((g) => (
          <section key={g.key} className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide ink-3">{t(g.key)}</h2>
            <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
              {g.items.map((i) => (
                <Link
                  key={i.id}
                  href={`/symbol/${encodeURIComponent(i.symbol)}`}
                  className="rounded-xl p-3 transition hover:-translate-y-0.5"
                  style={{
                    background: "linear-gradient(145deg, var(--panel-raised), var(--panel))",
                    border: "1px solid var(--line, rgba(255,255,255,0.06))",
                  }}
                >
                  <div className="font-mono text-sm" style={{ color: "var(--ink)" }}>
                    {i.symbol}
                  </div>
                  <div className="text-[0.6875rem] ink-3 truncate">{i.name}</div>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

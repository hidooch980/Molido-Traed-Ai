import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

export default async function FeaturesPage() {
  const { t } = await getT();
  const [catalog, instruments] = await Promise.all([
    api.featureCatalog(),
    api.instruments(),
  ]);

  if (!catalog.ok) return <Offline error={catalog.error} />;

  const primary = instruments.ok ? instruments.data[0] : undefined;
  const materialized = primary ? await api.features(primary.id, "H1", 1) : null;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("features.title")}</h1>
        <p className="text-xs ink-3 mt-0.5">
{t("features.subtitle")}
        </p>
      </header>

      {materialized?.ok && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="panel p-3.5">
            <div className="eyebrow">{t("features.registered")}</div>
            <div className="text-2xl font-semibold mt-1">{catalog.data.length}</div>
          </div>
          <div className="panel p-3.5">
            <div className="eyebrow">{t("features.values")}</div>
            <div className="text-2xl font-semibold mt-1 num">
              {materialized.data.materialized_values.toLocaleString()}
            </div>
          </div>
          <div className="panel p-3.5">
            <div className="eyebrow">{t("features.count")}</div>
            <div className="text-2xl font-semibold mt-1 num">
              {materialized.data.materialized_features}
            </div>
          </div>
        </div>
      )}

      <Panel title={t("features.title")} subtitle={t("features.description")}>
        {catalog.data.length === 0 ? (
          <Empty>{t("common.empty")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("features.feature")}</th>
                  <th>{t("features.version")}</th>
                  <th>{t("features.lookback")}</th>
                  <th style={{ whiteSpace: "normal" }}>{t("features.description")}</th>
                </tr>
              </thead>
              <tbody>
                {catalog.data.map((spec) => (
                  <tr key={spec.name}>
                    <td className="font-semibold">{spec.name}</td>
                    <td>
                      <Pill tone="muted">v{spec.version}</Pill>
                    </td>
                    <td className="num ink-2">{spec.lookback} {t("common.bars")}</td>
                    <td className="ink-3" style={{ whiteSpace: "normal" }}>
                      {spec.description}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title={t("features.enforced")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">
{t("features.enforcedBody")}
        </p>
      </Panel>
    </div>
  );
}

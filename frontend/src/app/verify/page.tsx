import { VerifyToken } from "@/components/VerifyToken";
import { Panel } from "@/components/ui";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Where the verification link in the email lands.
 *
 * It landed on a 404 for a while. The token system was built, tested and
 * shipped — hashed, single-use, expiring — and the one thing a person actually
 * clicks did not exist. Test coverage on a backend says nothing about whether
 * the path a human walks is complete.
 */
export default async function VerifyPage() {
  const { t } = await getT();

  return (
    <div className="mx-auto max-w-md space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("verify.title")}</h1>
        <p className="text-xs ink-3 mt-0.5">{t("verify.subtitle")}</p>
      </header>

      <Panel title={t("verify.title")}>
        <div className="p-4">
          <VerifyToken
            labels={{
              working: t("verify.working"),
              success: t("verify.success"),
              successNote: t("verify.successNote"),
              alreadyDone: t("verify.alreadyDone"),
              failed: t("verify.failed"),
              noToken: t("verify.noToken"),
              pointsAwarded: t("verify.pointsAwarded"),
              referrerAwarded: t("verify.referrerAwarded"),
              goHome: t("verify.goHome"),
            }}
          />
        </div>
      </Panel>
    </div>
  );
}

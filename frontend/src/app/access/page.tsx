import { AccessForm } from "@/components/AccessForm";
import { Offline, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

/**
 * The one page that works before anybody can sign in.
 *
 * It asks the API a single question - has this deployment been claimed - and
 * that answer decides which form appears. Rendering the choice on the server
 * means a visitor never sees a sign-in box on a deployment that has no
 * accounts, which is the state this system sat in while looking healthy.
 */
export const dynamic = "force-dynamic";

export default async function AccessPage() {
  const { t } = await getT();
  const setup = await api.setup();
  if (!setup.ok) return <Offline error={setup.error} />;

  const { claimed, password_min_length } = setup.data;

  return (
    <div className="mx-auto max-w-md space-y-4">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("signin.title")}</h1>
          <p className="page-lede">{claimed ? t("signin.subtitleClaimed") : t("signin.subtitleUnclaimed")}</p>
        </div>
      </header>

      <Panel title={claimed ? t("signin.signIn") : t("signin.claim")}>
        <div className="p-4">
          <AccessForm
            claimed={claimed}
            minLength={password_min_length}
            labels={{
              // Resolved here and handed over as plain strings. A `t` function
              // cannot cross into a Client Component - React refuses to
              // serialise it and the page 500s at runtime, which no type check
              // and no build catches.
              claimTitle: t("signin.claimTitle"),
              claimBody: t("signin.claimBody"),
              signInTitle: t("signin.signInTitle"),
              registerTitle: t("signin.registerTitle"),
              registerBody: t("signin.registerBody"),
              email: t("signin.email"),
              password: t("signin.password"),
              displayName: t("signin.displayName"),
              claim: t("signin.claim"),
              signIn: t("signin.signIn"),
              register: t("signin.register"),
              working: t("signin.working"),
              tooShort: t("signin.tooShort"),
              switchToRegister: t("signin.switchToRegister"),
              switchToSignIn: t("signin.switchToSignIn"),
              viewerNote: t("signin.viewerNote"),
            }}
          />
        </div>
      </Panel>

      <p className="text-xs ink-3 leading-relaxed">{t("signin.passwordNote")}</p>
    </div>
  );
}

import { LoginPanel } from "@/components/LoginPanel";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "ورود — MolidoTrade AI",
};

/**
 * A route of its own, outside the dashboard shell.
 *
 * The shell is a navigation rail over thirty-five pages and a header full of
 * status. None of it is reachable by somebody who has not signed in, and
 * drawing it behind a login form advertises a surface while refusing it - a
 * page that spends its first impression listing what you cannot have.
 *
 * Labels are resolved on the server and handed down as strings. The panel is a
 * client component and a function prop cannot cross that boundary; passing `t`
 * would compile, build, and fail at request time with "Functions cannot be
 * passed directly to Client Components" - which `/brokers` has already done
 * once in production.
 */
export default async function LoginPage() {
  const { t } = await getT();

  return (
    <LoginPanel
      version={t("login.version")}
      labels={{
        title: t("login.title"),
        subtitle: t("login.subtitle"),
        email: t("signin.email"),
        password: t("signin.password"),
        submit: t("signin.submit"),
        working: t("signin.working"),
        verifying: t("signin.verifying"),
        failed: t("signin.failed"),
        tooMany: t("signin.tooMany"),

        codeTitle: t("login.codeTitle"),
        codeSubtitle: t("login.codeSubtitle"),
        code: t("login.code"),
        codeHint: t("login.codeHint"),
        codeSubmit: t("login.codeSubmit"),

        enrolTitle: t("login.enrolTitle"),
        enrolSubtitle: t("login.enrolSubtitle"),
        scanHint: t("login.scanHint"),
        manualToggle: t("login.manualToggle"),
        manualHint: t("login.manualHint"),
        enrolSubmit: t("login.enrolSubmit"),

        codesTitle: t("login.codesTitle"),
        codesSubtitle: t("login.codesSubtitle"),
        codesWarning: t("login.codesWarning"),
        codesCopy: t("login.codesCopy"),
        codesCopied: t("login.codesCopied"),
        codesDone: t("login.codesDone"),

        heroTitle: t("login.heroTitle"),
        heroBody: t("login.heroBody"),
        statPagesLabel: t("login.statPages"),
        statEdgeValue: t("login.statEdgeValue"),
        statEdgeLabel: t("login.statEdge"),
        back: t("login.back"),
      }}
    />
  );
}

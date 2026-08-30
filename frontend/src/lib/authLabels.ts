import { getT } from "@/lib/locale";

/**
 * The label table both auth routes need, resolved once on the server.
 *
 * `/login` and `/register` are the same panel with a different first step, so
 * they need the same strings. Building the table in each page is the version
 * of this that drifts: a key added to one and forgotten in the other renders
 * its own name on screen, and only on the route nobody happened to open.
 *
 * Resolved here rather than passed as `t`. The panel is a client component and
 * a function prop cannot cross that boundary - it compiles, it builds, and it
 * fails at request time with "Functions cannot be passed directly to Client
 * Components", which `/brokers` has already done once in production.
 */
export async function authLabels() {
  const { t } = await getT();

  return {
    version: t("login.version"),
    labels: {
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

      registerTitle: t("login.registerTitle"),
      registerSubtitle: t("login.registerSubtitle"),
      registerSubmit: t("login.registerSubmit"),
      registerName: t("login.registerName"),
      registerDone: t("login.registerDone"),
      registerDoneBody: t("login.registerDoneBody"),

      claimTitle: t("login.claimTitle"),
      claimSubtitle: t("login.claimSubtitle"),
      claimWarning: t("login.claimWarning"),
      claimSubmit: t("login.claimSubmit"),
      claimDone: t("login.claimDone"),
      claimDoneBody: t("login.claimDoneBody"),
      haveAccount: t("login.haveAccount"),
      needAccount: t("login.needAccount"),
      signInHere: t("login.signInHere"),
      registerHere: t("login.registerHere"),

      heroTitle: t("login.heroTitle"),
      heroBody: t("login.heroBody"),

      humanCheck: {
        idle: t("human.idle"),
        solving: t("human.solving"),
        ready: t("human.ready"),
        stale: t("human.stale"),
        failed: t("human.failed"),
        notNeeded: t("human.notNeeded"),
        explain: t("human.explain"),
      },
    },
  };
}

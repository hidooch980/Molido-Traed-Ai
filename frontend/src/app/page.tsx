import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The public face, and the only page a visitor sees without an account.
 *
 * It reads nothing. That is the point: everything this application knows is
 * about somebody's account, and a landing page that fetched live figures would
 * be publishing them to anybody who loaded the URL.
 *
 * What it says is what the system actually is, including the parts that are
 * unflattering. The execution engine is off, no edge has been measured, and
 * the honest summary of the trading record is that there isn't one. A landing
 * page for a trading product that omitted those would be the first lie the
 * product tells, and every claim after it inherits the doubt.
 */
export default async function LandingPage() {
  const { t } = await getT();

  const principles = [
    { k: "proposes", n: "01" },
    { k: "authorises", n: "02" },
    { k: "executes", n: "03" },
    { k: "supervises", n: "04" },
  ];

  const refusals = ["noEdge", "noExecution", "noGuess", "noFabrication"];

  return (
    <div className="landing">
      <header className="landing-bar">
        <div className="landing-brand">
          <span className="auth-mark">◧</span>
          <span className="auth-wordmark">
            MolidoTrade<span className="auth-wordmark-ai">AI</span>
          </span>
        </div>
        <nav className="landing-actions">
          <a href="/register" className="pill">
            {t("signin.register")}
          </a>
          <a href="/login" className="pill pill-accent">
            {t("signin.signIn")}
          </a>
        </nav>
      </header>

      <section className="landing-hero">
        <div className="auth-hero-grid landing-grid" />
        <div className="landing-hero-body">
          <p className="landing-eyebrow">{t("landing.eyebrow")}</p>
          <h1 className="landing-title">{t("landing.title")}</h1>
          <p className="landing-lede">{t("landing.lede")}</p>
          <div className="landing-cta">
            <a href="/register" className="auth-button landing-button">
              {t("landing.ctaPrimary")}
            </a>
            <a href="/login" className="auth-button auth-button-quiet landing-button">
              {t("landing.ctaSecondary")}
            </a>
          </div>
        </div>
      </section>

      <section className="landing-section">
        <h2 className="landing-h2">{t("landing.chainTitle")}</h2>
        <p className="landing-section-lede">{t("landing.chainBody")}</p>
        <ol className="landing-chain">
          {principles.map((p) => (
            <li key={p.k} className="landing-step">
              <span className="landing-step-n">{p.n}</span>
              <h3 className="landing-step-title">{t(`landing.${p.k}Title`)}</h3>
              <p className="landing-step-body">{t(`landing.${p.k}Body`)}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-section">
        <h2 className="landing-h2">{t("landing.refusalsTitle")}</h2>
        <p className="landing-section-lede">{t("landing.refusalsBody")}</p>
        <ul className="landing-refusals">
          {refusals.map((r) => (
            <li key={r}>
              <h3 className="landing-refusal-title">{t(`landing.${r}Title`)}</h3>
              <p className="landing-step-body">{t(`landing.${r}Body`)}</p>
            </li>
          ))}
        </ul>
      </section>

      <footer className="landing-foot">
        <p>{t("landing.disclaimer")}</p>
        <p className="landing-foot-brand">MolidoTrade AI</p>
      </footer>
    </div>
  );
}

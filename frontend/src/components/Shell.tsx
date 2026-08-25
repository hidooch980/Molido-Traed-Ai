"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { translator, type Locale } from "@/lib/i18n";
import type { Theme } from "@/lib/locale";
import { SignIn } from "@/components/SignIn";
import { NAV, reachable, type NavItem } from "@/lib/nav";

/**
 * Routes that get no chrome at all.
 *
 * A sign-in page framed by the thing you have not signed into is a page that
 * spends its first impression listing what you cannot have - a rail of
 * thirty-five links, a language switcher, a status strip about a system the
 * visitor has no access to. Worse, the header carries a "sign in" button on
 * the sign-in page.
 *
 * Next's intended mechanism for this is a route group: move every dashboard
 * page under `(dashboard)/` with its own layout and leave `/login` outside it.
 * That is the better structure and it is not what this does, because it means
 * moving thirty-four directories, and the backend test that checks every page
 * either reads the API or is a declared exception indexes them by directory
 * name. The trade is recorded here rather than in a commit message nobody
 * reads twice: this is a list, and a list has to be maintained.
 *
 * `usePathname` resolves during the server render as well as in the browser,
 * so the bare page is bare in the first byte of HTML - no frame of a rail
 * appearing and then vanishing.
 */
const BARE_ROUTES = ["/login", "/register"];

const GROUPS: NavItem["group"][] = [
  "overview",
  "market",
  "trading",
  "intelligence",
  "operations",
];

function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg viewBox="0 0 128 128" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id="shell-grad" x1="0" y1="128" x2="128" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#0B2545" />
          <stop offset="0.55" stopColor="#1B6CA8" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="120" height="120" rx="28" fill="url(#shell-grad)" />
      <g fill="#22D3EE" stroke="#EAF6FF" strokeWidth="2.5">
        <rect x="23" y="44" width="14" height="40" rx="3" />
        <rect x="45" y="34" width="14" height="34" rx="3" />
        <rect x="69" y="52" width="14" height="34" rx="3" />
        <rect x="91" y="28" width="14" height="38" rx="3" />
      </g>
      <path
        d="M30 64 L52 51 L76 69 L98 47"
        fill="none"
        stroke="#7DF9FF"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Shell({
  locale,
  theme,
  initialCollapsed = false,
  children,
}: {
  locale: Locale;
  theme: Theme;
  initialCollapsed?: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  // Collapsed on wide screens is a preference, not a viewport question, so it
  // is remembered. A drawer that reopens on every navigation is a drawer
  // nobody closes twice.
  const [railCollapsed, setRailCollapsed] = useState(initialCollapsed);
  const t = translator(locale);
  // Counted from the nav table on every render rather than typed into the
  // translation file, so the badge cannot claim a page that was never wired.
  const { linked, total } = reachable();
  const coverage = t("app.coverage")
    .replace("{linked}", String(linked))
    .replace("{total}", String(total));

  // After every hook, never inside a condition above them: React counts hooks
  // per render and a component that runs a different number of them on one
  // path than another is one that crashes on the navigation between the two.
  if (BARE_ROUTES.includes(pathname)) {
    return <>{children}</>;
  }

  /**
   * The language lives in a cookie, not in React state.
   *
   * Every page is server-rendered, so a client-only language would translate
   * the chrome and leave the page body in the other language. Writing the
   * cookie and refreshing re-renders the whole tree on the server in one go.
   */
  function switchLocale(next: Locale) {
    document.cookie = `molido_locale=${next}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  }

  /**
   * The theme lives in a cookie, next to the language and for the same reason.
   *
   * The first version held it in component state and toggled a class. That
   * lasted until the next page load and then reverted, which reads as a broken
   * button rather than as a preference. Writing the cookie and refreshing means
   * the server renders the right theme into the first byte of HTML - no stored
   * choice that quietly forgets itself, and no frame of the wrong theme.
   */
  /** Remembered like the theme and the language, and for the same reason: a
   *  preference that resets on the next page load is not a preference. Written
   *  to a cookie so the server renders the rail at the right width in the first
   *  byte - no frame of a wide menu collapsing after the page arrives. */
  function toggleRail(next: boolean) {
    setRailCollapsed(next);
    document.cookie = `molido_rail=${next ? "collapsed" : "open"}; path=/; max-age=31536000; samesite=lax`;
  }

  function switchTheme(next: Theme) {
    document.cookie = `molido_theme=${next}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.classList.toggle("dark", next === "dark");
    router.refresh();
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header
        className="panel-flat sticky top-0 z-20 flex items-center gap-3 px-3 py-2"
        style={{ borderInline: "none", borderTop: "none" }}
      >
        <button
          type="button"
          className="md:hidden text-lg px-1"
          onClick={() => setMenuOpen(!menuOpen)}
          aria-label="menu"
        >
          ☰
        </button>

        {/* The same control on wide screens, where it collapses the rail
            rather than sliding a drawer over the page. One button, two
            behaviours, because "show me the menu" is one intention and the
            screen decides how that looks. */}
        <button
          type="button"
          className="hidden md:block text-lg px-1"
          onClick={() => toggleRail(!railCollapsed)}
          aria-label={railCollapsed ? t("nav.expand") : t("nav.collapse")}
          title={railCollapsed ? t("nav.expand") : t("nav.collapse")}
        >
          ☰
        </button>

        {/* The brand lives at the top of the rail, where it stays put. Repeating
            it in the header cost the widest strip of the screen to say the
            same word twice, and left no room for the thing a header is for:
            what is happening right now. */}
        <div className="md:hidden flex items-center gap-2 min-w-0">
          <Logo size={24} />
          <span className="font-bold text-[0.9375rem]">
            Molido<span style={{ color: "var(--accent)" }}>Trade</span>
          </span>
        </div>

        <div className="posture-strip" title={t("app.noExecution")}>
          <span className="posture-dot" />
          <span className="posture-text">{t("app.noExecution")}</span>
        </div>

        <div className="flex-1" />

        <span className="pill hidden md:inline-flex" style={{ color: "var(--ink-3)" }}>
          {coverage}
        </span>

        <SignIn
          labels={{
            signIn: t("signin.signIn"),
            register: t("signin.register"),
            signOut: t("signin.signOut"),
            email: t("signin.email"),
            password: t("signin.password"),
            submit: t("signin.submit"),
            cancel: t("signin.cancel"),
            working: t("signin.working"),
            failed: t("signin.failed"),
            verifying: t("signin.verifying"),
            tooMany: t("signin.tooMany"),
            signedInAs: t("signin.signedInAs"),
            anonymous: t("signin.anonymous"),
            anonymousHint: t("signin.anonymousHint"),
          }}
        />

        <button
          type="button"
          onClick={() => switchLocale(locale === "fa" ? "en" : "fa")}
          className="pill"
          style={{ color: "var(--ink-2)" }}
        >
          {locale === "fa" ? "English" : "فارسی"}
        </button>
        <button
          type="button"
          onClick={() => switchTheme(theme === "dark" ? "light" : "dark")}
          className="pill"
          style={{ color: "var(--ink-2)" }}
        >
          {theme === "dark" ? `☀ ${t("common.theme.light")}` : `☾ ${t("common.theme.dark")}`}
        </button>
      </header>

      <div className="flex flex-1 min-h-0">
        {/* The scrim. Only on narrow screens, where the drawer covers the
            page - tapping beside it is how people close a drawer, and without
            this the only way out is the same small button they came from. */}
        {menuOpen && (
          <button
            type="button"
            aria-label={t("nav.close")}
            onClick={() => setMenuOpen(false)}
            className="md:hidden fixed inset-0 z-[9]"
            style={{ background: "rgba(0,0,0,0.45)" }}
          />
        )}

        <nav
          className={`rail shrink-0 overflow-y-auto transition-all duration-200 ${
            menuOpen ? "block fixed inset-y-0 z-10 mt-12 w-64" : "hidden"
          } md:block ${railCollapsed ? "md:w-0 md:p-0 md:overflow-hidden" : "md:w-64"}`}
        >
          {/* Anchored, not scrolled past. On a rail of thirty-five links the
              brand is the one fixed point, and a wordmark that slides away
              takes the sense of place with it. */}
          <div className="rail-brand hidden md:flex">
            <Logo size={26} />
            <div className="min-w-0">
              <div className="rail-wordmark">
                Molido<span style={{ color: "var(--accent)" }}>Trade</span>
                <span className="rail-ai">AI</span>
              </div>
              <div className="rail-tagline">{t("app.tagline")}</div>
            </div>
          </div>

          {GROUPS.map((group) => (
            <div key={group} className="rail-group">
              <div className="rail-group-label">{t(`nav.${group}`)}</div>
              {NAV.filter((item) => item.group === group).map((item) => {
                const label = item.labelKey.includes(".")
                  ? t(item.labelKey)
                  : item.labelKey;
                if (item.planned || !item.href) {
                  return (
                    <div
                      key={item.key}
                      className="nav-link"
                      data-planned="true"
                      title={t("nav.planned")}
                    >
                      {label}
                    </div>
                  );
                }
                const active =
                  pathname === item.href ||
                  (item.href !== "/" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.key}
                    href={item.href}
                    className="nav-link"
                    data-active={active}
                    onClick={() => setMenuOpen(false)}
                  >
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}

          <p className="rail-note">{t("nav.note")}</p>
        </nav>

        <div className="flex-1 min-w-0 flex flex-col overflow-y-auto">
          {/* A measure. Full-bleed content on a 27-inch monitor produces table
              rows a metre wide, and the eye loses the row between the label at
              one edge and the number at the other. */}
          <main className="page-main">
            <div className="page-measure">{children}</div>
          </main>

          {/* Build stamp. Deliberately always visible and never breakpoint-hidden:
              its only job is to answer "did my deploy land?", and it cannot do
              that from behind a media query. */}
          <footer
            className="px-3 md:px-5 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem] ink-3"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <span className="font-semibold">MolidoTrade AI</span>
            <span>{coverage}</span>
            {/* Version, commit and build time together. Any one alone leaves
                a question the other two answer: which release is this, which
                code exactly, and did my deploy actually land. */}
            <span className="num" title="release version">
              v{process.env.NEXT_PUBLIC_VERSION || "dev"}
            </span>
            <span className="num" title="git commit">
              {process.env.NEXT_PUBLIC_COMMIT || "local"}
            </span>
            <span className="num" title="build timestamp (UTC)">
              build {process.env.NEXT_PUBLIC_BUILD || "dev"}
            </span>
            <span className="flex-1" />
            <span>{t("app.noExecution")}</span>
          </footer>
        </div>
      </div>
    </div>
  );
}

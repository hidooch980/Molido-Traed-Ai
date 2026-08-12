"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { translator, type Locale } from "@/lib/i18n";
import { NAV, type NavItem } from "@/lib/nav";

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
  children,
}: {
  locale: Locale;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [dark, setDark] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const t = translator(locale);

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

  function toggleTheme() {
    const nextDark = !dark;
    setDark(nextDark);
    document.documentElement.classList.toggle("dark", nextDark);
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

        <Logo />
        <div className="min-w-0">
          <div className="font-bold leading-tight text-[0.9375rem]">
            Molido<span style={{ color: "var(--accent)" }}>Trade</span>
            <span className="eyebrow ms-1.5 align-middle">AI</span>
          </div>
          <div className="text-[0.6875rem] ink-3 truncate hidden sm:block">
            {t("app.tagline")}
          </div>
        </div>

        <div className="flex-1" />

        <span className="pill hidden lg:inline-flex" style={{ color: "var(--ink-3)" }}>
          {t("app.phase")}
        </span>

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
          onClick={toggleTheme}
          className="pill"
          style={{ color: "var(--ink-2)" }}
        >
          {dark ? `☀ ${t("common.theme.light")}` : `☾ ${t("common.theme.dark")}`}
        </button>
      </header>

      <div className="flex flex-1 min-h-0">
        <nav
          className={`panel-flat w-56 shrink-0 overflow-y-auto p-2.5 ${
            menuOpen ? "block absolute inset-y-0 z-10 mt-12" : "hidden"
          } md:block`}
          style={{ borderBlock: "none", borderInlineStart: "none" }}
        >
          {GROUPS.map((group) => (
            <div key={group} className="mb-3">
              <div className="eyebrow px-2 mb-1">{t(`nav.${group}`)}</div>
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

          <p className="text-[0.6875rem] ink-3 px-2 pt-2 leading-relaxed">
            {t("nav.note")}
          </p>
        </nav>

        <main className="flex-1 min-w-0 p-3 md:p-5 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

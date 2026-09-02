/**
 * Command Center navigation (spec §43).
 *
 * The full 28-item map is declared here from the start so the information
 * architecture is visible and stable. Items that have no backend yet are
 * marked `planned` and render disabled — an honest "not built" beats a link
 * that leads to an empty page pretending to be a feature.
 */

export interface NavItem {
  key: string;
  labelKey: string;
  href?: string;
  planned?: boolean;
  // Named for what somebody is doing there, not for what the pages are
  // about. "Intelligence" said what the pages contained and nobody knew
  // whether the journal or the calendar belonged in it; "learning" is what
  // you go there to do. "Operations" became "setup" for the same reason:
  // it is where accounts, terminals and brokers get connected.
  group: "overview" | "market" | "trading" | "learning" | "setup";
}

export const NAV: NavItem[] = [
  { key: "home", labelKey: "nav.home", href: "/dashboard", group: "overview" },
  { key: "situation-room", labelKey: "nav.situationRoom", href: "/posture", group: "overview" },
  { key: "ai-brain", labelKey: "nav.aiBrain", href: "/brain", group: "overview" },
  { key: "markets", labelKey: "nav.markets", href: "/markets", group: "market" },
  { key: "sessions", labelKey: "nav.sessions", href: "/sessions", group: "market" },
  { key: "calendar", labelKey: "nav.calendar", href: "/calendar", group: "market" },
  { key: "scanner", labelKey: "nav.scanner", href: "/scanner", group: "market" },
  { key: "charts", labelKey: "nav.charts", href: "/charts", group: "market" },
  { key: "market-map", labelKey: "nav.marketMap", href: "/market-map", group: "market" },
  { key: "fundamentals", labelKey: "nav.fundamentals", href: "/fundamentals", group: "market" },
  { key: "signals", labelKey: "nav.signals", href: "/decisions", group: "trading" },
  { key: "positions", labelKey: "nav.positions", href: "/positions", group: "trading" },
  { key: "orders", labelKey: "nav.orders", href: "/orders", group: "trading" },
  { key: "risk", labelKey: "nav.risk", href: "/risk", group: "trading" },
  { key: "challenge", labelKey: "nav.challenge", href: "/challenge", group: "trading" },
  { key: "execution", labelKey: "nav.execution", href: "/execution", group: "trading" },
  { key: "journal", labelKey: "nav.journal", href: "/journal", group: "trading" },
  { key: "lab", labelKey: "nav.lab", href: "/lab", group: "learning" },
  { key: "research", labelKey: "nav.research", href: "/research", group: "learning" },
  { key: "features", labelKey: "nav.features", href: "/features", group: "learning" },
  { key: "symbol-dna", labelKey: "nav.symbolDna", href: "/symbol-dna", group: "learning" },
  { key: "memory", labelKey: "nav.memory", href: "/memory", group: "learning" },
  { key: "episodes", labelKey: "nav.episodes", href: "/episodes", group: "learning" },
  { key: "readiness", labelKey: "nav.readiness", href: "/readiness", group: "learning" },
  { key: "registry", labelKey: "nav.registry", href: "/learning", group: "learning" },
  { key: "accounts", labelKey: "nav.accounts", href: "/accounts", group: "setup" },
  { key: "terminals", labelKey: "nav.terminals", href: "/terminals", group: "setup" },
  { key: "brokers", labelKey: "nav.brokers", href: "/brokers", group: "setup" },
  { key: "telegram", labelKey: "nav.telegram", href: "/telegram", group: "setup" },
  { key: "automation", labelKey: "nav.automation", href: "/automation", group: "setup" },
  { key: "ai-health", labelKey: "nav.aiHealth", href: "/health", group: "setup" },
  { key: "data-quality", labelKey: "nav.dataQuality", href: "/data-quality", group: "setup" },
  { key: "security", labelKey: "nav.security", href: "/security", group: "setup" },
  { key: "settings", labelKey: "nav.settings", href: "/settings", group: "setup" },
];

/**
 * How much of the map is actually reachable, counted rather than typed.
 *
 * The badge above this used to read "53 / 53 built". Nothing measured it: it
 * was a number somebody typed, it counted how much code existed, and it stayed
 * 53 / 53 whether or not a single screen worked. This counts links that resolve
 * to a page, and `test_navigation_contract` asserts every one of those pages
 * exists and reads the API — so the number cannot climb without something
 * having been built and checked.
 */
export function reachable(): { linked: number; total: number } {
  return { linked: NAV.filter((item) => item.href).length, total: NAV.length };
}

export const GROUP_LABELS: Record<NavItem["group"], string> = {
  overview: "Overview",
  market: "Market",
  trading: "Trading",
  learning: "Learning",
  setup: "Setup",
};

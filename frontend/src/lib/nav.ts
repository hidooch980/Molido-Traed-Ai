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
  group: "overview" | "market" | "trading" | "intelligence" | "operations";
}

export const NAV: NavItem[] = [
  { key: "home", labelKey: "nav.home", href: "/", group: "overview" },
  { key: "ai-brain", labelKey: "nav.aiBrain", href: "/brain", group: "overview" },
  { key: "situation-room", labelKey: "nav.situationRoom", href: "/posture", group: "overview" },

  { key: "markets", labelKey: "nav.markets", href: "/markets", group: "market" },
  { key: "sessions", labelKey: "nav.sessions", href: "/sessions", group: "market" },
  { key: "market-map", labelKey: "nav.marketMap", href: "/market-map", group: "market" },
  { key: "scanner", labelKey: "nav.scanner", href: "/scanner", group: "market" },
  { key: "charts", labelKey: "nav.charts", href: "/charts", group: "market" },

  { key: "signals", labelKey: "nav.signals", href: "/decisions", group: "trading" },
  { key: "positions", labelKey: "nav.positions", planned: true, group: "trading" },
  { key: "orders", labelKey: "nav.orders", planned: true, group: "trading" },
  { key: "portfolio", labelKey: "nav.portfolio", href: "/risk", group: "trading" },
  { key: "risk", labelKey: "nav.risk", href: "/risk", group: "trading" },
  { key: "challenge", labelKey: "nav.challenge", planned: true, group: "trading" },
  { key: "execution", labelKey: "nav.execution", href: "/execution", group: "trading" },

  { key: "features", labelKey: "nav.features", href: "/features", group: "intelligence" },
  { key: "symbol-dna", labelKey: "nav.symbolDna", href: "/symbol-dna", group: "intelligence" },
  { key: "memory", labelKey: "nav.memory", href: "/memory", group: "intelligence" },
  { key: "episodes", labelKey: "nav.episodes", href: "/episodes", group: "intelligence" },
  { key: "journal", labelKey: "nav.journal", planned: true, group: "intelligence" },
  { key: "lab", labelKey: "nav.lab", planned: true, group: "intelligence" },
  { key: "backtest", labelKey: "nav.backtest", planned: true, group: "intelligence" },
  { key: "research", labelKey: "nav.research", planned: true, group: "intelligence" },
  { key: "benchmark", labelKey: "nav.benchmark", planned: true, group: "intelligence" },
  { key: "registry", labelKey: "nav.registry", href: "/learning", group: "intelligence" },

  { key: "data-quality", labelKey: "nav.dataQuality", href: "/data-quality", group: "operations" },
  { key: "ai-health", labelKey: "nav.aiHealth", href: "/health", group: "operations" },
  { key: "accounts", labelKey: "nav.accounts", href: "/execution", group: "operations" },
  { key: "brokers", labelKey: "nav.brokers", href: "/execution", group: "operations" },
  { key: "telegram", labelKey: "nav.telegram", href: "/security", group: "operations" },
  { key: "automation", labelKey: "nav.automation", planned: true, group: "operations" },
  { key: "security", labelKey: "nav.security", href: "/security", group: "operations" },
  { key: "settings", labelKey: "nav.settings", href: "/settings", group: "operations" },
];

export const GROUP_LABELS: Record<NavItem["group"], string> = {
  overview: "Overview",
  market: "Market",
  trading: "Trading",
  intelligence: "Intelligence",
  operations: "Operations",
};

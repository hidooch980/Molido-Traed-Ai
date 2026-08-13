import Link from "next/link";

/**
 * Carry the selected instrument between the screens that are about it.
 *
 * Every instrument-scoped page took `?instrument=<id>` and then linked only
 * within itself, so reading EURUSD's memory and then wanting its episodes
 * meant navigating away and picking EURUSD again from a list. The instrument
 * is the thing the operator is thinking about; the page is just which question
 * they are asking about it, and switching questions should not lose the
 * subject.
 *
 * The current page is rendered as plain text rather than a link to itself —
 * a link that reloads the page you are on reads as a broken one.
 */

export interface InstrumentLink {
  href: string;
  labelKey: string;
}

/** Every screen that answers a question about one instrument. */
export const INSTRUMENT_VIEWS: InstrumentLink[] = [
  { href: "/markets", labelKey: "nav.markets" },
  { href: "/symbol-dna", labelKey: "nav.symbolDna" },
  { href: "/memory", labelKey: "nav.memory" },
  { href: "/episodes", labelKey: "nav.episodes" },
  { href: "/data-quality", labelKey: "nav.dataQuality" },
];

export function InstrumentLinks({
  instrumentId,
  symbol,
  current,
  t,
}: {
  instrumentId: string;
  symbol?: string;
  /** Href of the page rendering this, so it is not linked to itself. */
  current: string;
  t: (key: string) => string;
}) {
  return (
    <nav
      className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs"
      aria-label={t("links.sameInstrument")}
    >
      <span className="ink-3">{t("links.sameInstrument")}</span>
      {symbol && <span className="num font-semibold">{symbol}</span>}
      <span className="ink-3">·</span>
      {INSTRUMENT_VIEWS.map((view) =>
        view.href === current ? (
          <span key={view.href} className="pill" style={{ color: "var(--ink-3)" }}>
            {t(view.labelKey)}
          </span>
        ) : (
          <Link
            key={view.href}
            href={`${view.href}?instrument=${instrumentId}`}
            className="pill"
          >
            {t(view.labelKey)}
          </Link>
        ),
      )}
    </nav>
  );
}

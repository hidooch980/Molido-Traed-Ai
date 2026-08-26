/**
 * Shared presentation pieces.
 *
 * Server components — no interactivity here. Anything needing hover state
 * lives in its own client component (see PriceChart).
 */

import type { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <header className="panel-head">
          <div>
            <h2 className="panel-title">{title}</h2>
            {subtitle && <p className="text-xs ink-3 mt-0.5">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
  chart,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: "neutral" | "good" | "warning" | "critical";
  chart?: ReactNode;
}) {
  const color =
    tone === "good"
      ? "var(--good)"
      : tone === "warning"
        ? "var(--warning)"
        : tone === "critical"
          ? "var(--critical)"
          : "var(--ink)";

  return (
    <div className="panel p-3.5 flex flex-col gap-1.5">
      <div className="eyebrow">{label}</div>
      <div className="flex items-end gap-1.5">
        <span className="text-[1.75rem] leading-none font-semibold" style={{ color }}>
          {value}
        </span>
        {unit && <span className="text-xs ink-3 pb-0.5">{unit}</span>}
      </div>
      {chart}
      {hint && <div className="text-xs ink-3">{hint}</div>}
    </div>
  );
}

const STATUS_META: Record<
  string,
  { color: string; icon: string; label: string }
> = {
  info: { color: "var(--ink-3)", icon: "•", label: "info" },
  warning: { color: "var(--warning)", icon: "▲", label: "warning" },
  error: { color: "var(--serious)", icon: "■", label: "error" },
  critical: { color: "var(--critical)", icon: "✕", label: "critical" },
  good: { color: "var(--good)", icon: "●", label: "ok" },
};

/**
 * Status is never carried by colour alone — every badge ships an icon and the
 * word. That is the rule for colour-vision deficiency, print and forced-colors
 * modes, and it costs nothing here.
 */
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.info;
  return (
    <span className="pill" style={{ color: meta.color, borderColor: "currentColor" }}>
      <span aria-hidden="true">{meta.icon}</span>
      {label ?? meta.label}
    </span>
  );
}

/**
 * A small state label.
 *
 * Carries the same five tones `Stat` does, and did not used to: it stopped at
 * good, neutral and muted, so a pill that needed to say "this is real money"
 * had nothing louder than the one that says "closed". Pages worked around
 * that with inline colours, which is how two things meaning "danger" end up
 * different shades on different screens.
 */
export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "muted" | "warning" | "critical";
}) {
  const color = {
    good: "var(--good)",
    muted: "var(--ink-3)",
    warning: "var(--warning)",
    critical: "var(--critical)",
    neutral: "var(--ink-2)",
  }[tone];
  return (
    <span
      className="pill"
      style={{
        color,
        // The border follows the tone for the two that mean something is
        // wrong. A red word inside a grey outline reads as a colour choice;
        // the outline is what makes it read as a state.
        borderColor:
          tone === "critical" || tone === "warning" ? color : "var(--border-strong)",
      }}
    >
      {children}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-6 text-sm ink-3 text-center">{children}</div>;
}

/**
 * Offline state. Deliberately loud and specific: a dashboard that silently
 * renders empty tables when its backend is down teaches operators to distrust
 * every empty table they ever see.
 */
export function Offline({ error, message, help }: { error: string; message?: string; help?: string }) {
  return (
    <div
      className="panel p-4 flex items-start gap-3"
      style={{ borderInlineStartWidth: 3, borderInlineStartColor: "var(--critical)" }}
    >
      <span style={{ color: "var(--critical)" }} aria-hidden="true">
        ✕
      </span>
      <div>
        <div className="font-semibold text-sm">{message ?? "Backend unreachable"}</div>
        <div className="text-xs ink-3 mt-0.5">{error}</div>
        <div className="text-xs ink-3 mt-1.5">
{help ?? "Start the API and check the database container."}
        </div>
      </div>
    </div>
  );
}

/** Inline sparkline. No axes, no labels — it shows shape, the tile shows value. */
export function Sparkline({
  values,
  width = 132,
  height = 30,
  color = "var(--series-1)",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length < 2) return null;

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const step = width / (clean.length - 1);

  const points = clean.map((v, i) => [i * step, height - ((v - min) / span) * height]);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const area = `${line}L${width},${height}L0,${height}Z`;
  const last = points[points.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="trend sparkline"
      style={{ overflow: "visible" }}
    >
      <path d={area} fill={color} opacity="0.1" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      {/* 2px surface ring keeps the end marker legible where it overlaps the line */}
      <circle cx={last[0]} cy={last[1]} r="3" fill={color} stroke="var(--panel)" strokeWidth="2" />
    </svg>
  );
}

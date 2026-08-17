"use client";

import { useEffect, useState } from "react";

/**
 * An analog face, anchored to the server's clock rather than the browser's.
 *
 * The anchoring is the only interesting part. A clock that reads
 * `new Date()` shows whatever the viewer's machine believes, and this platform
 * puts it beside session states, release times and bar timestamps that all come
 * from the server. A browser running four minutes fast would put a visibly
 * different time next to a "London open in 3 minutes" computed elsewhere, and
 * there would be no way to tell which one was wrong.
 *
 * So the server's instant arrives as a prop, the drift between it and the local
 * machine is measured once, and every tick after that applies the same
 * correction. The hands stay smooth because they still tick locally; they are
 * simply offset onto the clock the rest of the page uses.
 */
export function AnalogClock({
  utcIso,
  offsetHours,
  label,
  size = 132,
}: {
  utcIso: string;
  offsetHours: number;
  label: string;
  size?: number;
}) {
  // Measured once, on mount, and then held. Re-measuring every tick would
  // chase the browser's clock instead of correcting for it.
  const [drift, setDrift] = useState<number | null>(null);
  const [now, setNow] = useState(() => new Date(utcIso).getTime());

  useEffect(() => {
    const measured = new Date(utcIso).getTime() - Date.now();
    setDrift(measured);
    const tick = () => setNow(Date.now() + measured);
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [utcIso]);

  const local = new Date(now + offsetHours * 3_600_000);
  // getUTC*, not the local getters: the offset has already been applied above,
  // so reading local getters would apply the viewer's timezone a second time.
  const seconds = local.getUTCSeconds();
  const minutes = local.getUTCMinutes() + seconds / 60;
  const hours = (local.getUTCHours() % 12) + minutes / 60;

  const centre = size / 2;
  const hand = (angle: number, length: number, width: number, color: string) => {
    const radians = (angle - 90) * (Math.PI / 180);
    return (
      <line
        x1={centre}
        y1={centre}
        x2={centre + Math.cos(radians) * length}
        y2={centre + Math.sin(radians) * length}
        stroke={color}
        strokeWidth={width}
        strokeLinecap="round"
      />
    );
  };

  const digital = `${String(local.getUTCHours()).padStart(2, "0")}:${String(
    local.getUTCMinutes(),
  ).padStart(2, "0")}`;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`${label} ${digital}`}
      >
        <circle
          cx={centre}
          cy={centre}
          r={centre - 2}
          fill="var(--panel-raised)"
          stroke="var(--border)"
          strokeWidth="1.5"
        />
        {Array.from({ length: 12 }, (_, i) => {
          const radians = (i * 30 - 90) * (Math.PI / 180);
          const outer = centre - 8;
          const inner = outer - (i % 3 === 0 ? 9 : 5);
          return (
            <line
              key={i}
              x1={centre + Math.cos(radians) * inner}
              y1={centre + Math.sin(radians) * inner}
              x2={centre + Math.cos(radians) * outer}
              y2={centre + Math.sin(radians) * outer}
              stroke="var(--ink-3)"
              strokeWidth={i % 3 === 0 ? 2 : 1}
              strokeLinecap="round"
            />
          );
        })}
        {hand(hours * 30, centre * 0.5, 3.5, "var(--ink-1)")}
        {hand(minutes * 6, centre * 0.72, 2.5, "var(--ink-1)")}
        {/* The second hand is hidden until the drift is known, so the first
            frame never shows the browser's own time by accident. */}
        {drift !== null && hand(seconds * 6, centre * 0.78, 1, "var(--accent)")}
        <circle cx={centre} cy={centre} r="3" fill="var(--accent)" />
      </svg>
      <div className="text-center leading-tight">
        <div className="text-xs ink-3">{label}</div>
        <div className="text-sm font-bold tabular-nums">{digital}</div>
      </div>
    </div>
  );
}

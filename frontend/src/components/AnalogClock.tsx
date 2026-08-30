"use client";

import { useEffect, useId, useState } from "react";

/**
 * An analog face, anchored to the server's clock rather than the browser's.
 *
 * The anchoring is the load-bearing part. A clock that reads `new Date()` shows
 * whatever the viewer's machine believes, and this platform puts it beside
 * session states, release times and bar timestamps that all come from the
 * server. A browser running four minutes fast would put a visibly different
 * time next to a "London open in 3 minutes" computed elsewhere, and there would
 * be no way to tell which one was wrong.
 *
 * So the server's instant arrives as a prop, the drift between it and the local
 * machine is measured once, and every tick after that applies the same
 * correction. The hands stay smooth because they still tick locally; they are
 * simply offset onto the clock the rest of the page uses.
 *
 * **The face is drawn with depth on purpose.** Everything else on this
 * application is deliberately flat - panels are regions of one sheet, and a
 * drop shadow on a data table implies a floating object that is not floating.
 * A clock is the exception, and it earns it: it is a picture of a physical
 * object, and the whole reason to draw one instead of printing the digits is
 * that a person reads an angle faster than they read a number. A flat disc
 * with lines on it is neither - it reads as a diagram of a clock rather than
 * as a clock, and the eye stops to decode it.
 *
 * So: a dished face, a raised bezel catching light from above, a specular
 * sweep across the glass, and hands that cast a short shadow onto the dial.
 * The light source is top-left and consistent across all three faces, because
 * three clocks lit from three directions read as three unrelated objects.
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

  // Gradients and filters are referenced by id, and three clocks share a page.
  // Hardcoded ids would mean all three faces resolve to whichever `<defs>` the
  // browser saw last - and the bug looks like two of them failing to paint.
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");

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
  const point = (angle: number, length: number) => {
    const radians = (angle - 90) * (Math.PI / 180);
    return {
      x: centre + Math.cos(radians) * length,
      y: centre + Math.sin(radians) * length,
    };
  };

  const hand = (
    angle: number,
    length: number,
    width: number,
    color: string,
    tail = 0,
  ) => {
    const tip = point(angle, length);
    const back = point(angle + 180, tail);
    return (
      <line
        x1={back.x}
        y1={back.y}
        x2={tip.x}
        y2={tip.y}
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
        style={{ overflow: "visible" }}
      >
        <defs>
          {/* The bezel. Light from the top-left, so the ring is bright where it
              faces the light and dark where it turns away - which is the whole
              of what makes a ring look like a ring. */}
          <linearGradient id={`bezel${uid}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="rgba(255,255,255,0.34)" />
            <stop offset="42%" stopColor="rgba(255,255,255,0.08)" />
            <stop offset="58%" stopColor="rgba(0,0,0,0.45)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0.16)" />
          </linearGradient>

          {/* The dial is dished, not domed: darker at the rim, lighter toward
              the centre, with the light pool offset toward the source. A
              uniform fill is what made the old face read as a diagram. */}
          <radialGradient id={`dial${uid}`} cx="34%" cy="30%" r="78%">
            <stop offset="0%" stopColor="rgba(255,255,255,0.10)" />
            <stop offset="55%" stopColor="rgba(255,255,255,0.02)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0.55)" />
          </radialGradient>

          {/* Glass. One sweep across the upper left, fading out well before the
              centre so it never sits on top of the hands. */}
          <linearGradient id={`glass${uid}`} x1="0" y1="0" x2="0.85" y2="1">
            <stop offset="0%" stopColor="rgba(255,255,255,0.16)" />
            <stop offset="38%" stopColor="rgba(255,255,255,0.03)" />
            <stop offset="55%" stopColor="rgba(255,255,255,0)" />
          </linearGradient>

          {/* The hands sit above the dial, so they cast onto it. Short and soft:
              a long hard shadow would read as a second set of hands. */}
          <filter id={`cast${uid}`} x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow
              dx={size * 0.012}
              dy={size * 0.018}
              stdDeviation={size * 0.012}
              floodColor="#000"
              floodOpacity="0.55"
            />
          </filter>

          {/* And the whole object sits above the panel. */}
          <filter id={`lift${uid}`} x="-25%" y="-25%" width="150%" height="150%">
            <feDropShadow
              dx="0"
              dy={size * 0.03}
              stdDeviation={size * 0.045}
              floodColor="#000"
              floodOpacity="0.6"
            />
          </filter>
        </defs>

        <g filter={`url(#lift${uid})`}>
          {/* Body, bezel, dial, in that order: each one is the ring below it
              made smaller, which is how a bezel gets its thickness. */}
          <circle cx={centre} cy={centre} r={centre - 1} fill="var(--panel)" />
          <circle
            cx={centre}
            cy={centre}
            r={centre - 2}
            fill={`url(#bezel${uid})`}
          />
          <circle cx={centre} cy={centre} r={centre - 7} fill="var(--panel-raised)" />
          <circle cx={centre} cy={centre} r={centre - 7} fill={`url(#dial${uid})`} />
          {/* The inner lip: a hairline where the dial drops away from the
              bezel. Without it the two circles read as one flat area. */}
          <circle
            cx={centre}
            cy={centre}
            r={centre - 7}
            fill="none"
            stroke="rgba(0,0,0,0.5)"
            strokeWidth="1"
          />
        </g>

        {Array.from({ length: 12 }, (_, i) => {
          const radians = (i * 30 - 90) * (Math.PI / 180);
          const outer = centre - 12;
          const major = i % 3 === 0;
          const inner = outer - (major ? 8 : 4);
          return (
            <line
              key={i}
              x1={centre + Math.cos(radians) * inner}
              y1={centre + Math.sin(radians) * inner}
              x2={centre + Math.cos(radians) * outer}
              y2={centre + Math.sin(radians) * outer}
              stroke={major ? "var(--ink-2)" : "var(--ink-3)"}
              strokeWidth={major ? 2.25 : 1}
              strokeLinecap="round"
            />
          );
        })}

        <g filter={`url(#cast${uid})`}>
          {/* `--ink`, not `--ink-1`. That token does not exist and never did,
              so both of these strokes resolved to nothing and every clock on
              the page showed a single green second hand - a bug that reads as
              a design choice, which is why it survived. */}
          {hand(hours * 30, centre * 0.48, size * 0.032, "var(--ink)", size * 0.06)}
          {hand(minutes * 6, centre * 0.70, size * 0.022, "var(--ink)", size * 0.08)}
          {/* Hidden until the drift is known, so the first frame never shows
              the browser's own time by accident. */}
          {drift !== null &&
            hand(seconds * 6, centre * 0.76, size * 0.009, "var(--accent)", size * 0.14)}
        </g>

        {/* The cap, drawn last so it covers where the hands meet. */}
        <circle cx={centre} cy={centre} r={size * 0.035} fill="var(--panel-raised)" />
        <circle cx={centre} cy={centre} r={size * 0.022} fill="var(--accent)" />

        {/* Glass over everything, and it must not intercept a pointer. */}
        <circle
          cx={centre}
          cy={centre}
          r={centre - 7}
          fill={`url(#glass${uid})`}
          pointerEvents="none"
        />
      </svg>
      <div className="text-center leading-tight">
        <div className="text-xs ink-3">{label}</div>
        <div className="text-sm font-bold tabular-nums">{digital}</div>
      </div>
    </div>
  );
}

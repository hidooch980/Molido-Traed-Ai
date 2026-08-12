"use client";

/**
 * Close-price line with a crosshair tooltip.
 *
 * One series, so no legend — the title names it. The hover layer is not
 * optional decoration: an HTML chart that cannot be interrogated point by point
 * forces the reader to estimate values off an axis, which is exactly what a
 * trading operator must never do.
 */

import { useMemo, useState } from "react";

export interface PricePoint {
  t: string; // ISO event_time
  c: number; // close
}

const PAD = { top: 12, right: 16, bottom: 22, left: 52 };

export default function PriceChart({
  points,
  height = 260,
  label = "Close",
  digits = 5,
}: {
  points: PricePoint[];
  height?: number;
  label?: string;
  digits?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 900; // viewBox width; the SVG scales to its container

  const model = useMemo(() => {
    const clean = points.filter((p) => Number.isFinite(p.c));
    if (clean.length < 2) return null;

    const closes = clean.map((p) => p.c);
    const rawMin = Math.min(...closes);
    const rawMax = Math.max(...closes);
    // A price chart does not start at zero — the question is "how did it move",
    // not "how big is it". A 4% cushion keeps the line off the frame.
    const pad = (rawMax - rawMin || rawMax * 0.01) * 0.04;
    const min = rawMin - pad;
    const max = rawMax + pad;

    const innerW = width - PAD.left - PAD.right;
    const innerH = height - PAD.top - PAD.bottom;
    const x = (i: number) => PAD.left + (i / (clean.length - 1)) * innerW;
    const y = (v: number) => PAD.top + innerH - ((v - min) / (max - min)) * innerH;

    const line = clean
      .map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.c).toFixed(1)}`)
      .join("");
    const area = `${line}L${x(clean.length - 1).toFixed(1)},${PAD.top + innerH}L${PAD.left},${
      PAD.top + innerH
    }Z`;

    const ticks = Array.from({ length: 5 }, (_, i) => min + ((max - min) * i) / 4);

    return { clean, x, y, line, area, ticks, innerW, innerH };
  }, [points, height]);

  if (!model) {
    return (
      <div className="p-6 text-sm ink-3 text-center">
        Not enough price history to plot.
      </div>
    );
  }

  const { clean, x, y, line, area, ticks } = model;
  const active = hover === null ? null : clean[hover];

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    const px = ratio * width;
    const i = Math.round(
      ((px - PAD.left) / (width - PAD.left - PAD.right)) * (clean.length - 1),
    );
    setHover(Math.max(0, Math.min(clean.length - 1, i)));
  }

  const first = clean[0].c;
  const last = clean[clean.length - 1].c;
  const change = ((last - first) / first) * 100;

  return (
    <div>
      <div className="flex items-baseline gap-3 px-4 pt-3">
        <span className="text-xl font-semibold num">{last.toFixed(digits)}</span>
        <span
          className="text-xs num font-semibold"
          style={{ color: change >= 0 ? "var(--good)" : "var(--critical)" }}
        >
          {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%
        </span>
        <span className="text-xs ink-3">over {clean.length} bars</span>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`${label} price line chart`}
        style={{ display: "block", touchAction: "none" }}
      >
        {ticks.map((value, i) => {
          const ty = y(value);
          return (
            <g key={i}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={ty}
                y2={ty}
                stroke="var(--grid)"
                strokeWidth="1"
              />
              <text
                x={PAD.left - 8}
                y={ty + 3}
                textAnchor="end"
                fontSize="10"
                fill="var(--ink-3)"
                className="num"
              >
                {value.toFixed(digits)}
              </text>
            </g>
          );
        })}

        <path d={area} fill="var(--series-1)" opacity="0.08" />
        <path
          d={line}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {active && (
          <g>
            <line
              x1={x(hover!)}
              x2={x(hover!)}
              y1={PAD.top}
              y2={height - PAD.bottom}
              stroke="var(--axis)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <circle
              cx={x(hover!)}
              cy={y(active.c)}
              r="4.5"
              fill="var(--series-1)"
              stroke="var(--panel)"
              strokeWidth="2"
            />
          </g>
        )}

        <line
          x1={PAD.left}
          x2={width - PAD.right}
          y1={height - PAD.bottom}
          y2={height - PAD.bottom}
          stroke="var(--axis)"
          strokeWidth="1"
        />
        <text x={PAD.left} y={height - 6} fontSize="10" fill="var(--ink-3)" className="num">
          {clean[0].t.slice(0, 16).replace("T", " ")}
        </text>
        <text
          x={width - PAD.right}
          y={height - 6}
          fontSize="10"
          fill="var(--ink-3)"
          textAnchor="end"
          className="num"
        >
          {clean[clean.length - 1].t.slice(0, 16).replace("T", " ")}
        </text>
      </svg>

      <div className="px-4 pb-3 h-8 text-xs">
        {active ? (
          <span className="ink-2 num">
            <strong className="font-semibold">{active.c.toFixed(digits)}</strong>
            <span className="ink-3"> · {active.t.slice(0, 16).replace("T", " ")} UTC</span>
          </span>
        ) : (
          <span className="ink-3">Hover the chart to read individual bars.</span>
        )}
      </div>
    </div>
  );
}

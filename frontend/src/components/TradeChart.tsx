"use client";

/**
 * Candles with the bot's open positions drawn on them: entry, stop and target
 * as price lines. Built on TradingView's open-source Lightweight Charts.
 *
 * The bridge publishes no opening time for a position, so a position is a
 * level across the chart rather than a marker on a candle - drawing it at a
 * guessed time would be a made-up fact on a chart somebody trades from.
 */

import { useEffect, useRef } from "react";
import { ColorType, LineStyle, createChart, type UTCTimestamp } from "lightweight-charts";

export interface Candle {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
}

export interface ChartPosition {
  side: string;
  price_open: number;
  stop: number | null;
  target: number | null;
  volume: number;
  label: string;
}

function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export default function TradeChart({
  candles,
  positions,
  labels,
  height = 440,
}: {
  candles: Candle[];
  positions: ChartPosition[];
  labels: { entry: string; stop: string; target: string };
  height?: number;
}) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;

    const ink = token("--ink-2", "#4a4a5a");
    const grid = token("--grid", "#e6e2d9");
    const good = token("--good", "#0f766e");
    const bad = token("--critical", "#b91c1c");
    const accent = token("--accent", "#4338ca");

    const chart = createChart(element, {
      height,
      width: element.clientWidth,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: ink },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: true },
    });

    const series = chart.addCandlestickSeries({
      upColor: good,
      downColor: bad,
      wickUpColor: good,
      wickDownColor: bad,
      borderVisible: false,
    });
    series.setData(
      candles.map((b) => ({
        time: Math.floor(Date.parse(b.t) / 1000) as UTCTimestamp,
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
      })),
    );

    for (const p of positions) {
      const side = p.side === "buy" ? "▲" : "▼";
      series.createPriceLine({
        price: p.price_open,
        color: accent,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `${side} ${labels.entry} ${p.label} ${p.volume}`,
      });
      if (p.stop) {
        series.createPriceLine({
          price: p.stop,
          color: bad,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${labels.stop} ${p.label}`,
        });
      }
      if (p.target) {
        series.createPriceLine({
          price: p.target,
          color: good,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${labels.target} ${p.label}`,
        });
      }
    }
    chart.timeScale().fitContent();

    const resize = new ResizeObserver(() => chart.applyOptions({ width: element.clientWidth }));
    resize.observe(element);
    return () => {
      resize.disconnect();
      chart.remove();
    };
  }, [candles, positions, labels, height]);

  return <div ref={host} dir="ltr" style={{ width: "100%", height }} />;
}

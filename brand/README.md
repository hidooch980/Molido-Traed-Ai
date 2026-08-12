# MolidoTrade AI — brand assets

| File | Use |
| --- | --- |
| `molidotrade-logo.svg` | Full lockup (mark + wordmark). README headers, login screen, docs. |
| `molidotrade-mark.svg` | Square mark. App icon, favicon source, avatars. |
| `molidotrade-mark-mono.svg` | Single-colour outline. Inherits `currentColor` — use on photos, print, or inverted surfaces. |

## The mark

Four candlestick columns form an **M**. Read left to right their closes ascend,
and a cyan polyline links the four closes — the AI reading the sequence, with a
larger, ringed node at the newest bar: the decision point. Letterform and price
action say the same thing, which is the whole idea of the product.

## Colour

| Token | Hex | Role |
| --- | --- | --- |
| Deep navy | `#0B2545` | Base, dark surfaces |
| Ocean | `#1B6CA8` | Mid gradient, "Trade" in wordmark |
| Cyan | `#22D3EE` | Accent, AI signal |
| Signal cyan | `#7DF9FF` | Neural link, focus states |
| Ice | `#EAF6FF` | Strokes on dark, primary text on navy |

Semantic colours used by the dashboard (not part of the logo): profit
`#10B981`, loss `#EF4444`, warning `#F59E0B`.

## Rules

- Minimum clear space around the lockup: the height of the "M" in the wordmark.
- Minimum mark size: 24 px. Below that use `molidotrade-mark-mono.svg`.
- Do not recolour the gradient, stretch the lockup, or set the wordmark in a
  different typeface. The wordmark deliberately uses the system UI stack so no
  external font is ever fetched — the strict artifact/CSP-safe path.
- On busy or photographic backgrounds use the monochrome variant.

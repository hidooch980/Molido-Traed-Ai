# MolidoTrade — visual language (2026)

Chosen 2026-09-02 as a deliberate break from the black/green terminal look.
The design tool proposed dark slate + green accent + Fira; rejected — that is
the aesthetic being left behind, and Fira has no Persian glyphs.

## Decisions
- **Default theme: light, warm paper** (`#f4f2ee`). Dark is a true inverse, lifted off black.
- **Accent: indigo** (`#4338ca` light / `#8b85ff` dark) — as far from green as a
  primary can sit, so a status "good" is never read as a button.
- **Status:** teal / amber / orange / red — semantic, reserved, never reused as a series colour.
- **Type:** Vazirmatn (Persian + Latin, variable, tabular numerals); a mono for tickets and prices.
- **Density:** dashboard (8/10) — 12px radius, 0.5rem panel heads, 0.4rem table cells.
- **Motion:** subtle only, 150–300ms, `prefers-reduced-motion` respected.

## Verified
Every ink / status / accent colour measured ≥ 4.5:1 on every surface in both
themes before these tokens were written (worst pair 4.64:1). The first
draft failed four light pairs by 0.1–0.3 and was refused; this is the second.

## Do not
- Reintroduce green as an accent.  - Emoji as icons (SVG only).  - Text below 12px.

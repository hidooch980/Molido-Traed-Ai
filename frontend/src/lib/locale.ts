import { cookies } from "next/headers";

import { LOCALES, type Locale, direction, translator } from "./i18n";

export const LOCALE_COOKIE = "molido_locale";
export const DEFAULT_LOCALE: Locale = "fa";

/**
 * Server-side locale.
 *
 * Every dashboard page is server-rendered, so the language has to be known
 * before the HTML is produced. Keeping it in client state (as the first
 * version did) meant the server always emitted English and the toggle could
 * only relabel the chrome — the page body stayed untranslated no matter what
 * the user picked. A cookie is readable in both places, so one source of truth
 * serves the server render and the client toggle alike.
 */
export async function getLocale(): Promise<Locale> {
  const store = await cookies();
  const value = store.get(LOCALE_COOKIE)?.value;
  return LOCALES.includes(value as Locale) ? (value as Locale) : DEFAULT_LOCALE;
}

export async function getT() {
  const locale = await getLocale();
  return { locale, t: translator(locale), dir: direction(locale) };
}

export const THEME_COOKIE = "molido_theme";
export const THEMES = ["dark", "light"] as const;
export type Theme = (typeof THEMES)[number];
export const DEFAULT_THEME: Theme = "dark";

/**
 * Server-side theme, for exactly the reason the locale is server-side.
 *
 * The first version kept it in `useState`, which meant the choice lasted until
 * the next page load and then silently reverted - a setting that does not
 * survive a refresh reads as a broken button rather than as a preference.
 *
 * Reading it here also removes the flash: the `dark` class is on `<html>` in
 * the first byte of HTML, so a light-theme user never gets a frame of dark
 * before a client effect corrects it.
 */
export async function getTheme(): Promise<Theme> {
  const store = await cookies();
  const value = store.get(THEME_COOKIE)?.value;
  return THEMES.includes(value as Theme) ? (value as Theme) : DEFAULT_THEME;
}

export const RAIL_COOKIE = "molido_rail";

/** Whether the navigation rail starts collapsed.
 *
 *  Read on the server for the same reason the theme is: a rail that starts
 *  wide and snaps shut after hydration is a visible flinch on every page load,
 *  and the reader notices it every single time.
 */
export async function getRailCollapsed(): Promise<boolean> {
  const store = await cookies();
  return store.get(RAIL_COOKIE)?.value === "collapsed";
}

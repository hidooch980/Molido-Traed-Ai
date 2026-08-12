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

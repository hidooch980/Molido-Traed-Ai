import type { MetadataRoute } from "next";

/**
 * What turns the site into something installable on a phone.
 *
 * Both platforms read this file, and they disagree about almost everything
 * else - iOS ignores `display` and needs the meta tags in the layout, Android
 * ignores those and reads only this. The two are kept deliberately in step:
 * a colour that differs between them shows as a flash of the wrong shade on
 * every launch.
 *
 * `start_url` is the home page rather than the last visited one. Someone
 * opening this from a home screen icon is checking on money, and the useful
 * first screen is the one with the accounts and the floating P&L on it, not
 * wherever they happened to close the browser.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "MolidoTrade AI",
    short_name: "MolidoTrade",
    description: "سامانه هوش معاملاتی، ریسک و اجرا",
    start_url: "/",
    display: "standalone",
    orientation: "portrait-primary",
    // The navy the mark's own field starts from. The splash screen is painted
    // with this before any CSS loads, so a different value here shows as a
    // flash of the wrong colour on every cold launch.
    background_color: "#0B2545",
    theme_color: "#0B2545",
    lang: "fa",
    dir: "rtl",
    categories: ["finance", "productivity"],
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        // Android crops icons to whatever shape the launcher uses, so the
        // maskable one carries its own padding. Without it the corners of the
        // mark are cut off on most Android launchers.
        src: "/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}

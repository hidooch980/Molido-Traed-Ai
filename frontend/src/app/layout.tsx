import type { Metadata, Viewport } from "next";

import Shell from "@/components/Shell";
import { direction } from "@/lib/i18n";
import { getLocale, getRailCollapsed, getTheme } from "@/lib/locale";
import "./globals.css";

export const metadata: Metadata = {
  title: "MolidoTrade AI",
  description: "سامانه هوش معاملاتی، ریسک و اجرا",
  applicationName: "MolidoTrade",
  icons: {
    // SVG first for browsers that take it, PNG for the ones that do not.
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    // iOS does not read the manifest for this and does not render SVG here.
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  appleWebApp: {
    // Android reads `display: standalone` from the manifest. iOS does not -
    // it reads this, and without it the app opens in Safari with the address
    // bar showing, which is a browser tab wearing an app icon.
    capable: true,
    title: "MolidoTrade",
    statusBarStyle: "black-translucent",
  },
  formatDetection: {
    // Safari otherwise turns account numbers and ticket ids into tap-to-call
    // links, which on a page full of both is most of the page.
    telephone: false,
  },
};

export const viewport: Viewport = {
  // Matches the manifest's `theme_color`. A value that differs between the two
  // shows as a flash of the wrong shade on every cold launch.
  themeColor: "#0B2545",
  width: "device-width",
  initialScale: 1,
  // `viewport-fit: cover` lets the page paint under the notch and the home
  // indicator; the safe-area insets in globals.css are what keep content out
  // from under them.
  viewportFit: "cover",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // `lang` and `dir` are decided on the server so the first paint is already
  // right. Setting them from a client effect makes an RTL page render
  // left-to-right for a frame and then jump — visible on every navigation.
  const locale = await getLocale();
  // Read on the server for the same reason as the locale: a theme applied by a
  // client effect shows one frame of the wrong one on every navigation.
  const theme = await getTheme();
  const railCollapsed = await getRailCollapsed();

  return (
    <html lang={locale} dir={direction(locale)} className={theme === "dark" ? "dark" : ""}>
      <body className="font-sans antialiased">
        <Shell locale={locale} theme={theme} initialCollapsed={railCollapsed}>
          {children}
        </Shell>
      </body>
    </html>
  );
}

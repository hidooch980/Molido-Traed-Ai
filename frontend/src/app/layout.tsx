import type { Metadata } from "next";

import Shell from "@/components/Shell";
import { direction } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import "./globals.css";

export const metadata: Metadata = {
  title: "MolidoTrade AI",
  description: "سامانه هوش معاملاتی، ریسک و اجرا",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: "/icon.svg",
  },
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

  return (
    <html lang={locale} dir={direction(locale)} className="dark">
      <body className="font-sans antialiased">
        <Shell locale={locale}>{children}</Shell>
      </body>
    </html>
  );
}

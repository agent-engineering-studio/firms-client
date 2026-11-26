import type { Metadata, Viewport } from "next";
// Bootstrap Italia, the kit of the Italian public administration: served from here, no CDN.
import "bootstrap-italia/dist/css/bootstrap-italia.min.css";
import "leaflet/dist/leaflet.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fuochi visti dal satellite · firms-client",
  description:
    "I fuochi che i satelliti della NASA (FIRMS) hanno visto in un Comune: negli ultimi giorni, nella stagione, e quanto fidarsi.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function Layout({ children }: { children: React.ReactNode }) {
  const lang = process.env.FIRMS_UI_LANG === "en" ? "en" : "it";
  return (
    <html lang={lang}>
      <body>{children}</body>
    </html>
  );
}

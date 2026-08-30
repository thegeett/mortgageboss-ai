/**
 * IBM Plex via next/font — self-hosted, no network request at runtime.  LP-UI-003
 *
 * Wire in app/layout.tsx:
 *
 *   import { plexSans, plexMono, plexSerif } from "@/lib/fonts";
 *   <html className={`${plexSans.variable} ${plexMono.variable} ${plexSerif.variable}`}>
 *
 * Weights are deliberately capped at 600. There is no 700 in this system.
 * Serif is loaded for ONE use: text quoted verbatim from a document. Both styles
 * are loaded: an italic-only face leaves upright `font-serif` with nothing to
 * bind to, and it falls back to Georgia silently.
 */
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";

export const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  weight: ["400"],
  style: ["normal", "italic"],
  variable: "--font-plex-serif",
  display: "swap",
});

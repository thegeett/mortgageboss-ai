import { Providers } from "@/components/providers";
import { plexMono, plexSans, plexSerif } from "@/lib/fonts";
import { PALETTE_COOKIE, THEME_COOKIE, stampedTheme } from "@/lib/theme";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import "./globals.css";
// The colours the role layer in globals.css points at (LP-901). Every file in
// app/palettes/ is imported here; palettes.test.ts fails on one that is not.
import "./palettes/petrol.css";
import "./palettes/blue.css";

export const metadata: Metadata = {
  title: {
    default: "mortgageboss-ai",
    template: "%s · mortgageboss-ai",
  },
  description: "AI-powered loan processing assistant for mortgage processors",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Read on the SERVER so the collapsed state is right in the first byte. Doing
  // this in a client effect would flash the column open on every refresh.
  const jar = await cookies();
  const navCollapsed = jar.get("ledger-nav")?.value === "collapsed";
  // Compact is the default, so only the other two are ever stamped. Anything
  // unexpected in the cookie falls through to compact rather than to nothing.
  const density = jar.get("ledger-density")?.value;
  const densityAttr = density === "comfortable" || density === "relaxed" ? density : undefined;
  // Palette and theme are development-only (LP-902): a production build reads
  // neither cookie, so every user gets the default palette in light whatever
  // their browser holds.
  const { palette, dark } = stampedTheme({
    palette: jar.get(PALETTE_COOKIE)?.value,
    theme: jar.get(THEME_COOKIE)?.value,
  });

  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${plexSerif.variable}${dark ? " dark" : ""}`}
      data-nav={navCollapsed ? "collapsed" : undefined}
      data-density={densityAttr}
      data-palette={palette}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

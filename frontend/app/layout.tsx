import { Providers } from "@/components/providers";
import { plexMono, plexSans, plexSerif } from "@/lib/fonts";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import "./globals.css";

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
  const navCollapsed = (await cookies()).get("ledger-nav")?.value === "collapsed";

  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${plexSerif.variable}`}
      data-nav={navCollapsed ? "collapsed" : undefined}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

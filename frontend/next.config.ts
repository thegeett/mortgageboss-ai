import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A build can be sent somewhere other than `.next`, which is what makes it
  // safe to run one while a dev server is up. `next build` and `next dev` share
  // `.next`, so a verification build clobbers a running dev server's chunks and
  // every request 404s — a failure that presents as an auth error and cost the
  // session running this epic three restarts before anyone connected the two.
  //
  // Default unchanged, so CI, the container image and `pnpm dev` all behave
  // exactly as before. A reviewer runs `NEXT_DIST_DIR=.next-review pnpm build`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Standalone output (C1) — required for the container image. Next traces the modules
  // actually reached and emits a self-contained .next/standalone with its own minimal
  // node_modules plus a server.js entrypoint. Without it the runtime stage has to carry
  // the whole dependency tree (hundreds of MB instead of tens), because `next start`
  // needs it. Local workflows are unaffected: it only adds an output directory — it
  // changes no routing, rendering, or build behaviour.
  output: "standalone",
};

export default nextConfig;

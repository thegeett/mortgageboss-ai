import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output (C1) — required for the container image. Next traces the modules
  // actually reached and emits a self-contained .next/standalone with its own minimal
  // node_modules plus a server.js entrypoint. Without it the runtime stage has to carry
  // the whole dependency tree (hundreds of MB instead of tens), because `next start`
  // needs it. Local workflows are unaffected: it only adds an output directory — it
  // changes no routing, rendering, or build behaviour.
  output: "standalone",
};

export default nextConfig;

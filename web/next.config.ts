import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// One .env at the repo root serves both api/ and web/. Real env vars (Render) win,
// and on Render the root has no .env file, so this is a no-op there.
// forceReload: Next has already loaded (and cached) web/'s own env files by now.
loadEnvConfig(path.resolve(process.cwd(), ".."), false, console, true);

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

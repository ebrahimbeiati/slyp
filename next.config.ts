import type { NextConfig } from "next";

// NEXT_PUBLIC_* is inlined into the browser bundle at BUILD time, not read
// at runtime. That makes a missing NEXT_PUBLIC_API_BASE_URL uniquely nasty:
// lib/Api.ts falls back to http://localhost:8000, the build succeeds, and
// the deployed site ships a chunk telling every visitor's browser to call
// localhost - which fails, and on an HTTPS page is additionally blocked as
// mixed content. Setting the variable in a hosting platform's *runtime*
// environment afterwards does nothing; the value is already baked in.
//
// So: on a hosted build, refuse. Locally the fallback is correct and the
// build carries on. `process.env.VERCEL` is set to "1" by Vercel on every
// build; CI is set by GitHub Actions and most other CI.
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
const isHostedBuild = Boolean(process.env.VERCEL || process.env.CI);

if (isHostedBuild && !apiBaseUrl) {
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is not set for this build.\n\n" +
      "It is inlined into the browser bundle at build time, so without it " +
      "the deployed frontend would call http://localhost:8000 from every " +
      "visitor's browser and fail.\n\n" +
      "Set it to the backend's public origin (no trailing slash, e.g. " +
      "https://slyp-api.up.railway.app) in the hosting platform's " +
      "environment variables, then REDEPLOY - a rebuild is required, not " +
      "just a restart.",
  );
}

if (apiBaseUrl?.endsWith("/")) {
  throw new Error(
    `NEXT_PUBLIC_API_BASE_URL must not end with a slash (got "${apiBaseUrl}"). ` +
      "lib/Api.ts appends /analyse, so a trailing slash produces a //analyse " +
      "path that 404s.",
  );
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
};

export default nextConfig;

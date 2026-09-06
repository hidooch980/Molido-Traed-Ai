/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    // Server-side only default; the browser reads NEXT_PUBLIC_API_URL.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    // Stamped at build time so the running version is visible in the UI.
    // Without it, the only way to confirm a deploy landed is to compare page
    // text by eye — which is how a cached shell gets mistaken for a failed
    // deployment.
    NEXT_PUBLIC_BUILD:
      process.env.NEXT_PUBLIC_BUILD ||
      new Date().toISOString().slice(0, 16).replace("T", " "),
  },
  // In production Caddy owns `/api/*` and forwards it to the API before Next
  // ever sees the request. Locally there is no Caddy, so the relative fetches
  // the components make - `Shell.tsx` asks for `/api/v1/execution/autopilot`
  // on its own origin - had nothing to answer them and every page loaded with
  // a 404 behind it.
  //
  // Development only, and deliberately so: in production this would point at
  // the deployment's own public URL, which is the address Caddy is already
  // serving, and a rewrite there would route the request back into the server
  // that sent it.
  async rewrites() {
    if (process.env.NODE_ENV === "production") return [];
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;

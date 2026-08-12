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

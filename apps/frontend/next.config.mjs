// Security headers for every page (backlog PR-02). The API sends its own (apps/backend/app/core/ratelimit.py).
const api = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1");
const ws = new URL(process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1/simulation/stream");
const dev = process.env.NODE_ENV !== "production";

// Content Security Policy: the page may only talk to itself and the API. Next.js puts small inline
// scripts in every page ('unsafe-inline'); the dev server also needs eval for hot reload. Barcodes
// and labels are shown from blob: URLs; the barcode scanner uses the camera.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  `img-src 'self' data: blob: ${api.origin}`,
  `connect-src 'self' ${api.origin} ${ws.origin}${dev ? " ws://localhost:3000 ws://127.0.0.1:3000" : ""}`,
  "worker-src 'self' blob:",
  "object-src 'self' blob:", // labels open as PDFs from blob: URLs
  "frame-src 'self' blob:",
  "frame-ancestors 'none'", // nobody may show the control center inside a frame (clickjacking)
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=(), payment=()" },
  // No Cross-Origin-Opener-Policy: labels open in a tab the page writes into (lib/auth.ts openProtected).
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  transpilePackages: ["three"],
  poweredByHeader: false, // do not announce the framework
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};
export default nextConfig;

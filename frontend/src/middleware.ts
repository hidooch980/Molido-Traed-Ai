import { NextResponse, type NextRequest } from "next/server";

/**
 * Nothing but the front door is visible until somebody signs in.
 *
 * Every page in this application used to be public, on the reasoning that
 * nothing mutated state so the exposure was only disclosure. That reasoning
 * expired: the deployment now has broker links, challenge rulebooks, a
 * security log and an execution posture, and even the read-only pages describe
 * an account rather than a market.
 *
 * **This is a gate, not the lock.** The lock is on the API - `require_auth`,
 * the permission on every route, and the execution gate that refuses to start
 * the application if a mutating route is reachable without one. A cookie is
 * only evidence that somebody signed in *once*, and this never checks whether
 * it is still valid, because validating it here would mean a database round
 * trip on every asset request. What it buys is that an unauthenticated visitor
 * lands on the door rather than on a dashboard that then fails to fill itself
 * in - which reads as a broken product rather than as a closed one.
 *
 * **The public list is a list, and lists rot.** It is short and it is here
 * rather than spread across the pages it describes, so adding a public route
 * is one edit somebody has to make on purpose. The default is closed: anything
 * not named below needs a session.
 */

/** Reachable without signing in. Everything else is not. */
const PUBLIC_PATHS = new Set([
  "/", // the landing page - what this is, for somebody who has no account
  "/login",
  "/register",
]);

/** Prefixes that are public because they are not pages at all. */
const PUBLIC_PREFIXES = [
  // The API enforces its own authentication, per route, per permission. Gating
  // it here as well would break the sign-in call itself - which is made by a
  // caller who by definition has no session yet.
  "/api/",
  // Verification spends a token that only exists in the link somebody was
  // emailed. Requiring a session to use it would mean the people most likely
  // to click it - new accounts - are the ones it refuses.
  "/verify",
  "/_next/",
  "/icon",
  "/apple-touch-icon",
  "/manifest.webmanifest",
  "/favicon.ico",
  "/robots.txt",
];

const SESSION_COOKIE = "molido_session";

/**
 * The content security policy, with a fresh nonce on every request.
 *
 * A nonce rather than `'unsafe-inline'`, and the difference is the whole
 * value: Next inlines a hydration script into every page, so a policy that
 * permitted inline scripts to allow it would permit *any* inline script -
 * which is precisely the injection class a policy exists to stop. With a
 * nonce, the only inline script that runs is the one this server stamped.
 *
 * `strict-dynamic` means scripts loaded *by* a trusted script are trusted too,
 * so the chunk graph works without listing every filename. It also makes
 * modern browsers ignore the `'self'` beside it, which is left in only as the
 * fallback for browsers that do not implement it.
 *
 * `style-src` still allows inline, and that is a real weakness stated rather
 * than hidden. Tailwind and this application's `style={{}}` props both emit
 * style attributes, and there is no nonce for an attribute. An injected style
 * can deface a page and can read some things through selectors; it cannot
 * execute. That is a smaller hole than the one closed above, and closing it
 * means removing every inline style in thirty-five pages.
 *
 * `connect-src 'self'` is honest here because the API is same-origin behind
 * Caddy. If the dashboard is ever pointed at an API on another host, this line
 * is what will refuse it - loudly, in the console, which is the correct way to
 * find out that the deployment shape changed.
 */
function policyFor(nonce: string): string {
  // Next's dev server compiles modules through `eval` for hot reloading. The
  // production build does not, so the exemption is scoped to the one mode that
  // needs it rather than left in the policy that ships - a CSP with
  // `unsafe-eval` in it permits exactly the injection technique it is there to
  // stop, and it would have been invisible: the policy header still looks
  // strict at a glance.
  const evalForHotReload =
    process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : "";

  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${evalForHotReload}`,
    "style-src 'self' 'unsafe-inline'",
    // `data:` for the QR and the icons; nothing remote.
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    // Nothing here is ever framed, and clickjacking a kill switch is a real
    // shape of attack rather than a theoretical one.
    "frame-ancestors 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    // A form that posts anywhere but here is a form somebody else wrote.
    "form-action 'self'",
    "upgrade-insecure-requests",
  ].join("; ");
}

function withPolicy(response: NextResponse, policy: string): NextResponse {
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // 128 bits from the platform's own generator. `Math.random` is not a source
  // of nonces: a predictable nonce is the same as no nonce at all.
  const nonce = btoa(crypto.randomUUID());
  const policy = policyFor(nonce);

  // Next reads the policy off the *request* to find the nonce, and stamps it
  // onto the scripts it generates. Without this the page's own hydration
  // script is the first thing the policy blocks.
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const pass = () => withPolicy(NextResponse.next({ request: { headers } }), policy);

  // Somebody who is already signed in has no use for the page written to
  // explain the product to strangers. Sending them past it is not a
  // convenience: the landing page carries a "sign in" button and nothing that
  // acknowledges a session, so arriving there after authenticating looks
  // exactly like having failed to authenticate - which is precisely how it was
  // read, four successful sign-ins in a row, while the server recorded every
  // one of them.
  if (pathname === "/" && request.cookies.get(SESSION_COOKIE)) {
    const home = request.nextUrl.clone();
    home.pathname = "/dashboard";
    home.search = "";
    return withPolicy(NextResponse.redirect(home), policy);
  }

  if (PUBLIC_PATHS.has(pathname)) return pass();
  if (PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return pass();
  }

  if (request.cookies.get(SESSION_COOKIE)) return pass();

  // Where they were going, so signing in finishes the journey rather than
  // dropping them on a dashboard and making them navigate again. Carried as a
  // path only - a full URL here is an open redirect, and an open redirect on a
  // login page is how a phishing link borrows your domain.
  const destination = request.nextUrl.clone();
  destination.pathname = "/login";
  destination.search = "";
  if (pathname !== "/dashboard") {
    destination.searchParams.set("next", `${pathname}${search}`);
  }
  return withPolicy(NextResponse.redirect(destination), policy);
}

export const config = {
  // Everything except the static assets Next serves itself. The matcher is a
  // performance concern only - the function above is what decides, and it
  // decides closed.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

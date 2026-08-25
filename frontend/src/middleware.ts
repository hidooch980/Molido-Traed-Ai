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

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname)) return NextResponse.next();
  if (PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return NextResponse.next();
  }

  if (request.cookies.get(SESSION_COOKIE)) return NextResponse.next();

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
  return NextResponse.redirect(destination);
}

export const config = {
  // Everything except the static assets Next serves itself. The matcher is a
  // performance concern only - the function above is what decides, and it
  // decides closed.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

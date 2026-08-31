import { NextResponse } from "next/server";

import { api } from "@/lib/api";

/**
 * The one endpoint the browser may poll for open positions and floating P&L.
 *
 * The API refuses an unauthenticated caller, and the key that satisfies it
 * lives in this process rather than in the page - which is the right way
 * round. Handing the browser a key so it could poll directly would put a
 * credential that can place orders into every reader's devtools.
 *
 * So this is a keyhole: one route, read-only, returning exactly the two things
 * a live view needs. It is not a proxy for the API - a general one would let
 * anyone with the page open reach every route the key can reach.
 *
 * Served from `/live-feed` rather than `/api/live`. The reverse proxy hands
 * every `/api/*` path to the backend, so a Next route under that prefix is
 * unreachable - it returned the API's own 404, which reads as a broken route
 * handler rather than as a path that never arrives here.
 *
 * `stamped_at` is the server's own clock, and the client shows the age rather
 * than the value alone. A poll that quietly stops updating leaves the last
 * numbers on screen looking current, and on a page about open risk that is the
 * failure worth designing against: a floating loss that stopped moving is
 * indistinguishable from one that stopped growing.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  const [positions, realised] = await Promise.all([
    api.positions(),
    api.realised(1),
  ]);

  return NextResponse.json(
    {
      stamped_at: new Date().toISOString(),
      positions: positions.ok ? positions.data : null,
      realised: realised.ok ? realised.data : null,
      // Reported rather than swallowed. A failed read and an account with
      // nothing open both render as an empty table, and only one of them is
      // about trading.
      unreachable: [
        positions.ok ? null : "positions",
        realised.ok ? null : "realised",
      ].filter(Boolean),
    },
    {
      headers: {
        // Never cached. A cached answer on this route is a stale floating
        // P&L presented as a live one.
        "cache-control": "no-store, max-age=0",
      },
    },
  );
}

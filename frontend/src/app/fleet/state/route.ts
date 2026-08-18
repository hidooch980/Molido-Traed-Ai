import { NextResponse } from "next/server";

/**
 * The one route the browser may use to pause or resume an account.
 *
 * The API key lives in this process, not in the page: handing the browser a
 * credential that can reach every route it can reach would be a worse trade
 * than any convenience it buys. So this forwards exactly one call, with
 * exactly the fields that call takes.
 *
 * Not under /api - the reverse proxy claims that prefix for the backend, so a
 * Next route there is unreachable and returns the API's own 404, which reads
 * like a broken handler rather than a path that never arrives.
 */
export const dynamic = "force-dynamic";

const BASE = process.env.MOLIDO_API_URL ?? "http://api:8000";
const KEY = process.env.MOLIDO_INTERNAL_API_KEY ?? "";

export async function POST(request: Request) {
  const body = (await request.json()) as {
    account?: string;
    active?: boolean;
    by?: string;
    reason?: string;
  };

  if (!body.account || typeof body.active !== "boolean" || !body.by?.trim()) {
    // Refused here rather than forwarded. A half-filled call would be refused
    // by the API anyway, and the message it returns would be about a payload
    // the reader never saw.
    return NextResponse.json(
      { error: "account, active and by are all required" },
      { status: 400 },
    );
  }

  const answer = await fetch(
    `${BASE}/api/v1/execution/accounts/${encodeURIComponent(body.account)}/state`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(KEY ? { "X-API-Key": KEY } : {}),
      },
      body: JSON.stringify({
        active: body.active,
        by: body.by,
        reason: body.reason ?? "",
      }),
      cache: "no-store",
    },
  );

  return NextResponse.json(await answer.json(), { status: answer.status });
}

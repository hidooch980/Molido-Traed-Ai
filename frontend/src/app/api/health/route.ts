import { NextResponse } from "next/server";

/**
 * Proof that this process is answering, and nothing more.
 *
 * The container healthcheck used to fetch `/`, which is the heaviest page on
 * the site: server-rendered, several API calls deep. On two cores under load it
 * took longer than the healthcheck timeout, the probe was killed with SIGKILL,
 * and the container was marked unhealthy while every page it served returned
 * 200. The healthcheck was measuring the dashboard, not the process.
 *
 * This renders nothing, reads nothing, and touches no dependency. A liveness
 * probe that fails when the database is slow is a probe that restarts a healthy
 * web server because something else is busy - and restarting it makes the busy
 * thing worse.
 */
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok" });
}

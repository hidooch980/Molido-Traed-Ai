import { LoginPanel } from "@/components/LoginPanel";
import { authLabels } from "@/lib/authLabels";

export const dynamic = "force-dynamic";

export const metadata = { title: "ورود — MolidoTrade AI" };

/**
 * A route of its own, outside the dashboard shell.
 *
 * The shell is a navigation rail over thirty-five pages and a header full of
 * status. None of it is reachable by somebody who has not signed in, and
 * drawing it behind a login form advertises a surface while refusing it - a
 * page that spends its first impression listing what you cannot have, with a
 * "sign in" button in the header, on the sign-in page.
 */
export default async function LoginPage() {
  const { labels, version } = await authLabels();
  return <LoginPanel labels={labels} version={version} mode="sign-in" />;
}

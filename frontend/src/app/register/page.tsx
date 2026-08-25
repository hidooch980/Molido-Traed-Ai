import { LoginPanel } from "@/components/LoginPanel";
import { authLabels } from "@/lib/authLabels";

export const dynamic = "force-dynamic";

export const metadata = { title: "ثبت‌نام — MolidoTrade AI" };

/**
 * The same panel, entered at a different step.
 *
 * Registration already existed - buried inside `/access`, a page somebody has
 * to know about to find. A door nobody can see is a door nobody uses, and the
 * two things a visitor arrives wanting to do are sign in and sign up.
 *
 * A new account lands as a viewer: it reads everything and moves nothing.
 * Saying so on the form matters, because the alternative is somebody creating
 * an account expecting to trade with it and discovering the answer by being
 * refused.
 */
export default async function RegisterPage() {
  const { labels, version } = await authLabels();
  return <LoginPanel labels={labels} version={version} mode="register" />;
}

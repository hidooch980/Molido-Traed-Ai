import { LoginPanel } from "@/components/LoginPanel";
import { authLabels } from "@/lib/authLabels";
import { api } from "@/lib/api";

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
 *
 * **Unless nobody owns this deployment yet, in which case this form makes the
 * owner instead.** A fresh installation has no account with a password, and
 * the API refuses ordinary registration until one exists - correctly, since
 * the first account has to be the administrator. This page had no way to send
 * that request, so the only route to a brand-new deployment's first account
 * was a form that answered every attempt with a refusal telling the person to
 * do something the interface did not offer. Reading the state here is what
 * turns that dead end into a door.
 */
export default async function RegisterPage() {
  const { labels, version } = await authLabels();

  // Defaulting to the ordinary form when this cannot be read is the safe way
  // round: the server refuses a register on an unclaimed deployment with a
  // message that says so, whereas offering to claim one that already has an
  // owner would answer a filled-in form with a 409 for no reason.
  const setup = await api.setup();
  const unclaimed = setup.ok ? !setup.data.claimed : false;

  return (
    <LoginPanel
      labels={labels}
      version={version}
      mode="register"
      unclaimed={unclaimed}
    />
  );
}

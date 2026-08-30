import { UserAdmin } from "@/components/UserAdmin";
import { Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The accounts that can sign in, and who may do what.
 *
 * This page used to be the sign-in form. That moved to `/login`, which left
 * the route holding a door nobody needed and no account management anywhere -
 * the endpoints for it existed and nothing called them, so the only way to
 * create a trader or an administrator was a POST somebody wrote by hand.
 *
 * Read on the server; the listing is behind `users.manage`, so an unauthorised
 * caller gets a refusal rather than an empty list. Those are shown as different
 * things, because a page that renders "no users" when it was actually refused
 * is a page that lies quietly.
 */
export default async function AccessPage() {
  const { t } = await getT();
  const [users, setup, roles] = await Promise.all([
    api.users(),
    api.setup(),
    api.roles(),
  ]);

  const roleNames: Record<string, string> = {};
  if (roles.ok) {
    for (const row of roles.data.roles) {
      roleNames[row.role] = t(`role.${row.role}`);
    }
  }

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("users.title")}</h1>
          <p className="page-lede">{t("users.subtitle")}</p>
        </div>
      </header>

      <Panel title={t("users.people")} subtitle={t("users.peopleSubtitle")}>
        <div className="p-4">
          <UserAdmin
            refused={!users.ok}
            users={users.ok ? users.data.users : []}
            assignableRoles={users.ok ? users.data.assignable_roles : []}
            passwordMinLength={setup.ok ? setup.data.password_min_length : 12}
            labels={{
              title: t("users.title"),
              subtitle: t("users.subtitle"),
              name: t("login.registerName"),
              email: t("signin.email"),
              password: t("signin.password"),
              role: t("users.role"),
              create: t("users.create"),
              creating: t("users.creating"),
              created: t("users.created"),
              failed: t("users.failed"),
              minLength: t("users.minLength"),
              activate: t("users.activate"),
              deactivate: t("users.deactivate"),
              active: t("users.active"),
              inactive: t("users.inactive"),
              neverSignedIn: t("users.neverSignedIn"),
              lastSeen: t("users.lastSeen"),
              refused: t("users.refused"),
              roleNames,
            }}
          />
        </div>
      </Panel>
    </div>
  );
}

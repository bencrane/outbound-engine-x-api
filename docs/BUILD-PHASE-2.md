# Super Admin Build Instructions

The super-admin layer exists above the three-tier tenant model. The super admin (you) creates orgs, manages all orgs, and provisions admin users within those orgs.

```
Super Admin (you)
  └── Organization
       └── Company
            └── User
```

---

## Step 1: Database

Create a `super_admins` table:

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `email` | VARCHAR(255) | NOT NULL, UNIQUE | Login email |
| `password_hash` | VARCHAR(255) | NOT NULL | Hashed password |
| `name` | VARCHAR(100) | NULLABLE | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

This table is NOT org-scoped. It exists above the tenant model.

---

## Step 2: Auth

Add a third auth method to the auth system:

- `get_current_super_admin()` — a FastAPI dependency that validates JWT and checks that the user exists in `super_admins` table. The JWT should have `type: "super_admin"` to distinguish from regular session tokens.
- Super-admin login endpoint: `POST /api/super-admin/login` — accepts email + password, validates against `super_admins` table, returns JWT with `type: "super_admin"`.
- Super-admin tokens carry NO `org_id`. They operate above the tenant layer.

---

## Step 3: Super-admin router

Create `src/routers/super_admin.py` with prefix `/api/super-admin`. All endpoints use `Depends(get_current_super_admin)`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/login` | Super-admin login, returns JWT |
| GET | `/me` | Current super-admin info |
| POST | `/organizations` | Create a new org |
| GET | `/organizations` | List ALL orgs |
| GET | `/organizations/{org_id}` | Get any org |
| PUT | `/organizations/{org_id}` | Update any org |
| DELETE | `/organizations/{org_id}` | Soft delete org |
| POST | `/organizations/{org_id}/users` | Create admin user within an org (bootstraps the first user) |
| GET | `/organizations/{org_id}/companies` | List companies in any org |
| GET | `/organizations/{org_id}/users` | List users in any org |
| POST | `/organizations/{org_id}/api-tokens` | Create API token for an org |
| PUT | `/organizations/{org_id}/provider-config` | Set provider config (Smartlead API key etc.) on an org |

---

## Step 4: Seed the first super-admin

Create a seed script at `scripts/seed_super_admin.py` that:
1. Reads `.env` for `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_PASSWORD`
2. Hashes the password with bcrypt
3. Inserts into `super_admins` table
4. Prints confirmation

Add `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_PASSWORD` to `.env.example`.

---

## Step 5: Wire into main.py

Register the super-admin router in `src/main.py`.

---

## Key Rules

- Super-admin endpoints must NEVER be accessible with regular org-scoped auth
- Regular org-scoped endpoints must NEVER be accessible with super-admin auth
- Super-admin JWT has `type: "super_admin"`, regular user JWT has `type: "session"`
- The `get_current_super_admin` dependency rejects tokens that aren't `type: "super_admin"`
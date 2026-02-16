-- Phase 1 RBAC migration: canonical role names for users

-- Normalize legacy role values before enforcing constraint.
UPDATE users
SET role = 'org_admin'
WHERE role = 'admin';

UPDATE users
SET role = 'company_member'
WHERE role = 'user';

ALTER TABLE users
ALTER COLUMN role SET DEFAULT 'company_member';

ALTER TABLE users
DROP CONSTRAINT IF EXISTS users_role_check;

ALTER TABLE users
ADD CONSTRAINT users_role_check
CHECK (role IN ('org_admin', 'company_admin', 'company_member'));

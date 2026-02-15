#!/usr/bin/env python3
"""Create Phase 1 database tables for Outbound Engine X."""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

SQL = """
-- 1. organizations
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- 2. companies
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_companies_org_id ON companies(org_id);

-- 3. users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name_first VARCHAR(100),
    name_last VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    UNIQUE(org_id, email)
);
CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_users_company_id ON users(company_id);

-- 4. api_tokens
CREATE TABLE IF NOT EXISTS api_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(100),
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_token_hash ON api_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_api_tokens_org_id ON api_tokens(org_id);

-- 5. capabilities
CREATE TABLE IF NOT EXISTS capabilities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. providers
CREATE TABLE IF NOT EXISTS providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_id UUID NOT NULL REFERENCES capabilities(id),
    slug VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. company_entitlements
CREATE TABLE IF NOT EXISTS company_entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    capability_id UUID NOT NULL REFERENCES capabilities(id),
    provider_id UUID NOT NULL REFERENCES providers(id),
    status VARCHAR(20) NOT NULL DEFAULT 'entitled',
    provider_config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, capability_id)
);
CREATE INDEX IF NOT EXISTS idx_company_entitlements_org_id ON company_entitlements(org_id);
CREATE INDEX IF NOT EXISTS idx_company_entitlements_company_id ON company_entitlements(company_id);
"""

SEED_CAPABILITIES = """
INSERT INTO capabilities (slug, name) VALUES
    ('email_outreach', 'Email Outreach'),
    ('linkedin_outreach', 'LinkedIn Outreach')
ON CONFLICT (slug) DO NOTHING;
"""

SEED_PROVIDERS = """
INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'smartlead', 'Smartlead'
FROM capabilities c WHERE c.slug = 'email_outreach'
ON CONFLICT (slug) DO NOTHING;

INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'instantly', 'Instantly'
FROM capabilities c WHERE c.slug = 'email_outreach'
ON CONFLICT (slug) DO NOTHING;

INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'heyreach', 'HeyReach'
FROM capabilities c WHERE c.slug = 'linkedin_outreach'
ON CONFLICT (slug) DO NOTHING;
"""

def main():
    print(f"Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    print("Creating tables...")
    cur.execute(SQL)

    print("Seeding capabilities...")
    cur.execute(SEED_CAPABILITIES)

    print("Seeding providers...")
    cur.execute(SEED_PROVIDERS)

    # Verify
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;")
    tables = cur.fetchall()
    print(f"\nTables created: {[t[0] for t in tables]}")

    cur.execute("SELECT slug, name FROM capabilities;")
    caps = cur.fetchall()
    print(f"Capabilities: {caps}")

    cur.execute("SELECT p.slug, p.name, c.slug as capability FROM providers p JOIN capabilities c ON p.capability_id = c.id;")
    provs = cur.fetchall()
    print(f"Providers: {provs}")

    cur.close()
    conn.close()
    print("\nDone!")

if __name__ == "__main__":
    main()

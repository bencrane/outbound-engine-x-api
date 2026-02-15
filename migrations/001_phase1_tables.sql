-- Phase 1: Core Tables for Outbound Engine X
-- Run this in Supabase SQL Editor

-- 1. organizations
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- 2. companies
CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_companies_org_id ON companies(org_id);

-- 3. users
CREATE TABLE users (
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
CREATE INDEX idx_users_org_id ON users(org_id);
CREATE INDEX idx_users_company_id ON users(company_id);

-- 4. api_tokens
CREATE TABLE api_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(100),
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_api_tokens_token_hash ON api_tokens(token_hash);
CREATE INDEX idx_api_tokens_org_id ON api_tokens(org_id);

-- 5. capabilities
CREATE TABLE capabilities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed capabilities
INSERT INTO capabilities (slug, name) VALUES
    ('email_outreach', 'Email Outreach'),
    ('linkedin_outreach', 'LinkedIn Outreach');

-- 6. providers
CREATE TABLE providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_id UUID NOT NULL REFERENCES capabilities(id),
    slug VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed providers
INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'smartlead', 'Smartlead'
FROM capabilities c WHERE c.slug = 'email_outreach';

INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'instantly', 'Instantly'
FROM capabilities c WHERE c.slug = 'email_outreach';

INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'heyreach', 'HeyReach'
FROM capabilities c WHERE c.slug = 'linkedin_outreach';

-- 7. company_entitlements
CREATE TABLE company_entitlements (
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
CREATE INDEX idx_company_entitlements_org_id ON company_entitlements(org_id);
CREATE INDEX idx_company_entitlements_company_id ON company_entitlements(company_id);

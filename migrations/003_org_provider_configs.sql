-- Add provider_configs to organizations (org-level API keys)
-- Run this in Supabase SQL Editor

ALTER TABLE organizations
ADD COLUMN IF NOT EXISTS provider_configs JSONB DEFAULT '{}';

-- Example structure:
-- {
--   "smartlead": { "api_key": "sl_xxxxx" },
--   "heyreach": { "api_key": "hr_xxxxx" }
-- }

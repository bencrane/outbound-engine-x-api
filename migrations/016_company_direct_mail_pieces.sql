-- Stage 2: direct mail piece mapping storage

CREATE TABLE IF NOT EXISTS company_direct_mail_pieces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),
    external_piece_id VARCHAR(255) NOT NULL,
    piece_type VARCHAR(20) NOT NULL CHECK (piece_type IN ('postcard', 'letter')),
    status VARCHAR(40) NOT NULL DEFAULT 'unknown',
    send_date TIMESTAMPTZ,
    metadata JSONB,
    raw_payload JSONB,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (org_id, provider_id, external_piece_id)
);

CREATE INDEX IF NOT EXISTS idx_company_direct_mail_pieces_org_id ON company_direct_mail_pieces(org_id);
CREATE INDEX IF NOT EXISTS idx_company_direct_mail_pieces_company_id ON company_direct_mail_pieces(company_id);
CREATE INDEX IF NOT EXISTS idx_company_direct_mail_pieces_type ON company_direct_mail_pieces(piece_type);

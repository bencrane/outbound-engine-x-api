DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'company_direct_mail_pieces'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%piece_type%';

    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE company_direct_mail_pieces DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;
END $$;

ALTER TABLE company_direct_mail_pieces
    ADD CONSTRAINT company_direct_mail_pieces_piece_type_check
    CHECK (piece_type IN ('postcard', 'letter', 'self_mailer', 'check'));

-- Stage 1: direct_mail capability + lob provider foundation

INSERT INTO capabilities (slug, name)
VALUES ('direct_mail', 'Direct Mail')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'lob', 'Lob'
FROM capabilities c
WHERE c.slug = 'direct_mail'
ON CONFLICT (slug) DO NOTHING;

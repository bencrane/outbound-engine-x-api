BEGIN;

INSERT INTO capabilities (slug, name)
VALUES ('voicemail_drop', 'Voicemail Drop')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO providers (capability_id, slug, name)
SELECT c.id, 'voicedrop', 'VoiceDrop'
FROM capabilities c
WHERE c.slug = 'voicemail_drop'
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE campaign_sequence_steps
DROP CONSTRAINT IF EXISTS campaign_sequence_steps_channel_check,
ADD CONSTRAINT campaign_sequence_steps_channel_check
CHECK (channel IN ('email', 'linkedin', 'direct_mail', 'voicemail'));

COMMIT;

-- PROPOSAL ONLY. GHUS decision of 2026-10-28 (Ismail Sabbar): the category
-- note "Category confirmed by GHUS on 2026-10-06 (Phase 12 proposal)." that
-- 491 wrote on the 58 organizations whose proposed category GHUS confirmed is
-- removed from them (58 on the live map, read 2026-10-28; the note was the
-- whole of each one's category note).
--
-- Nothing of the decision is lost: it stays recorded in review_item_decision
-- (decided_by "GHUS (approved by Ismail Sabbar, 2026-10-06)", reason
-- "actor_category=... confirmed"). Only the note goes. A note edited since is
-- no longer this exact text and is left alone. Type "other" requires a note
-- (ck_actor_other_type_note), so such a row would keep it; none of the 58 is.
-- Idempotent: a second run changes nothing.
BEGIN;

UPDATE actor
SET category_note = NULL,
    updated_at = now()
WHERE category_note = 'Category confirmed by GHUS on 2026-10-06 (Phase 12 proposal).'
  AND category_type IS DISTINCT FROM 'other';

COMMIT;

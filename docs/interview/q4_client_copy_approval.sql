-- Interview question: "Do clients approve copy before launch?"
-- YES: records who approved each campaign and when. (The "30 - Client Review"
--      stage is already on the board.)
-- NO:  skip this file. Move cards past "30 - Client Review" without waiting.

alter table public.campaigns
  add column client_approved_at timestamptz,
  add column client_approved_by text,
  add column client_feedback    text;

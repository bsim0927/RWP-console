-- Intake: what the analyst records when a fund is filed (decisions F2, B5, G4).
CREATE TABLE "public"."intake" (
  "fund_id"          text                     NOT NULL,
  "referred_by"      text,
  "owner"            text,
  "sponsor_deadline" date,
  "filed_on"         date,
  "share_class"      text,
  "updated_at"       timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "intake_pkey" PRIMARY KEY (fund_id)
);

ALTER TABLE "public"."intake"
  ENABLE ROW LEVEL SECURITY;

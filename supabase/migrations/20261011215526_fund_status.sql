-- Fund pipeline status in the database, replacing PIPELINE.md (decision G3).
CREATE TABLE "public"."fund_status" (
  "id"          bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  "fund_id"     text                     NOT NULL,
  "status"      text                     NOT NULL,
  "reviewer_id" text,
  "source"      text                     NOT NULL,
  "note"        text,
  "created_at"  timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "fund_status_check" CHECK (((source = 'import'::text) OR (reviewer_id IS NOT NULL))),
  CONSTRAINT "fund_status_pkey" PRIMARY KEY (id),
  CONSTRAINT "fund_status_source_check" CHECK ((source = ANY (ARRAY['import'::text, 'console'::text]))),
  CONSTRAINT "fund_status_status_check"
    CHECK
    ((status = ANY (ARRAY['Not reviewed'::text, 'Triaged'::text, 'Under review'::text, 'Deep DD'::text, 'IC ready'::text, 'Covered'::text, 'Watch'::text,
    'Reviewed and not covered'::text])))
);

ALTER TABLE "public"."fund_status"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."fund_status"
  ADD CONSTRAINT "fund_status_reviewer_id_fkey" FOREIGN KEY (reviewer_id) REFERENCES public.reviewers(id);

CREATE INDEX fund_status_fund_idx ON public.fund_status USING btree (fund_id, id DESC);

-- Disposition confirmations and CIO sign-off (decision F5).
CREATE TABLE "public"."disposition_confirmations" (
  "id"          bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  "run_id"      uuid                     NOT NULL,
  "disposition" text                     NOT NULL,
  "reviewer_id" text                     NOT NULL,
  "sign_off"    boolean                  NOT NULL DEFAULT false,
  "reason"      text,
  "created_at"  timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "disposition_confirmations_pkey" PRIMARY KEY (id)
);

ALTER TABLE "public"."disposition_confirmations"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."disposition_confirmations"
  ADD CONSTRAINT "disposition_confirmations_reviewer_id_fkey" FOREIGN KEY (reviewer_id) REFERENCES public.reviewers(id);

ALTER TABLE "public"."disposition_confirmations"
  ADD CONSTRAINT "disposition_confirmations_run_id_fkey" FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE CASCADE;

CREATE INDEX disposition_confirmations_run_idx ON public.disposition_confirmations USING btree (run_id, id DESC);

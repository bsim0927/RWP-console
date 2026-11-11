-- Analyst review: reviewers, gate reviews and manual checks (decisions G1, G2, C3, C4).
CREATE TABLE "public"."gate_checks" (
  "id"          bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  "run_id"      uuid                     NOT NULL,
  "gate_id"     text                     NOT NULL,
  "check_id"    text                     NOT NULL,
  "ok"          boolean                  NOT NULL,
  "note"        text,
  "reviewer_id" text                     NOT NULL,
  "created_at"  timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "gate_checks_pkey" PRIMARY KEY (id)
);

ALTER TABLE "public"."gate_checks"
  ENABLE ROW LEVEL SECURITY;

CREATE TABLE "public"."gate_reviews" (
  "id"          bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  "run_id"      uuid                     NOT NULL,
  "gate_id"     text                     NOT NULL,
  "reviewer_id" text                     NOT NULL,
  "verdict"     text                     NOT NULL,
  "result"      text,
  "reason"      text                     NOT NULL,
  "document"    text,
  "page"        integer,
  "created_at"  timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "gate_reviews_check" CHECK (((verdict = 'agree'::text) OR ((result IS NOT NULL) AND (document IS NOT NULL) AND (page IS NOT NULL)))),
  CONSTRAINT "gate_reviews_page_check" CHECK ((page > 0)),
  CONSTRAINT "gate_reviews_pkey" PRIMARY KEY (id),
  CONSTRAINT "gate_reviews_reason_check" CHECK ((length(btrim(reason)) > 0)),
  CONSTRAINT "gate_reviews_result_check" CHECK ((result = ANY (ARRAY['Pass'::text, 'Fail'::text, 'Incomplete'::text]))),
  CONSTRAINT "gate_reviews_verdict_check" CHECK ((verdict = ANY (ARRAY['agree'::text, 'override'::text])))
);

ALTER TABLE "public"."gate_reviews"
  ENABLE ROW LEVEL SECURITY;

CREATE TABLE "public"."reviewers" (
  "id"         text                     NOT NULL,
  "name"       text                     NOT NULL,
  "role"       text                     NOT NULL,
  "active"     boolean                  NOT NULL DEFAULT true,
  "created_at" timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "reviewers_id_check" CHECK ((id ~ '^[a-z][a-z0-9_]{1,30}$'::text)),
  CONSTRAINT "reviewers_name_check" CHECK ((length(btrim(name)) > 0)),
  CONSTRAINT "reviewers_pkey" PRIMARY KEY (id),
  CONSTRAINT "reviewers_role_check" CHECK ((role = ANY (ARRAY['analyst'::text, 'cio'::text])))
);

ALTER TABLE "public"."reviewers"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."gate_checks"
  ADD CONSTRAINT "gate_checks_run_id_fkey" FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE CASCADE;

ALTER TABLE "public"."gate_reviews"
  ADD CONSTRAINT "gate_reviews_run_id_fkey" FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE CASCADE;

ALTER TABLE "public"."gate_checks"
  ADD CONSTRAINT "gate_checks_reviewer_id_fkey" FOREIGN KEY (reviewer_id) REFERENCES public.reviewers(id);

ALTER TABLE "public"."gate_reviews"
  ADD CONSTRAINT "gate_reviews_reviewer_id_fkey" FOREIGN KEY (reviewer_id) REFERENCES public.reviewers(id);

CREATE INDEX gate_checks_run_idx ON public.gate_checks USING btree (run_id, gate_id, check_id, id DESC);

CREATE INDEX gate_reviews_run_idx ON public.gate_reviews USING btree (run_id, gate_id, id DESC);

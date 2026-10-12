-- Screen jobs and the console event log in the database, not in memory (Vercel port).
CREATE TABLE "public"."console_events" (
  "id"    bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  "ts"    timestamp with time zone NOT NULL DEFAULT now(),
  "kind"  text                     NOT NULL,
  "level" text                     NOT NULL,
  "msg"   text                     NOT NULL,
  "extra" json                     NOT NULL DEFAULT '{}'::json,
  CONSTRAINT "console_events_level_check" CHECK ((level = ANY (ARRAY['info'::text, 'warn'::text, 'error'::text]))),
  CONSTRAINT "console_events_pkey" PRIMARY KEY (id)
);

ALTER TABLE "public"."console_events"
  ENABLE ROW LEVEL SECURITY;

CREATE TABLE "public"."screen_jobs" (
  "id"         text                     NOT NULL,
  "fund_id"    text                     NOT NULL,
  "fund_name"  text                     NOT NULL,
  "extractor"  text                     NOT NULL,
  "judge"      text                     NOT NULL,
  "status"     text                     NOT NULL,
  "gates"      json                     NOT NULL,
  "steps"      json                     NOT NULL DEFAULT '[]'::json,
  "run_stamp"  text,
  "error"      text,
  "created_at" timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at" timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "screen_jobs_pkey" PRIMARY KEY (id),
  CONSTRAINT "screen_jobs_status_check" CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'done'::text, 'error'::text])))
);

ALTER TABLE "public"."screen_jobs"
  ENABLE ROW LEVEL SECURITY;

CREATE INDEX screen_jobs_created_idx ON public.screen_jobs USING btree (created_at DESC);

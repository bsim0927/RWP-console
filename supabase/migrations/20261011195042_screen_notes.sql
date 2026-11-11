-- Screen notes, versioned (decisions F1, F4).
CREATE TABLE "public"."screen_notes" (
  "id"          bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  "run_id"      uuid                     NOT NULL,
  "body"        text                     NOT NULL,
  "author"      text                     NOT NULL,
  "reviewer_id" text,
  "model"       text,
  "created_at"  timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "screen_notes_author_check" CHECK ((author = ANY (ARRAY['tool'::text, 'analyst'::text]))),
  CONSTRAINT "screen_notes_check" CHECK (((author = 'tool'::text) OR (reviewer_id IS NOT NULL))),
  CONSTRAINT "screen_notes_pkey" PRIMARY KEY (id)
);

ALTER TABLE "public"."screen_notes"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."screen_notes"
  ADD CONSTRAINT "screen_notes_reviewer_id_fkey" FOREIGN KEY (reviewer_id) REFERENCES public.reviewers(id);

ALTER TABLE "public"."screen_notes"
  ADD CONSTRAINT "screen_notes_run_id_fkey" FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE CASCADE;

CREATE INDEX screen_notes_run_idx ON public.screen_notes USING btree (run_id, id DESC);

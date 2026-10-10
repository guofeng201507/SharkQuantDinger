-- Product documentation stored per locale, so the in-app user guide (/docs) can be
-- edited at runtime instead of requiring a frontend rebuild.
CREATE TABLE IF NOT EXISTS qd_docs (
    id          SERIAL      PRIMARY KEY,
    slug        TEXT        NOT NULL,
    locale      TEXT        NOT NULL,
    title       TEXT,
    content_md  TEXT        NOT NULL,
    updated_by  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT qd_docs_slug_locale_key UNIQUE (slug, locale)
);

CREATE INDEX IF NOT EXISTS idx_qd_docs_slug ON qd_docs (slug);

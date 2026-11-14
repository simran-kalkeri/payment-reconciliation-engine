"""Create durable staging, canonical payments, and versioned reconciliation."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for ddl in (
        """
        CREATE TABLE input_files (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          source text NOT NULL,
          kind text NOT NULL CHECK (kind IN ('ledger', 'settlement')),
          schema_version int NOT NULL CHECK (schema_version = 1),
          date_format text NOT NULL CHECK (date_format IN ('iso', 'dmy', 'named')),
          sha256 char(64) NOT NULL,
          storage_key text NOT NULL,
          status text NOT NULL DEFAULT 'loading' CHECK (status IN ('loading','staged','rejected')),
          row_count int NOT NULL DEFAULT 0 CHECK (row_count >= 0),
          error text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (source, kind, schema_version, date_format, sha256)
        )
        """,
        """
        CREATE TABLE canonical (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          kind text NOT NULL CHECK (kind IN ('ledger', 'settlement')),
          source text NOT NULL,
          external_id text NOT NULL,
          merchant text NOT NULL,
          account text NOT NULL,
          reference text NOT NULL,
          currency char(3) NOT NULL CHECK (currency = 'INR'),
          gross bigint NOT NULL CHECK (gross > 0),
          net bigint,
          fee bigint,
          business_date date NOT NULL,
          deadline_at timestamptz,
          available_at timestamptz,
          fingerprint char(64) NOT NULL,
          UNIQUE (kind, source, external_id),
          UNIQUE (kind, id),
          CHECK (
            (kind = 'ledger' AND deadline_at IS NOT NULL AND available_at IS NULL AND net IS NULL AND fee IS NULL)
            OR (kind = 'settlement' AND deadline_at IS NULL AND available_at IS NOT NULL
                AND net IS NOT NULL AND fee IS NOT NULL AND net >= 0 AND fee >= 0 AND net + fee = gross)
          )
        )
        """,
        """
        CREATE TABLE staged_rows (
          file_id bigint NOT NULL REFERENCES input_files(id),
          row_number int NOT NULL CHECK (row_number > 0),
          payload text NOT NULL,
          status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
          attempts int NOT NULL DEFAULT 0 CHECK (attempts >= 0),
          canonical_id bigint REFERENCES canonical(id),
          rejection_code text,
          rejection_reason text,
          worker text,
          created_at timestamptz NOT NULL DEFAULT now(),
          processed_at timestamptz,
          PRIMARY KEY (file_id, row_number),
          CHECK (
            (status = 'pending' AND canonical_id IS NULL AND rejection_code IS NULL AND rejection_reason IS NULL)
            OR (status = 'accepted' AND canonical_id IS NOT NULL AND rejection_code IS NULL AND rejection_reason IS NULL)
            OR (status = 'rejected' AND canonical_id IS NULL AND rejection_code IS NOT NULL AND rejection_reason IS NOT NULL)
          )
        )
        """,
        "CREATE INDEX staged_pending ON staged_rows (file_id, row_number) WHERE status='pending'",
        "CREATE INDEX staged_canonical ON staged_rows (canonical_id)",
        """
        CREATE VIEW canonical_membership AS
          SELECT file_id, canonical_id FROM staged_rows WHERE status='accepted'
        """,
        """
        CREATE VIEW input_quality AS
          SELECT file_id, row_number, status, rejection_code FROM staged_rows
        """,
        """
        CREATE TABLE operations (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          stage text NOT NULL,
          status text NOT NULL CHECK (status IN ('running','done','failed')),
          detail jsonb NOT NULL,
          error text,
          started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          finished_at timestamptz
        )
        """,
        """
        CREATE TABLE matcher_configs (
          hash char(64) PRIMARY KEY,
          version text NOT NULL,
          rules jsonb NOT NULL
        )
        """,
        """
        CREATE TABLE results (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          scope text NOT NULL,
          business_date date NOT NULL,
          cutoff timestamptz NOT NULL,
          context_hash char(64) NOT NULL UNIQUE,
          result_hash char(64) NOT NULL,
          config_hash char(64) NOT NULL REFERENCES matcher_configs(hash),
          report jsonb NOT NULL,
          evidence jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (scope, business_date, id)
        )
        """,
        """
        CREATE TABLE matches (
          result_id bigint NOT NULL REFERENCES results(id),
          ledger_id bigint NOT NULL,
          settlement_id bigint NOT NULL,
          ledger_kind text GENERATED ALWAYS AS ('ledger'::text) STORED,
          settlement_kind text GENERATED ALWAYS AS ('settlement'::text) STORED,
          method text NOT NULL CHECK (method IN ('exact','diagnostic','fuzzy')),
          evidence jsonb NOT NULL,
          PRIMARY KEY (result_id, ledger_id),
          UNIQUE (result_id, settlement_id),
          FOREIGN KEY (ledger_kind, ledger_id) REFERENCES canonical(kind, id),
          FOREIGN KEY (settlement_kind, settlement_id) REFERENCES canonical(kind, id),
          CHECK (ledger_id <> settlement_id)
        )
        """,
        """
        CREATE TABLE current_results (
          scope text NOT NULL,
          business_date date NOT NULL,
          result_id bigint NOT NULL,
          PRIMARY KEY (scope, business_date),
          FOREIGN KEY (scope, business_date, result_id) REFERENCES results(scope,business_date,id)
        )
        """,
        """
        CREATE TABLE exceptions (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          scope text NOT NULL,
          business_date date NOT NULL,
          category text NOT NULL CHECK (category IN (
            'missing_settlement','duplicate_settlement','amount_mismatch','late_settlement',
            'reference_mismatch','ambiguous_match','unexpected_settlement','data_quality')),
          subject text NOT NULL,
          merchant text,
          amount bigint CHECK (amount >= 0),
          active boolean NOT NULL DEFAULT true,
          review_status text NOT NULL DEFAULT 'open' CHECK (review_status IN ('open','resolved')),
          version int NOT NULL DEFAULT 1,
          result_id bigint NOT NULL REFERENCES results(id),
          evidence jsonb NOT NULL,
          UNIQUE (scope, business_date, category, subject)
        )
        """,
        """
        CREATE TABLE exception_history (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          exception_id bigint NOT NULL REFERENCES exceptions(id),
          actor text NOT NULL CHECK (btrim(actor) <> ''),
          action text NOT NULL CHECK (action IN ('detected','cleared','reactivated','updated','resolve','reopen')),
          previous_state jsonb,
          new_state jsonb NOT NULL,
          reason text NOT NULL CHECK (btrim(reason) <> ''),
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """,
        "CREATE INDEX history_exception ON exception_history (exception_id, id)",
        """
        CREATE FUNCTION protect_audit_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'application audit history is append-only';
        END;
        $$
        """,
        """
        CREATE TRIGGER append_only_history BEFORE UPDATE OR DELETE OR TRUNCATE ON exception_history
        FOR EACH STATEMENT EXECUTE FUNCTION protect_audit_history()
        """,
    ):
        op.execute(ddl)


def downgrade():
    for table in ("exception_history", "exceptions", "current_results", "matches", "results",
                  "matcher_configs", "operations"):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION protect_audit_history()")
    op.execute("DROP VIEW input_quality, canonical_membership")
    op.execute("DROP TABLE staged_rows, canonical, input_files")

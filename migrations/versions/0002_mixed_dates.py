"""Accept input files whose declared date format is mixed."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("input_files_date_format_check", "input_files", type_="check")
    op.create_check_constraint("input_files_date_format_check", "input_files",
                               "date_format IN ('iso', 'dmy', 'named', 'mixed')")


def downgrade():
    op.drop_constraint("input_files_date_format_check", "input_files", type_="check")
    op.create_check_constraint("input_files_date_format_check", "input_files",
                               "date_format IN ('iso', 'dmy', 'named')")

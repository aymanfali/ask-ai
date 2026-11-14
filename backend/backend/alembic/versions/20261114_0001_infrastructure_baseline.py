"""Establish the initial migration baseline.

No domain tables are created in Milestone 1. This revision makes the migration
pipeline executable and provides a stable parent for the first domain migration.
"""

from typing import Sequence


revision: str = "20261114_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the migration baseline; domain tables arrive in later milestones."""
    pass


def downgrade() -> None:
    """Remove the empty baseline revision."""
    pass

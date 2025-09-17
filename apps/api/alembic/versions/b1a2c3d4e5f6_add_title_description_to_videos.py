"""add title and description to videos

Revision ID: b1a2c3d4e5f6
Revises: 32058bb167aa
Create Date: 2025-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1a2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '32058bb167aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('videos', sa.Column('title', sa.String(), nullable=False, server_default=''))
    op.add_column('videos', sa.Column('description', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('videos', 'description')
    op.drop_column('videos', 'title')



"""add knowledge_article table for F11 knowledge base

Revision ID: c9f1a2b7d4e6
Revises: 8b289cc88989
Create Date: 2026-10-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9f1a2b7d4e6'
down_revision = '8b289cc88989'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'knowledge_article',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('tags', sa.String(length=300), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('source_case_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['source_case_id'], ['case.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('knowledge_article', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_knowledge_article_is_published'),
            ['is_published'], unique=False,
        )


def downgrade():
    with op.batch_alter_table('knowledge_article', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_article_is_published'))
    op.drop_table('knowledge_article')

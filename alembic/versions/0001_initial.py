"""Initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-07-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_login', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'license',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('license_key', sa.String(), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('pricing_plan', sa.String(), nullable=True),
        sa.Column('features', sa.String(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'lead',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('place_id', sa.String(), nullable=True),
        sa.Column('enriched_company', sa.String(), nullable=True),
        sa.Column('enriched_linkedin', sa.String(), nullable=True),
        sa.Column('enriched_source', sa.String(), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=True),
        sa.Column('verification_details', sa.String(), nullable=True),
        sa.Column('normalized_phone', sa.String(), nullable=True),
        sa.Column('normalized_name', sa.String(), nullable=True),
        sa.Column('normalized_address', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_lead_place_id'), 'lead', ['place_id'], unique=True)

    op.create_table(
        'suppression',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_suppression_email'), 'suppression', ['email'], unique=False)

    op.create_table(
        'campaign',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('recipient_count', sa.Integer(), nullable=True),
        sa.Column('sent_count', sa.Integer(), nullable=True),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'emaillog',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('recipient', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('message_id', sa.String(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'replylog',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('sender', sa.String(), nullable=True),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('message_id', sa.String(), nullable=True),
        sa.Column('in_reply_to', sa.String(), nullable=True),
        sa.Column('body_text', sa.String(), nullable=True),
        sa.Column('body_html', sa.String(), nullable=True),
        sa.Column('raw_message', sa.String(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('replylog')
    op.drop_table('emaillog')
    op.drop_table('campaign')
    op.drop_table('suppression')
    op.drop_index(op.f('ix_lead_place_id'), table_name='lead')
    op.drop_table('lead')
    op.drop_table('license')
    op.drop_table('user')

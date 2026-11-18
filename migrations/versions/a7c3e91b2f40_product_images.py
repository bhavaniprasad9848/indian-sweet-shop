"""Store uploaded product photos in the database

Revision ID: a7c3e91b2f40
Revises: d42f6085d63d
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3e91b2f40"
down_revision = "d42f6085d63d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])
    op.create_index("ix_product_images_created_at", "product_images", ["created_at"])


def downgrade():
    op.drop_index("ix_product_images_created_at", table_name="product_images")
    op.drop_index("ix_product_images_product_id", table_name="product_images")
    op.drop_table("product_images")

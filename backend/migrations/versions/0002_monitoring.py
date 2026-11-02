"""Per-workflow monitoring control; existing workflows remain monitored."""
from alembic import op
import sqlalchemy as sa
revision='0002_monitoring'
down_revision='0001_initial'
branch_labels=None
depends_on=None
def upgrade():
 op.add_column('workflows',sa.Column('monitoring_enabled',sa.Boolean(),nullable=False,server_default=sa.text('true')))
def downgrade():
 op.drop_column('workflows','monitoring_enabled')

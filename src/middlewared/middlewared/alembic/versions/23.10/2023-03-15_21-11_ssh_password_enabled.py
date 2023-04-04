"""SSH password enabled

Revision ID: 1c060aa856ca
Revises: 91a4e09f5b7a
Create Date: 2023-02-12 10:45:59.865895+00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1c060aa856ca'
down_revision = '91a4e09f5b7a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('account_bsdusers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bsdusr_ssh_password_enabled', sa.Boolean(), nullable=False, server_default='0'))

    conn = op.get_bind()
    for passwordauth, rootlogin, adminlogin in conn.execute("""
        SELECT ssh_passwordauth, ssh_rootlogin, ssh_adminlogin FROM services_ssh
    """).fetchall():
        if int(passwordauth):
            op.execute("UPDATE account_bsdusers SET bsdusr_ssh_password_enabled = IIF(bsdusr_password_disabled, 0, 1) "
                       "WHERE bsdusr_builtin = 0")

            op.execute(f"UPDATE account_bsdusers SET bsdusr_ssh_password_enabled = {int(rootlogin)} WHERE bsdusr_uid = 0")
            op.execute(f"UPDATE account_bsdusers SET bsdusr_ssh_password_enabled = {int(adminlogin)} WHERE bsdusr_uid = 950")

    with op.batch_alter_table('services_ssh', schema=None) as batch_op:
        batch_op.drop_column('ssh_adminlogin')
        batch_op.drop_column('ssh_rootlogin')
        batch_op.add_column(sa.Column('ssh_password_login_groups', sa.TEXT(), nullable=False, server_default='[]'))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('services_ssh', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ssh_rootlogin', sa.BOOLEAN(), nullable=False))
        batch_op.add_column(sa.Column('ssh_adminlogin', sa.BOOLEAN(), server_default=sa.text("'1'"), nullable=False))

    with op.batch_alter_table('account_bsdusers', schema=None) as batch_op:
        batch_op.drop_column('bsdusr_ssh_password_enabled')

    # ### end Alembic commands ###

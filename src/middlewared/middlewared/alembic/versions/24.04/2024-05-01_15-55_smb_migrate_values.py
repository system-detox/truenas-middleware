"""Fix up SMB paramters and users

Revision ID: f38c2bbe776a
Revises: d774066c6c0c
Create Date: 2024-05-01 15:55:42.754331+00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f38c2bbe776a'
down_revision = 'd774066c6c0c'
branch_labels = None
depends_on = None

SHARE_TABLE = "sharing_cifs_share"
PURPOSE_KEY = "cifs_purpose"
READONLY_KEY = "cifs_ro"

USER_TABLE = "account_bsdusers"
SMB_KEY = "bsdusr_smb"
HOME_KEY = "bsdusr_home"
LEGACY_HOME = "/nonexistent"
EMPTY_DIR = "/var/empty"


def upgrade():
    conn = op.get_bind()

    # convert any cluster READ_ONLY shares to a default share
    # with readonly checked
    stmnt = (
        f"UPDATE {SHARE_TABLE} "
        f"SET {PURPOSE_KEY} = ?, {READONLY_KEY} = ? "
        f"WHERE {PURPOSE_KEY} = ?"
    )
    conn.execute(stmnt, ['DEFAULT_SHARE', 1, 'READ_ONLY'])

    # convert any cluster DEFAULT_CLUSTER_SHARE shares to
    # DEFAULT_SHARE
    stmnt = (
        f"UPDATE {SHARE_TABLE} "
        f"SET {PURPOSE_KEY} = ? "
        f"WHERE {PURPOSE_KEY} = ?"
    )
    conn.execute(stmnt, ['DEFAULT_SHARE', 'DEFAULT_CLUSTER_SHARE'])

    # convert any SMB users with a home directory of `/nonexistent` to
    # having a home directory of `/var/empty`
    stmnt = (
       f"UPDATE {USER_TABLE} "
       f"SET {HOME_KEY} = ? "
       f"WHERE {HOME_KEY} = ? AND {SMB_KEY} = ?"
    )
    conn.execute(stmnt, [EMPTY_DIR, LEGACY_HOME, 1])


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###

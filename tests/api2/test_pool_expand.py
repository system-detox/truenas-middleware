import pytest

from middlewared.test.integration.assets.pool import another_pool
from middlewared.test.integration.utils import call, ssh

pytestmark = pytest.mark.zfs


def test_expand_pool():
    with another_pool() as pool:
        disk = pool["topology"]["data"][0]["disk"]
        original_partition_size = call("disk.list_partitions", disk)[-1]["size"]
        # Ensure that the test pool vdev is way larger than 2 GiB
        assert original_partition_size > 2147483648 * 2

        # Transform this pool into a pool on a vdev with a partition that is only 2 GiB
        ssh(f"zpool export {pool['name']}")
        ssh(f"sgdisk -d 2 /dev/{disk}")
        ssh(f"sgdisk -n 2:0:+2GiB -t 2:BF01 /dev/{disk}")
        small_partition = call("disk.list_partitions", disk)[-1]
        assert small_partition["size"] < 2147483648 * 1.01
        device = "disk/by-partuuid/" + small_partition["partition_uuid"]
        ssh(f"zpool create {pool['name']} -o altroot=/mnt -f {device}")
        # Ensure that the pool size is small now
        assert call("pool.get_instance", pool["id"])["size"] < 2147483648 * 1.01
        ssh(f"touch /mnt/{pool['name']}/test")

        call("pool.expand", pool["id"], job=True)

        new_partition = call("disk.list_partitions", disk)[-1]
        # Ensure that the partition size is way larger than 2 GiB
        assert new_partition["size"] > 2147483648 * 2
        # Ensure that the pool size was increased
        assert call("pool.get_instance", pool["id"])["size"] > 2147483648 * 2
        # Ensure that data was not destroyed
        assert ssh(f"ls /mnt/{pool['name']}") == "test\n"

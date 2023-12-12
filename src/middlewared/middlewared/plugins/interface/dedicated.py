from enum import IntFlag


class Dedicated(IntFlag):
    NVME_ROCE_A = 0x00000001
    NVME_ROCE_B = 0x00010000

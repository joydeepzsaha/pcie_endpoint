"""PCIe DLLP CRC16 and reflected CRC32 helpers."""


def dllp_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xD008) if crc & 1 else crc >> 1
            crc &= 0xFFFF
    return crc ^ 0xFFFF


def crc32_update(crc: int, byte: int) -> int:
    crc ^= byte & 0xFF
    for _ in range(8):
        crc = ((crc >> 1) ^ 0xEDB88320) if crc & 1 else crc >> 1
        crc &= 0xFFFFFFFF
    return crc


def crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = crc32_update(crc, byte)
    return crc ^ 0xFFFFFFFF

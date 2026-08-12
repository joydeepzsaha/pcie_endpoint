"""Reference traffic and Gen1 logical-PHY coding for endpoint line-rate tests."""

from dataclasses import dataclass
import zlib

from cocotbext.pcie.core.dllp import Dllp, DllpType, FcScale


PHY_USER_IS_DLLP = 1
PHY_USER_IS_TLP = 2
MESSAGE_TYPE_BASE = 0x10


@dataclass(frozen=True)
class MessageTlp:
    route: int
    code: int
    requester_id: int
    tag: int
    route_data: int
    payload: bytes


def build_message_tlp(
    route: int,
    code: int,
    requester_id: int,
    tag: int = 0,
    route_data: int = 0,
    payload: bytes = b"",
) -> bytes:
    """Build a four-DWORD PCIe Message or Message-with-Data TLP."""
    if route < 0 or route > 5:
        raise ValueError("message route must be in the range 0 through 5")
    if len(payload) % 4:
        raise ValueError("message payload must contain complete DWORDs")
    length_dw = len(payload) // 4
    if length_dw > 1024:
        raise ValueError("message payload exceeds the TLP length field")
    fmt = 0b011 if payload else 0b001
    tlp_type = MESSAGE_TYPE_BASE | route
    encoded_length = 0 if length_dw in (0, 1024) else length_dw
    dw0 = (fmt << 29) | (tlp_type << 24) | encoded_length
    dw1 = ((requester_id & 0xFFFF) << 16) | ((tag & 0xFF) << 8) | (code & 0xFF)
    return (
        dw0.to_bytes(4, "big")
        + dw1.to_bytes(4, "big")
        + (route_data & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
        + bytes(payload)
    )


def parse_message_tlp(data: bytes) -> MessageTlp:
    """Decode the generic Message fields used by the endpoint scoreboard."""
    if len(data) < 16:
        raise AssertionError("Message TLP is shorter than its four-DWORD header")
    dw0 = int.from_bytes(data[0:4], "big")
    dw1 = int.from_bytes(data[4:8], "big")
    fmt = (dw0 >> 29) & 0x7
    tlp_type = (dw0 >> 24) & 0x1F
    route = tlp_type & 0x7
    if tlp_type < 0x10 or tlp_type > 0x15 or fmt not in (0b001, 0b011):
        raise AssertionError("packet is not a supported Message TLP")
    length_dw = dw0 & 0x3FF
    if fmt == 0b001:
        length_dw = 0
    elif length_dw == 0:
        length_dw = 1024
    payload = bytes(data[16:16 + length_dw * 4])
    if len(payload) != length_dw * 4 or len(data) != 16 + len(payload):
        raise AssertionError("Message TLP length does not match its payload")
    return MessageTlp(
        route=route,
        code=dw1 & 0xFF,
        requester_id=(dw1 >> 16) & 0xFFFF,
        tag=(dw1 >> 8) & 0xFF,
        route_data=int.from_bytes(data[8:16], "big"),
        payload=payload,
    )


def calculate_dllp_crc(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xD008 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def build_fc_dllp(dllp_type: DllpType, hdr_fc=32, data_fc=256) -> bytes:
    packet = Dllp()
    packet.type = dllp_type
    packet.vc = 0
    packet.hdr_scale = FcScale(0)
    packet.hdr_fc = hdr_fc
    packet.data_scale = FcScale(0)
    packet.data_fc = data_fc
    packet.feature_support = 0
    packet.feature_ack = False
    payload = bytes(packet.pack())
    return payload + calculate_dllp_crc(payload).to_bytes(2, "little")


def build_ack_nak(dllp_type: DllpType, sequence: int) -> bytes:
    packet = Dllp()
    packet.type = dllp_type
    packet.seq = sequence & 0xFFF
    payload = bytes(packet.pack())
    return payload + calculate_dllp_crc(payload).to_bytes(2, "little")


def add_sequence_and_lcrc(sequence: int, tlp: bytes) -> bytes:
    body = (sequence & 0xFFF).to_bytes(2, "big") + bytes(tlp)
    return body + (zlib.crc32(body) & 0xFFFFFFFF).to_bytes(4, "little")


def lfsr_step(state: int) -> int:
    q = [(state >> bit) & 1 for bit in range(16)]
    out = [0] * 16
    out[0:3] = q[8:11]
    out[3] = q[8] ^ q[11]
    out[4] = q[8] ^ q[9] ^ q[12]
    out[5] = q[8] ^ q[9] ^ q[10] ^ q[13]
    out[6] = q[9] ^ q[10] ^ q[11] ^ q[14]
    out[7] = q[10] ^ q[11] ^ q[12] ^ q[15]
    out[8] = q[0] ^ q[11] ^ q[12] ^ q[13]
    out[9] = q[1] ^ q[12] ^ q[13] ^ q[14]
    out[10] = q[2] ^ q[13] ^ q[14] ^ q[15]
    out[11] = q[3] ^ q[14] ^ q[15]
    out[12] = q[4] ^ q[15]
    out[13:16] = q[5:8]
    return sum(bit << index for index, bit in enumerate(out))


def reverse16(value: int) -> int:
    return int(f"{value & 0xFFFF:016b}"[::-1], 2)


def scramble_byte(value: int, state: int) -> tuple[int, int]:
    return value ^ (reverse16(state) & 0xFF), lfsr_step(state)


def encode_8b10b(value: int, disparity: int, k: int = 0) -> tuple[int, int]:
    """Independent transcription of the repository's encode_8b10b equations."""
    bits = [(value >> bit) & 1 for bit in range(8)]
    ai, bi, ci, di, ei, fi, gi, hi = bits
    ki = int(bool(k))
    aeqb = (ai and bi) or (not ai and not bi)
    ceqd = (ci and di) or (not ci and not di)
    l22 = (ai and bi and not ci and not di) or (
        ci and di and not ai and not bi
    ) or (not aeqb and not ceqd)
    l40 = ai and bi and ci and di
    l04 = not ai and not bi and not ci and not di
    l13 = (not aeqb and not ci and not di) or (not ceqd and not ai and not bi)
    l31 = (not aeqb and ci and di) or (not ceqd and ai and bi)

    ao = ai
    bo = (bi and not l40) or l04
    co = l04 or ci or (ei and di and not ci and not bi and not ai)
    do = di and not (ai and bi and ci)
    eo = (ei or l13) and not (ei and di and not ci and not bi and not ai)
    io = (l22 and not ei) or (
        ei and not di and not ci and not (ai and bi)
    ) or (ei and l40) or (ki and ei and di and ci and not bi and not ai) or (
        ei and not di and ci and not bi and not ai
    )

    pd1s6 = (ei and di and not ci and not bi and not ai) or (
        not ei and not l22 and not l31
    )
    nd1s6 = ki or (ei and not l22 and not l13) or (
        not ei and not di and ci and bi and ai
    )
    ndos6 = pd1s6
    pdos6 = ki or (ei and not l22 and not l13)
    alt7 = fi and gi and hi and (
        ki or ((not ei and di and l31) if disparity else (ei and not di and l13))
    )
    fo = fi and not alt7
    go = gi or (not fi and not gi and not hi)
    ho = hi
    jo = (not hi and bool(gi ^ fi)) or alt7
    nd1s4 = fi and gi
    pd1s4 = (not fi and not gi) or (ki and ((fi and not gi) or (not fi and gi)))
    ndos4 = not fi and not gi
    pdos4 = fi and gi and hi
    compls6 = (pd1s6 and not disparity) or (nd1s6 and disparity)
    disp6 = disparity ^ int(bool(ndos6 or pdos6))
    compls4 = (pd1s4 and not disp6) or (nd1s4 and disp6)
    dispout = disp6 ^ int(bool(ndos4 or pdos4))

    encoded_bits = [
        ao ^ compls6,
        bo ^ compls6,
        co ^ compls6,
        do ^ compls6,
        eo ^ compls6,
        io ^ compls6,
        fo ^ compls4,
        go ^ compls4,
        ho ^ compls4,
        jo ^ compls4,
    ]
    code = sum(int(bool(bit)) << index for index, bit in enumerate(encoded_bits))
    return code, int(bool(dispout))


_DECODE_TABLE = {
    disparity: {
        encode_8b10b(byte, disparity)[0]: (byte, encode_8b10b(byte, disparity)[1])
        for byte in range(256)
    }
    for disparity in (0, 1)
}


def decode_8b10b(code: int, disparity: int) -> tuple[int, int]:
    try:
        return _DECODE_TABLE[disparity][code & 0x3FF]
    except KeyError as exc:
        raise AssertionError(
            f"illegal 8b/10b data code {code & 0x3ff:#05x} at disparity {disparity}"
        ) from exc


@dataclass(frozen=True)
class SymbolGroup:
    data: int
    keep: int
    sop: bool
    eop: bool


class Gen1Encoder:
    def __init__(self, lane_count: int):
        if lane_count not in (1, 4):
            raise ValueError("Gen1 tests support one or four lanes")
        self.lane_count = lane_count
        self.lfsr = [0xFFFF] * lane_count
        self.disparity = [0] * lane_count

    def reset(self):
        self.lfsr = [0xFFFF] * self.lane_count
        self.disparity = [0] * self.lane_count

    def encode_frame(self, payload: bytes) -> list[SymbolGroup]:
        groups = []
        for offset in range(0, len(payload), self.lane_count):
            chunk = payload[offset:offset + self.lane_count]
            packed = 0
            keep = 0
            for lane, byte in enumerate(chunk):
                scrambled, self.lfsr[lane] = scramble_byte(byte, self.lfsr[lane])
                code, self.disparity[lane] = encode_8b10b(
                    scrambled, self.disparity[lane]
                )
                packed |= code << (10 * lane)
                keep |= 1 << lane
            groups.append(SymbolGroup(
                packed,
                keep,
                offset == 0,
                offset + self.lane_count >= len(payload),
            ))
        return groups


class Gen1Decoder:
    def __init__(self, lane_count: int):
        if lane_count not in (1, 4):
            raise ValueError("Gen1 tests support one or four lanes")
        self.lane_count = lane_count
        self.lfsr = [0xFFFF] * lane_count
        self.disparity = [0] * lane_count

    def reset(self):
        self.lfsr = [0xFFFF] * self.lane_count
        self.disparity = [0] * self.lane_count

    def decode_group(self, data: int, keep: int) -> bytes:
        result = bytearray()
        for lane in range(self.lane_count):
            if keep & (1 << lane):
                code = (data >> (10 * lane)) & 0x3FF
                scrambled, self.disparity[lane] = decode_8b10b(
                    code, self.disparity[lane]
                )
                byte, self.lfsr[lane] = scramble_byte(scrambled, self.lfsr[lane])
                result.append(byte)
        return bytes(result)


def expected_symbol_cycles(byte_count: int, lane_count: int) -> int:
    return (byte_count + lane_count - 1) // lane_count

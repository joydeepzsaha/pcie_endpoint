"""TLP/DLLP codecs, classification, validation, ECRC, and LCRC."""

from dataclasses import dataclass
from typing import List, Optional

from .config import ModelConfig
from .crc import crc32_update, dllp_crc16
from .types import (
    CompletionStatus,
    Dllp,
    DllpType,
    ErrorCode,
    Tlp,
    TlpFmt,
    TlpHeader,
    TlpType,
    TrafficClass,
    decoded_length,
    encoded_length,
    tlp_has_data,
    tlp_is_4dw,
    tlp_is_completion,
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    error: ErrorCode = ErrorCode.NONE


def classify_tlp(header: TlpHeader) -> TrafficClass:
    if tlp_is_completion(header.type):
        return TrafficClass.COMPLETION
    if header.type == TlpType.MESSAGE:
        return TrafficClass.POSTED
    if header.type == TlpType.MEMORY and tlp_has_data(header.fmt):
        return TrafficClass.POSTED
    if header.type in (
        TlpType.MEMORY,
        TlpType.IO,
        TlpType.CONFIG0,
        TlpType.CONFIG1,
        TlpType.MEMORY_LOCKED,
        TlpType.FETCH_ADD,
        TlpType.SWAP,
        TlpType.CAS,
    ):
        return TrafficClass.NON_POSTED
    return TrafficClass.UNSUPPORTED


def enabled_byte_count(byte_enable: int) -> int:
    return (byte_enable & 0xF).bit_count()


def first_enabled_offset(byte_enable: int) -> int:
    for bit in range(4):
        if byte_enable & (1 << bit):
            return bit
    return 0


def request_byte_count(header: TlpHeader) -> int:
    if header.length_dw == 0:
        return 0
    if header.length_dw == 1:
        return enabled_byte_count(header.first_be)
    return (
        enabled_byte_count(header.first_be)
        + enabled_byte_count(header.last_be)
        + (header.length_dw - 2) * 4
    )


def _make_dw0(header: TlpHeader) -> int:
    return (
        (int(header.fmt) << 29)
        | ((int(header.type) & 0x1F) << 24)
        | ((header.traffic_class & 0x7) << 20)
        | ((header.attributes & 0x4) << 16)
        | (int(header.processing_hint) << 16)
        | (int(header.digest_present) << 15)
        | (int(header.poisoned) << 14)
        | ((header.attributes & 0x3) << 12)
        | ((header.address_type & 0x3) << 10)
        | encoded_length(header.length_dw)
    ) & 0xFFFFFFFF


def _parse_dw0(word: int, header: TlpHeader) -> bool:
    try:
        header.fmt = TlpFmt((word >> 29) & 0x7)
        header.type = TlpType((word >> 24) & 0x1F)
    except ValueError:
        return False
    header.traffic_class = (word >> 20) & 0x7
    header.attributes = ((word >> 16) & 0x4) | ((word >> 12) & 0x3)
    header.processing_hint = bool((word >> 16) & 1)
    header.digest_present = bool((word >> 15) & 1)
    header.poisoned = bool((word >> 14) & 1)
    header.address_type = (word >> 10) & 0x3
    header.length_dw = decoded_length(word & 0x3FF)
    return True


def encode_tlp(tlp: Tlp) -> Optional[List[int]]:
    header = tlp.header
    if header.fmt not in (
        TlpFmt.THREE_DW_NO_DATA,
        TlpFmt.FOUR_DW_NO_DATA,
        TlpFmt.THREE_DW_DATA,
        TlpFmt.FOUR_DW_DATA,
    ):
        return None
    words: List[int] = []
    if header.prefix_present:
        words.append(header.prefix & 0xFFFFFFFF)
    words.append(_make_dw0(header))
    if tlp_is_completion(header.type):
        words.append(
            ((header.completer_id & 0xFFFF) << 16)
            | ((int(header.completion_status) & 0x7) << 13)
            | (int(header.byte_count_modified) << 12)
            | (0 if header.byte_count == 4096 else header.byte_count & 0xFFF)
        )
        words.append(
            ((header.requester_id & 0xFFFF) << 16)
            | ((header.tag & 0xFF) << 8)
            | (header.lower_address & 0x7F)
        )
    else:
        words.append(
            ((header.requester_id & 0xFFFF) << 16)
            | ((header.tag & 0xFF) << 8)
            | ((header.last_be & 0xF) << 4)
            | (header.first_be & 0xF)
        )
        if tlp_is_4dw(header.fmt):
            words.append((header.address >> 32) & 0xFFFFFFFF)
            words.append(header.address & 0xFFFFFFFC)
        elif header.type in (TlpType.CONFIG0, TlpType.CONFIG1):
            words.append(
                ((header.destination_id & 0xFFFF) << 16)
                | (header.address & 0xFFC)
            )
        else:
            words.append(header.address & 0xFFFFFFFC)
    if len(tlp.payload) > ModelConfig.MAX_PAYLOAD_DW:
        return None
    words.extend(word & 0xFFFFFFFF for word in tlp.payload)
    if header.digest_present:
        words.append(tlp.ecrc & 0xFFFFFFFF)
    return words


def decode_tlp(words: List[int]) -> Optional[Tlp]:
    if len(words) < 3:
        return None
    tlp = Tlp()
    index = 0
    if ((words[0] >> 29) & 0x7) == int(TlpFmt.PREFIX):
        tlp.header.prefix_present = True
        tlp.header.prefix = words[0] & 0xFFFFFFFF
        index += 1
        if len(words) < 4:
            return None
    dw0 = words[index]
    index += 1
    if not _parse_dw0(dw0, tlp.header):
        return None
    header = tlp.header
    if tlp_is_completion(header.type):
        if len(words) < index + 2:
            return None
        dw1, dw2 = words[index], words[index + 1]
        index += 2
        header.completer_id = (dw1 >> 16) & 0xFFFF
        try:
            header.completion_status = CompletionStatus((dw1 >> 13) & 0x7)
        except ValueError:
            return None
        header.byte_count_modified = bool((dw1 >> 12) & 1)
        header.byte_count = dw1 & 0xFFF
        if header.byte_count == 0:
            header.byte_count = 4096
        header.requester_id = (dw2 >> 16) & 0xFFFF
        header.tag = (dw2 >> 8) & 0xFF
        header.lower_address = dw2 & 0x7F
        if not tlp_has_data(header.fmt) and (dw0 & 0x3FF) == 0:
            header.length_dw = 0
    else:
        if len(words) < index + 2:
            return None
        dw1 = words[index]
        index += 1
        header.requester_id = (dw1 >> 16) & 0xFFFF
        header.tag = (dw1 >> 8) & 0xFF
        header.last_be = (dw1 >> 4) & 0xF
        header.first_be = dw1 & 0xF
        if tlp_is_4dw(header.fmt):
            if len(words) < index + 2:
                return None
            header.address = (words[index] & 0xFFFFFFFF) << 32
            header.address |= words[index + 1] & 0xFFFFFFFC
            index += 2
        elif header.type in (TlpType.CONFIG0, TlpType.CONFIG1):
            destination = words[index]
            index += 1
            header.destination_id = (destination >> 16) & 0xFFFF
            header.address = destination & 0xFFC
        else:
            header.address = words[index] & 0xFFFFFFFC
            index += 1
    digest_words = 1 if header.digest_present else 0
    if len(words) < index + digest_words:
        return None
    available = len(words) - index - digest_words
    if tlp_has_data(header.fmt):
        if available != header.length_dw or available > ModelConfig.MAX_PAYLOAD_DW:
            return None
        tlp.payload = [word & 0xFFFFFFFF for word in words[index:index + available]]
        index += available
    elif available:
        return None
    if header.digest_present:
        tlp.ecrc = words[index] & 0xFFFFFFFF
    return tlp


def _crc_words(words: List[int], first: int = 0) -> int:
    crc = 0xFFFFFFFF
    for word in words[first:]:
        for shift in (24, 16, 8, 0):
            crc = crc32_update(crc, (word >> shift) & 0xFF)
    return crc ^ 0xFFFFFFFF


def tlp_ecrc(tlp: Tlp) -> int:
    words = encode_tlp(tlp)
    if words is None:
        return 0
    if tlp.header.digest_present:
        words = words[:-1]
    return _crc_words(words, 1 if tlp.header.prefix_present else 0)


def tlp_lcrc(sequence: int, tlp: Tlp) -> int:
    words = encode_tlp(tlp)
    if words is None:
        return 0
    crc = 0xFFFFFFFF
    crc = crc32_update(crc, (sequence >> 8) & 0xF)
    crc = crc32_update(crc, sequence & 0xFF)
    for word in words:
        for shift in (24, 16, 8, 0):
            crc = crc32_update(crc, (word >> shift) & 0xFF)
    return crc ^ 0xFFFFFFFF


def validate_tlp(tlp: Tlp, config: ModelConfig) -> ValidationResult:
    header = tlp.header
    completion = tlp_is_completion(header.type)
    config_or_io = header.type in (TlpType.CONFIG0, TlpType.CONFIG1, TlpType.IO)
    has_data = tlp_has_data(header.fmt)
    if header.fmt not in (
        TlpFmt.THREE_DW_NO_DATA,
        TlpFmt.FOUR_DW_NO_DATA,
        TlpFmt.THREE_DW_DATA,
        TlpFmt.FOUR_DW_DATA,
    ) or header.type not in (
        TlpType.MEMORY,
        TlpType.IO,
        TlpType.CONFIG0,
        TlpType.CONFIG1,
        TlpType.COMPLETION,
        TlpType.COMPLETION_LOCKED,
    ):
        return ValidationResult(False, ErrorCode.BAD_FMT_TYPE)
    if (config_or_io or completion) and tlp_is_4dw(header.fmt):
        return ValidationResult(False, ErrorCode.BAD_FMT_TYPE)
    if header.type == TlpType.MEMORY:
        if not tlp_is_4dw(header.fmt) and header.address >> 32:
            return ValidationResult(False, ErrorCode.BAD_ADDRESS_FORMAT)
        if tlp_is_4dw(header.fmt) and not header.address >> 32:
            return ValidationResult(False, ErrorCode.BAD_ADDRESS_FORMAT)
    if header.type in (TlpType.MEMORY, TlpType.IO) and header.address & 3:
        return ValidationResult(False, ErrorCode.BAD_ADDRESS_FORMAT)
    if header.type in (TlpType.CONFIG0, TlpType.CONFIG1) and header.address & ~0xFFC:
        return ValidationResult(False, ErrorCode.BAD_ADDRESS_FORMAT)
    if header.length_dw > ModelConfig.MAX_PAYLOAD_DW:
        return ValidationResult(False, ErrorCode.BAD_LENGTH)
    if (
        (config_or_io and header.length_dw != 1)
        or (not completion and header.length_dw == 0)
        or (completion and not has_data and header.length_dw != 0)
        or (has_data and header.length_dw == 0)
    ):
        return ValidationResult(False, ErrorCode.BAD_LENGTH)
    if has_data != bool(tlp.payload) or (has_data and len(tlp.payload) != header.length_dw):
        return ValidationResult(False, ErrorCode.BAD_LENGTH)
    if not completion and header.length_dw == 1 and header.last_be:
        return ValidationResult(False, ErrorCode.BAD_BYTE_ENABLE)
    if (
        not completion
        and header.length_dw > 1
        and (not header.first_be or not header.last_be)
    ):
        return ValidationResult(False, ErrorCode.BAD_BYTE_ENABLE)
    byte_count = request_byte_count(header)
    if not completion and header.type == TlpType.MEMORY and byte_count:
        first = header.address + first_enabled_offset(header.first_be)
        if first & ~0xFFF != (first + byte_count - 1) & ~0xFFF:
            return ValidationResult(False, ErrorCode.FOUR_KB_CROSSING)
    if has_data and header.length_dw * 4 > config.max_payload_bytes:
        return ValidationResult(False, ErrorCode.MPS_EXCEEDED)
    if (
        header.type == TlpType.MEMORY
        and not has_data
        and header.length_dw * 4 > config.max_read_request_bytes
    ):
        return ValidationResult(False, ErrorCode.MRRS_EXCEEDED)
    if header.digest_present and tlp.ecrc != tlp_ecrc(tlp):
        return ValidationResult(False, ErrorCode.ECRC)
    return ValidationResult(True)


def encode_dllp(dllp: Dllp) -> Optional[bytes]:
    data = bytearray(6)
    data[0] = int(dllp.type)
    if dllp.type in (DllpType.ACK, DllpType.NAK):
        data[2] = (dllp.sequence >> 8) & 0xF
        data[3] = dllp.sequence & 0xFF
    else:
        if dllp.header_credits > 0xFF or dllp.data_credits > 0xFFF:
            return None
        data[1] = (dllp.header_credits >> 2) & 0x3F
        data[2] = ((dllp.header_credits & 3) << 6) | ((dllp.data_credits >> 8) & 0xF)
        data[3] = dllp.data_credits & 0xFF
    crc = dllp_crc16(bytes(data[:4]))
    data[4], data[5] = crc & 0xFF, crc >> 8
    return bytes(data)


def decode_dllp(data: bytes) -> Optional[Dllp]:
    if len(data) != 6:
        return None
    received = data[4] | (data[5] << 8)
    if received != dllp_crc16(data[:4]):
        return None
    try:
        dllp = Dllp(type=DllpType(data[0]), crc=received)
    except ValueError:
        return None
    if dllp.type in (DllpType.ACK, DllpType.NAK):
        dllp.sequence = ((data[2] & 0xF) << 8) | data[3]
    else:
        dllp.header_credits = ((data[1] & 0x3F) << 2) | ((data[2] >> 6) & 3)
        dllp.data_credits = ((data[2] & 0xF) << 8) | data[3]
    return dllp

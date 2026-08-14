"""Shared protocol objects used by the PCIe Endpoint BFM."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Deque, Generic, List, Optional, TypeVar

from .config import ModelConfig


T = TypeVar("T")


class BoundedQueue(Generic[T]):
    """A value-semantics FIFO whose full condition models ready/valid."""

    def __init__(self, depth: int):
        if depth <= 0:
            raise ValueError("queue depth must be positive")
        self.depth = depth
        self._items: Deque[T] = deque()

    def push(self, value: T) -> bool:
        if self.full:
            return False
        self._items.append(deepcopy(value))
        return True

    def pop(self) -> Optional[T]:
        return self._items.popleft() if self._items else None

    @property
    def front(self) -> Optional[T]:
        return self._items[0] if self._items else None

    @property
    def empty(self) -> bool:
        return not self._items

    @property
    def full(self) -> bool:
        return len(self._items) >= self.depth

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


class LinkState(IntEnum):
    INACTIVE = 0
    FC_INIT1 = 1
    FC_INIT2 = 2
    DL_ACTIVE = 3


class TrafficClass(IntEnum):
    POSTED = 0
    NON_POSTED = 1
    COMPLETION = 2
    UNSUPPORTED = 3


class TlpFmt(IntEnum):
    THREE_DW_NO_DATA = 0
    FOUR_DW_NO_DATA = 1
    THREE_DW_DATA = 2
    FOUR_DW_DATA = 3
    PREFIX = 4


class TlpType(IntEnum):
    MEMORY = 0x00
    MEMORY_LOCKED = 0x01
    IO = 0x02
    CONFIG0 = 0x04
    CONFIG1 = 0x05
    COMPLETION = 0x0A
    COMPLETION_LOCKED = 0x0B
    FETCH_ADD = 0x0C
    SWAP = 0x0D
    CAS = 0x0E
    MESSAGE = 0x10


class CompletionStatus(IntEnum):
    SUCCESS = 0
    UNSUPPORTED_REQUEST = 1
    CONFIG_RETRY = 2
    COMPLETER_ABORT = 4


class ErrorCode(IntEnum):
    NONE = 0
    TRUNCATED_HEADER = auto()
    EARLY_EOP = auto()
    LATE_EOP = auto()
    BAD_KEEP = auto()
    BAD_FMT_TYPE = auto()
    BAD_LENGTH = auto()
    BAD_BYTE_ENABLE = auto()
    BAD_ADDRESS_FORMAT = auto()
    FOUR_KB_CROSSING = auto()
    MPS_EXCEEDED = auto()
    MRRS_EXCEEDED = auto()
    ECRC = auto()
    LCRC = auto()
    BAD_SEQUENCE = auto()
    UNEXPECTED_COMPLETION = auto()
    COMPLETION_OVERFLOW = auto()
    CREDIT_UNDERFLOW = auto()
    FLOW_CONTROL_OVERFLOW = auto()
    RECEIVE_OVERFLOW = auto()
    LOCAL_PAYLOAD = auto()
    VC_OVERFLOW = auto()
    REPLAY_EXHAUSTED = auto()
    UNSUPPORTED_REQUEST = auto()
    BAR_MISS = auto()


@dataclass
class TlpHeader:
    fmt: TlpFmt = TlpFmt.THREE_DW_NO_DATA
    type: TlpType = TlpType.MEMORY
    traffic_class: int = 0
    attributes: int = 0
    digest_present: bool = False
    poisoned: bool = False
    processing_hint: bool = False
    address_type: int = 0
    length_dw: int = 0
    requester_id: int = 0
    completer_id: int = 0
    destination_id: int = 0
    tag: int = 0
    first_be: int = 0
    last_be: int = 0
    address: int = 0
    completion_status: CompletionStatus = CompletionStatus.SUCCESS
    byte_count_modified: bool = False
    byte_count: int = 0
    lower_address: int = 0
    prefix_present: bool = False
    prefix: int = 0


@dataclass
class Tlp:
    header: TlpHeader = field(default_factory=TlpHeader)
    payload: List[int] = field(default_factory=list)
    ecrc: int = 0

    @property
    def payload_dw(self) -> int:
        return len(self.payload)


class DllpType(IntEnum):
    ACK = 0x00
    NAK = 0x10
    INIT_FC1_P = 0x40
    INIT_FC1_NP = 0x50
    INIT_FC1_CPL = 0x60
    UPDATE_FC_P = 0x80
    UPDATE_FC_NP = 0x90
    UPDATE_FC_CPL = 0xA0
    INIT_FC2_P = 0xC0
    INIT_FC2_NP = 0xD0
    INIT_FC2_CPL = 0xE0


@dataclass
class Dllp:
    type: DllpType = DllpType.ACK
    vc: int = 0
    header_credits: int = 0
    data_credits: int = 0
    sequence: int = 0
    crc: int = 0


class LinkEventKind(IntEnum):
    TLP = 0
    DLLP = 1


@dataclass
class LinkEvent:
    kind: LinkEventKind = LinkEventKind.DLLP
    tlp: Tlp = field(default_factory=Tlp)
    dllp: Dllp = field(default_factory=Dllp)
    sequence: int = 0
    lcrc: int = 0


@dataclass
class CreditPair:
    header: int = 0
    data: int = 0
    header_infinite: bool = False
    data_infinite: bool = False


@dataclass
class CreditSet:
    posted: CreditPair = field(default_factory=CreditPair)
    nonposted: CreditPair = field(default_factory=CreditPair)
    completion: CreditPair = field(default_factory=CreditPair)


@dataclass
class FlowControlCounterPair:
    credit_limit: int = 0
    credits_consumed: int = 0
    credit_allocated: int = 0
    credits_received: int = 0
    infinite: bool = False


@dataclass
class FlowControlCounterSet:
    posted_header: FlowControlCounterPair = field(
        default_factory=FlowControlCounterPair
    )
    posted_data: FlowControlCounterPair = field(
        default_factory=FlowControlCounterPair
    )
    nonposted_header: FlowControlCounterPair = field(
        default_factory=FlowControlCounterPair
    )
    nonposted_data: FlowControlCounterPair = field(
        default_factory=FlowControlCounterPair
    )
    completion_header: FlowControlCounterPair = field(
        default_factory=FlowControlCounterPair
    )
    completion_data: FlowControlCounterPair = field(
        default_factory=FlowControlCounterPair
    )


@dataclass
class LinkStatus:
    state: LinkState = LinkState.INACTIVE
    entered_inactive: bool = False
    entered_fc_init1: bool = False
    entered_fc_init2: bool = False
    entered_dl_active: bool = False
    flow_control_initialized: bool = False
    replay_active: bool = False
    protocol_error: bool = False
    fatal_error: bool = False
    last_error: ErrorCode = ErrorCode.NONE
    next_tx_sequence: int = 0
    expected_rx_sequence: int = 0


def tlp_has_data(fmt: TlpFmt) -> bool:
    return fmt in (TlpFmt.THREE_DW_DATA, TlpFmt.FOUR_DW_DATA)


def tlp_is_4dw(fmt: TlpFmt) -> bool:
    return fmt in (TlpFmt.FOUR_DW_NO_DATA, TlpFmt.FOUR_DW_DATA)


def tlp_is_completion(tlp_type: TlpType) -> bool:
    return tlp_type in (TlpType.COMPLETION, TlpType.COMPLETION_LOCKED)


def encoded_length(length_dw: int) -> int:
    return 0 if length_dw == 1024 else length_dw & 0x3FF


def decoded_length(encoded: int) -> int:
    return 1024 if encoded == 0 else encoded & 0x3FF


def data_credit_count(payload_dw: int) -> int:
    return (payload_dw + 3) // 4

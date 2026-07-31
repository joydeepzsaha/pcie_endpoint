"""Bus functional model of src/pcie_endpoint/pcie_endpoint_top.sv."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional

from .config import ModelConfig
from .data_link import DataLinkLayer
from .gen1_phy import DecodedSymbol, EncodedSymbol, Gen1PhyCodec
from .tlp import classify_tlp, enabled_byte_count, tlp_ecrc
from .types import (
    BoundedQueue,
    CompletionStatus,
    CreditSet,
    ErrorCode,
    FlowControlCounterSet,
    LinkEvent,
    LinkState,
    LinkStatus,
    Tlp,
    TlpFmt,
    TlpHeader,
    TlpType,
    TrafficClass,
    tlp_has_data,
    tlp_is_4dw,
    tlp_is_completion,
)


@dataclass
class BfmPayload:
    """Transaction-level form of the endpoint's 32-bit payload stream."""

    words: List[int] = field(default_factory=list)
    keep: List[int] = field(default_factory=list)
    beat_count: int = 0
    last: bool = True


class EndpointCommandCode(IntEnum):
    MEMORY_READ = 0
    MEMORY_WRITE = 1
    CONFIG_READ0 = 2
    CONFIG_WRITE0 = 3
    IO_READ = 4
    IO_WRITE = 5


@dataclass
class EndpointCommand:
    code: EndpointCommandCode = EndpointCommandCode.MEMORY_READ
    address: int = 0
    byte_count: int = 0
    traffic_class: int = 0
    attributes: int = 0
    context: int = 0
    prefix_valid: bool = False
    prefix: int = 0
    ecrc_enable: bool = False
    payload: BfmPayload = field(default_factory=BfmPayload)


@dataclass
class TargetRequest:
    packet: Tlp = field(default_factory=Tlp)
    traffic_class: TrafficClass = TrafficClass.UNSUPPORTED
    memory: bool = False
    config: bool = False
    config_hit: bool = False
    config_type_one: bool = False
    config_offset: int = 0
    read: bool = False
    write: bool = False
    unsupported: bool = False
    bar_hit: bool = False
    bar_overlap: bool = False
    bar: int = 0
    offset: int = 0


@dataclass
class CompletionRequest:
    request_header: TlpHeader = field(default_factory=TlpHeader)
    status: CompletionStatus = CompletionStatus.SUCCESS
    byte_count: int = 0
    lower_address: int = 0
    ecrc_enable: bool = False
    payload: BfmPayload = field(default_factory=BfmPayload)


@dataclass
class ReceivedCompletion:
    packet: Tlp = field(default_factory=Tlp)


@dataclass
class CompletionResult:
    context: int = 0
    status: CompletionStatus = CompletionStatus.SUCCESS
    last: bool = False


@dataclass
class EndpointBfmStatus:
    command_error_valid: bool = False
    command_error: ErrorCode = ErrorCode.NONE
    malformed: bool = False
    rx_error_valid: bool = False
    rx_error: ErrorCode = ErrorCode.NONE
    rx_ecrc_error: bool = False
    tx_error_valid: bool = False
    tx_error: ErrorCode = ErrorCode.NONE
    tx_fc_blocked: bool = False
    credit_error: bool = False
    vc_overflow: bool = False
    unexpected_completion: bool = False
    completion_error: ErrorCode = ErrorCode.NONE
    phy_rx_code_error: bool = False
    phy_rx_disparity_error: bool = False
    outstanding: int = 0


@dataclass
class _CommandState:
    command: EndpointCommand
    address: int
    remaining: int
    payload_offset: int = 0


@dataclass
class _CompletionState:
    request: CompletionRequest
    remaining: int
    lower_address: int
    payload_offset: int = 0


@dataclass
class _TagState:
    active: bool = False
    requester_id: int = 0
    remaining: int = 0
    context: int = 0
    expects_data: bool = False
    next_lower_address: int = 0


class PcieEndpointBfm:
    """Packet-level complete Endpoint BFM with bounded ready/valid queues."""

    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.data_link = DataLinkLayer(self.config)
        self.phy_codec = Gen1PhyCodec()
        self.status = EndpointBfmStatus()
        self.phy_link_up = False
        self.idle_valid = True
        self.transmit_enable = True
        self.memory_enable = False
        self.extended_tag_enable = False
        self.rcb_128b = True
        self.max_payload_bytes = 128
        self.max_read_bytes = 128
        self.function_id = 0
        self.prefer_completion = True
        self.bar_base: List[int] = []
        self.bar_mask: List[int] = []
        self.bar_enable: List[bool] = []
        self.tags: List[_TagState] = []
        self.commands = BoundedQueue[EndpointCommand](
            ModelConfig.TRANSACTION_QUEUE_DEPTH
        )
        self.completion_requests = BoundedQueue[CompletionRequest](
            ModelConfig.TRANSACTION_QUEUE_DEPTH
        )
        self.target_requests = BoundedQueue[TargetRequest](
            ModelConfig.TRANSACTION_QUEUE_DEPTH
        )
        self.received_completions = BoundedQueue[ReceivedCompletion](
            ModelConfig.TRANSACTION_QUEUE_DEPTH
        )
        self.results = BoundedQueue[CompletionResult](
            ModelConfig.TRANSACTION_QUEUE_DEPTH
        )
        self.requester_packets = BoundedQueue[Tlp](
            ModelConfig.VIRTUAL_CHANNEL_DEPTH
        )
        self.completion_packets = BoundedQueue[Tlp](
            ModelConfig.VIRTUAL_CHANNEL_DEPTH
        )
        self.active_command: Optional[_CommandState] = None
        self.active_completion: Optional[_CompletionState] = None
        self.pending_rx: Optional[Tlp] = None
        self.reset()

    def reset(self) -> None:
        self.data_link.reset()
        self.phy_codec.reset()
        self.status = EndpointBfmStatus()
        self.phy_link_up = False
        self.idle_valid = True
        self.transmit_enable = True
        self.memory_enable = False
        self.extended_tag_enable = False
        self.rcb_128b = self.config.read_completion_boundary_bytes != 64
        self.max_payload_bytes = self.config.max_payload_bytes
        self.max_read_bytes = self.config.max_read_request_bytes
        self.function_id = self.config.completer_id & 0xFFFF
        self.prefer_completion = True
        self.bar_base = (list(self.config.bar_base) + [0] * 6)[:6]
        self.bar_mask = (list(self.config.bar_mask) + [0] * 6)[:6]
        self.bar_enable = (list(self.config.bar_enable) + [False] * 6)[:6]
        self._clear_transaction_state()

    def _clear_transaction_state(self) -> None:
        self.clear_status_events()
        self.status.tx_fc_blocked = False
        self.commands.clear()
        self.completion_requests.clear()
        self.target_requests.clear()
        self.received_completions.clear()
        self.results.clear()
        self.requester_packets.clear()
        self.completion_packets.clear()
        self.active_command = None
        self.active_completion = None
        self.pending_rx = None
        self.tags = [_TagState() for _ in range(ModelConfig.MAX_TAGS)]
        self._refresh_outstanding()

    def set_phy_link_up(self, link_up: bool) -> None:
        self.phy_link_up = bool(link_up)
        self.data_link.set_phy_link_up(link_up)

    def set_idle_valid(self, idle_valid: bool) -> None:
        self.idle_valid = bool(idle_valid)

    def set_transmit_enable(self, enable: bool) -> None:
        self.transmit_enable = bool(enable)

    def set_memory_enable(self, enable: bool) -> None:
        self.memory_enable = bool(enable)

    def set_extended_tag_enable(self, enable: bool) -> None:
        self.extended_tag_enable = bool(enable)

    def set_max_payload_bytes(self, byte_count: int) -> None:
        self.max_payload_bytes = min(max(byte_count, 0), 4096)

    def set_max_read_bytes(self, byte_count: int) -> None:
        self.max_read_bytes = min(max(byte_count, 0), 4096)

    def set_rcb_128b(self, enable: bool) -> None:
        self.rcb_128b = bool(enable)

    def set_function_id(self, bus: int, device: int, function: int) -> None:
        self.function_id = (
            ((bus & 0xFF) << 8) | ((device & 0x1F) << 3) | (function & 0x7)
        )

    @property
    def bus_number(self) -> int:
        return self.function_id >> 8

    @property
    def device_number(self) -> int:
        return (self.function_id >> 3) & 0x1F

    @property
    def function_number(self) -> int:
        return self.function_id & 0x7

    def configure_bar(self, bar: int, base: int, mask: int, enable: bool) -> bool:
        if not 0 <= bar < ModelConfig.BAR_COUNT:
            return False
        self.bar_base[bar] = base & 0xFFFFFFFFFFFFFFFF
        self.bar_mask[bar] = mask & 0xFFFFFFFFFFFFFFFF
        self.bar_enable[bar] = bool(enable)
        return True

    def push_link_rx(self, event: LinkEvent) -> bool:
        return self.data_link.push_link_rx(event)

    def pop_link_tx(self) -> Optional[LinkEvent]:
        return self.data_link.pop_link_tx()

    def encode_phy_tx_symbol(
        self,
        byte: int,
        *,
        is_control: bool = False,
        scramble: bool = True,
        advance_lfsr: bool = True,
        reset_lfsr_after: bool = False,
    ) -> EncodedSymbol:
        """Run one byte through the Endpoint's persistent Gen1 TX path."""
        return self.phy_codec.tx.encode(
            byte,
            is_control=is_control,
            scramble=scramble,
            advance_lfsr=advance_lfsr,
            reset_lfsr_after=reset_lfsr_after,
        )

    def decode_phy_rx_symbol(
        self,
        code: int,
        *,
        scramble: bool = True,
        advance_lfsr: bool = True,
        reset_lfsr_after: bool = False,
    ) -> DecodedSymbol:
        """Run one 10-bit symbol through the Endpoint's persistent RX path."""
        decoded = self.phy_codec.rx.decode(
            code,
            scramble=scramble,
            advance_lfsr=advance_lfsr,
            reset_lfsr_after=reset_lfsr_after,
        )
        self.status.phy_rx_code_error |= decoded.code_error
        self.status.phy_rx_disparity_error |= decoded.disparity_error
        return decoded

    @property
    def command_ready(self) -> bool:
        return not self.commands.full

    @property
    def completion_request_ready(self) -> bool:
        return not self.completion_requests.full

    @property
    def link_status(self) -> LinkStatus:
        return self.data_link.status

    def transmit_credits(self) -> CreditSet:
        return self.data_link.transmit_credits()

    def receive_credits(self) -> CreditSet:
        return self.data_link.receive_credits()

    def flow_control_counters(self) -> FlowControlCounterSet:
        return self.data_link.flow_control_counters()

    def clear_status_events(self) -> None:
        self.status.command_error_valid = False
        self.status.command_error = ErrorCode.NONE
        self.status.malformed = False
        self.status.rx_error_valid = False
        self.status.rx_error = ErrorCode.NONE
        self.status.rx_ecrc_error = False
        self.status.tx_error_valid = False
        self.status.tx_error = ErrorCode.NONE
        self.status.credit_error = False
        self.status.vc_overflow = False
        self.status.unexpected_completion = False
        self.status.completion_error = ErrorCode.NONE
        self.status.phy_rx_code_error = False
        self.status.phy_rx_disparity_error = False

    def _command_error(self, error: ErrorCode) -> None:
        self.status.command_error_valid = True
        self.status.command_error = error
        self._tx_error(error)

    def _tx_error(self, error: ErrorCode) -> None:
        self.status.tx_error_valid = True
        self.status.tx_error = error

    def _rx_error(self, error: ErrorCode) -> None:
        self.status.malformed = True
        self.status.rx_error_valid = True
        self.status.rx_error = error
        self.status.rx_ecrc_error = error == ErrorCode.ECRC

    @staticmethod
    def _has_data(code: EndpointCommandCode) -> bool:
        return code in (
            EndpointCommandCode.MEMORY_WRITE,
            EndpointCommandCode.CONFIG_WRITE0,
            EndpointCommandCode.IO_WRITE,
        )

    @staticmethod
    def _nonposted(code: EndpointCommandCode) -> bool:
        return code != EndpointCommandCode.MEMORY_WRITE

    @staticmethod
    def _payload_bytes(payload: BfmPayload) -> int:
        if (
            payload.beat_count < 0
            or payload.beat_count > ModelConfig.MAX_COMMAND_DW
            or payload.beat_count > len(payload.words)
            or payload.beat_count > len(payload.keep)
        ):
            return -1
        return sum(
            enabled_byte_count(payload.keep[index])
            for index in range(payload.beat_count)
        )

    @staticmethod
    def _payload_byte(payload: BfmPayload, byte_index: int) -> Optional[int]:
        visited = 0
        for beat in range(payload.beat_count):
            keep = payload.keep[beat] & 0xF
            for lane in range(4):
                if not keep & (1 << lane):
                    continue
                if visited == byte_index:
                    return (payload.words[beat] >> (lane * 8)) & 0xFF
                visited += 1
        return None

    @classmethod
    def _pack_payload(
        cls,
        payload: BfmPayload,
        source_offset: int,
        byte_count: int,
        destination_offset: int,
    ) -> Optional[List[int]]:
        word_count = (destination_offset + byte_count + 3) // 4
        if word_count > ModelConfig.MAX_PAYLOAD_DW:
            return None
        words = [0] * word_count
        for index in range(byte_count):
            value = cls._payload_byte(payload, source_offset + index)
            if value is None:
                return None
            position = destination_offset + index
            words[position // 4] |= value << ((position & 3) * 8)
        return words

    @staticmethod
    def _first_be(address_low: int, byte_count: int) -> int:
        end = address_low + byte_count
        return sum(
            1 << lane
            for lane in range(4)
            if address_low <= lane < end
        )

    @staticmethod
    def _last_be(address_low: int, byte_count: int) -> int:
        end = address_low + byte_count
        if end <= 4:
            return 0
        offset = end & 3
        return 0xF if offset == 0 else (1 << offset) - 1

    def submit_command(self, command: EndpointCommand) -> bool:
        if self.commands.full:
            return False
        config_or_io = command.code in (
            EndpointCommandCode.CONFIG_READ0,
            EndpointCommandCode.CONFIG_WRITE0,
            EndpointCommandCode.IO_READ,
            EndpointCommandCode.IO_WRITE,
        )
        if (
            command.byte_count < 0
            or command.byte_count > 0x1FFF
            or (command.byte_count == 0 and command.code != EndpointCommandCode.MEMORY_READ)
            or (config_or_io and command.byte_count != 4)
        ):
            self._command_error(ErrorCode.BAD_LENGTH)
            return False
        supplied = self._payload_bytes(command.payload)
        if self._has_data(command.code):
            if not command.payload.last or supplied != command.byte_count:
                self._command_error(ErrorCode.LOCAL_PAYLOAD)
                return False
        elif supplied != 0:
            self._command_error(ErrorCode.LOCAL_PAYLOAD)
            return False
        return self.commands.push(command)

    def submit_completion(self, request: CompletionRequest) -> bool:
        if self.completion_requests.full:
            return False
        if request.byte_count < 0 or request.byte_count > 0x1FFF:
            self._tx_error(ErrorCode.BAD_LENGTH)
            return False
        supplied = self._payload_bytes(request.payload)
        needs_data = (
            request.status == CompletionStatus.SUCCESS and request.byte_count != 0
        )
        if (
            needs_data
            and (not request.payload.last or supplied != request.byte_count)
        ) or (not needs_data and supplied != 0):
            self._tx_error(ErrorCode.LOCAL_PAYLOAD)
            return False
        return self.completion_requests.push(request)

    def pop_target_request(self) -> Optional[TargetRequest]:
        return self.target_requests.pop()

    def pop_received_completion(self) -> Optional[ReceivedCompletion]:
        return self.received_completions.pop()

    def pop_result(self) -> Optional[CompletionResult]:
        return self.results.pop()

    @staticmethod
    def _bounded_limit(value: int) -> int:
        return 128 if value == 0 else min(value, 4096)

    def _command_limit(self, code: EndpointCommandCode) -> int:
        if code in (
            EndpointCommandCode.CONFIG_READ0,
            EndpointCommandCode.CONFIG_WRITE0,
            EndpointCommandCode.IO_READ,
            EndpointCommandCode.IO_WRITE,
        ):
            return 4
        if code == EndpointCommandCode.MEMORY_READ:
            return self._bounded_limit(self.max_read_bytes)
        return self._bounded_limit(self.max_payload_bytes)

    def _command_segment(
        self, address: int, remaining: int, code: EndpointCommandCode
    ) -> int:
        boundary = 4096 - (address & 0xFFF)
        limit = self._command_limit(code)
        low = address & 3
        aligned_limit = limit - low if limit > low else 1
        return min(remaining, aligned_limit, boundary)

    def _allocate_tag(
        self,
        requester_id: int,
        byte_count: int,
        address: int,
        context: int,
        expects_data: bool,
    ) -> Optional[int]:
        limit = min(max(self.config.tag_count, 0), ModelConfig.MAX_TAGS)
        if not self.extended_tag_enable:
            limit = min(limit, 32)
        for index in range(limit):
            if not self.tags[index].active:
                self.tags[index] = _TagState(
                    active=True,
                    requester_id=requester_id,
                    remaining=byte_count,
                    context=context,
                    expects_data=expects_data,
                    next_lower_address=address & 0x7F,
                )
                self._refresh_outstanding()
                return index
        return None

    def _find_tag(self, header: TlpHeader) -> Optional[int]:
        limit = min(max(self.config.tag_count, 0), ModelConfig.MAX_TAGS)
        for index in range(limit):
            tag = self.tags[index]
            if (
                tag.active
                and header.tag == index
                and header.requester_id == tag.requester_id
            ):
                return index
        return None

    def _retire_tag(self, index: int) -> None:
        self.tags[index] = _TagState()
        self._refresh_outstanding()

    def _refresh_outstanding(self) -> None:
        self.status.outstanding = sum(tag.active for tag in self.tags)

    def _service_command(self) -> None:
        if self.active_command is None:
            command = self.commands.pop()
            if command is None:
                return
            self.active_command = _CommandState(
                command=command,
                address=command.address,
                remaining=command.byte_count,
            )
        if self.requester_packets.full or not self.phy_link_up:
            return
        active = self.active_command
        command = active.command
        segment = self._command_segment(active.address, active.remaining, command.code)
        address_low = active.address & 3
        length_dw = 1 if segment == 0 else (segment + address_low + 3) // 4
        tag: Optional[int] = None
        if self._nonposted(command.code):
            expects_data = command.code in (
                EndpointCommandCode.MEMORY_READ,
                EndpointCommandCode.CONFIG_READ0,
                EndpointCommandCode.IO_READ,
            )
            tag = self._allocate_tag(
                self.function_id,
                4 if segment == 0 else segment,
                active.address,
                command.context,
                expects_data,
            )
            if tag is None:
                return
        has_data = self._has_data(command.code)
        memory = command.code in (
            EndpointCommandCode.MEMORY_READ,
            EndpointCommandCode.MEMORY_WRITE,
        )
        packet = Tlp()
        packet.header.type = (
            TlpType.MEMORY
            if memory
            else TlpType.CONFIG0
            if command.code
            in (
                EndpointCommandCode.CONFIG_READ0,
                EndpointCommandCode.CONFIG_WRITE0,
            )
            else TlpType.IO
        )
        if memory:
            four_dw = bool(active.address >> 32)
            packet.header.fmt = (
                TlpFmt.FOUR_DW_DATA
                if has_data and four_dw
                else TlpFmt.THREE_DW_DATA
                if has_data
                else TlpFmt.FOUR_DW_NO_DATA
                if four_dw
                else TlpFmt.THREE_DW_NO_DATA
            )
            packet.header.address = active.address & ~3
        else:
            packet.header.fmt = (
                TlpFmt.THREE_DW_DATA if has_data else TlpFmt.THREE_DW_NO_DATA
            )
            packet.header.address = active.address & 0xFFC
            if packet.header.type == TlpType.CONFIG0:
                packet.header.destination_id = (active.address >> 16) & 0xFFFF
        packet.header.traffic_class = command.traffic_class & 7
        packet.header.attributes = command.attributes & 7
        packet.header.length_dw = length_dw
        packet.header.requester_id = self.function_id
        packet.header.tag = tag or 0
        packet.header.first_be = self._first_be(address_low, segment)
        packet.header.last_be = self._last_be(address_low, segment)
        packet.header.prefix_present = command.prefix_valid
        packet.header.prefix = command.prefix & 0xFFFFFFFF
        packet.header.digest_present = command.ecrc_enable
        if has_data:
            payload = self._pack_payload(
                command.payload, active.payload_offset, segment, address_low
            )
            if payload is None or len(payload) != length_dw:
                if tag is not None:
                    self._retire_tag(tag)
                self._command_error(ErrorCode.LOCAL_PAYLOAD)
                self.active_command = None
                return
            packet.payload = payload
        if packet.header.digest_present:
            packet.ecrc = tlp_ecrc(packet)
        if not self.requester_packets.push(packet):
            if tag is not None:
                self._retire_tag(tag)
            self.status.vc_overflow = True
            self._tx_error(ErrorCode.VC_OVERFLOW)
            return
        if active.remaining > segment:
            active.address += segment
            active.remaining -= segment
            if has_data:
                active.payload_offset += segment
        else:
            self.active_command = None

    def _completion_segment(self, remaining: int, lower_address: int) -> int:
        limit = self._bounded_limit(self.max_payload_bytes)
        rcb = 128 if self.rcb_128b else 64
        boundary = rcb - (lower_address & (rcb - 1))
        return min(remaining, limit, boundary)

    def _service_completion_request(self) -> None:
        if self.active_completion is None:
            request = self.completion_requests.pop()
            if request is None:
                return
            self.active_completion = _CompletionState(
                request=request,
                remaining=request.byte_count,
                lower_address=request.lower_address & 0x7F,
            )
        if self.completion_packets.full or not self.phy_link_up:
            return
        active = self.active_completion
        request = active.request
        with_data = (
            request.status == CompletionStatus.SUCCESS and active.remaining != 0
        )
        segment = (
            self._completion_segment(active.remaining, active.lower_address)
            if with_data
            else 0
        )
        offset = active.lower_address & 3
        packet = Tlp()
        packet.header.fmt = (
            TlpFmt.THREE_DW_DATA if with_data else TlpFmt.THREE_DW_NO_DATA
        )
        packet.header.type = TlpType.COMPLETION
        packet.header.traffic_class = request.request_header.traffic_class
        packet.header.attributes = request.request_header.attributes
        packet.header.length_dw = (segment + offset + 3) // 4 if with_data else 0
        packet.header.requester_id = request.request_header.requester_id
        packet.header.completer_id = self.function_id
        packet.header.tag = request.request_header.tag
        packet.header.completion_status = request.status
        packet.header.byte_count = active.remaining
        packet.header.lower_address = active.lower_address
        packet.header.digest_present = request.ecrc_enable
        if with_data:
            payload = self._pack_payload(
                request.payload, active.payload_offset, segment, offset
            )
            if payload is None or len(payload) != packet.header.length_dw:
                self._tx_error(ErrorCode.LOCAL_PAYLOAD)
                self.active_completion = None
                return
            packet.payload = payload
        if packet.header.digest_present:
            packet.ecrc = tlp_ecrc(packet)
        if not self.completion_packets.push(packet):
            self.status.vc_overflow = True
            self._tx_error(ErrorCode.VC_OVERFLOW)
            return
        if with_data and active.remaining > segment:
            active.remaining -= segment
            active.payload_offset += segment
            active.lower_address = (active.lower_address + segment) & 0x7F
        else:
            self.active_completion = None

    def _service_generated_packets(self) -> None:
        self.status.tx_fc_blocked = False
        if (
            not self.transmit_enable
            or self.data_link.status.state != LinkState.DL_ACTIVE
        ):
            return
        request_valid = not self.requester_packets.empty
        completion_valid = not self.completion_packets.empty
        if not request_valid and not completion_valid:
            return
        select_completion = completion_valid and (
            not request_valid or self.prefer_completion
        )
        selected = (
            self.completion_packets if select_completion else self.requester_packets
        )
        packet = selected.front
        if packet is None:
            return
        if not self.data_link.can_transmit_tlp(packet):
            self.status.tx_fc_blocked = True
            return
        if not self.data_link.submit_tlp(packet):
            return
        selected.pop()
        self.prefer_completion = not select_completion

    @staticmethod
    def _validate_received(packet: Tlp) -> ErrorCode:
        header = packet.header
        completion = tlp_is_completion(header.type)
        config_or_io = header.type in (
            TlpType.CONFIG0,
            TlpType.CONFIG1,
            TlpType.IO,
        )
        has_data = tlp_has_data(header.fmt)
        valid_types = (
            TlpType.MEMORY,
            TlpType.IO,
            TlpType.CONFIG0,
            TlpType.CONFIG1,
            TlpType.COMPLETION,
            TlpType.COMPLETION_LOCKED,
        )
        valid_fmts = (
            TlpFmt.THREE_DW_NO_DATA,
            TlpFmt.FOUR_DW_NO_DATA,
            TlpFmt.THREE_DW_DATA,
            TlpFmt.FOUR_DW_DATA,
        )
        if header.fmt not in valid_fmts or header.type not in valid_types:
            return ErrorCode.BAD_FMT_TYPE
        if (config_or_io or completion) and tlp_is_4dw(header.fmt):
            return ErrorCode.BAD_FMT_TYPE
        if (
            header.type == TlpType.MEMORY
            and tlp_is_4dw(header.fmt)
            and not header.address >> 32
        ):
            return ErrorCode.BAD_ADDRESS_FORMAT
        if (
            (config_or_io and header.length_dw != 1)
            or (not completion and header.length_dw == 0)
            or (completion and not has_data and header.length_dw != 0)
            or (has_data and header.length_dw == 0)
            or header.length_dw > ModelConfig.MAX_PAYLOAD_DW
        ):
            return ErrorCode.BAD_LENGTH
        if not completion and header.length_dw == 1 and header.last_be:
            return ErrorCode.BAD_BYTE_ENABLE
        if (
            not completion
            and header.length_dw > 1
            and (not header.first_be or not header.last_be)
        ):
            return ErrorCode.BAD_BYTE_ENABLE
        if (has_data and len(packet.payload) != header.length_dw) or (
            not has_data and packet.payload
        ):
            return ErrorCode.BAD_LENGTH
        if header.digest_present and packet.ecrc != tlp_ecrc(packet):
            return ErrorCode.ECRC
        return ErrorCode.NONE

    def _route_target(self, packet: Tlp) -> bool:
        if self.target_requests.full:
            return False
        request = TargetRequest(packet=packet)
        request.traffic_class = classify_tlp(packet.header)
        request.memory = packet.header.type == TlpType.MEMORY
        request.config = packet.header.type in (TlpType.CONFIG0, TlpType.CONFIG1)
        request.config_type_one = packet.header.type == TlpType.CONFIG1
        request.config_offset = packet.header.address & 0xFFC
        request.read = not tlp_has_data(packet.header.fmt)
        request.write = not request.read
        destination = (
            packet.header.destination_id
            if packet.header.destination_id
            else (packet.header.address >> 16) & 0xFFFF
        )
        request.config_hit = request.config and destination == self.function_id
        span = packet.header.length_dw * 4
        if (
            not tlp_has_data(packet.header.fmt)
            and packet.header.length_dw == 1
            and packet.header.first_be == 0
            and packet.header.last_be == 0
        ):
            span = 1
        end = packet.header.address if span == 0 else packet.header.address + span - 1
        end_overflow = end > 0xFFFFFFFFFFFFFFFF
        matches = 0
        for index in range(ModelConfig.BAR_COUNT):
            if (
                not request.memory
                or not self.memory_enable
                or not self.bar_enable[index]
                or end_overflow
            ):
                continue
            start_match = (
                packet.header.address & self.bar_mask[index]
            ) == (self.bar_base[index] & self.bar_mask[index])
            end_match = (end & self.bar_mask[index]) == (
                self.bar_base[index] & self.bar_mask[index]
            )
            if not start_match or not end_match:
                continue
            matches += 1
            if not request.bar_hit:
                request.bar_hit = True
                request.bar = index
                request.offset = packet.header.address - self.bar_base[index]
        request.bar_overlap = matches > 1
        if request.bar_overlap:
            request.bar_hit = False
        request.unsupported = (
            request.traffic_class == TrafficClass.UNSUPPORTED
            or (request.memory and (not request.bar_hit or request.bar_overlap))
            or (request.config and not request.config_hit)
        )
        return self.target_requests.push(request)

    def _route_completion(self, packet: Tlp) -> bool:
        if self.received_completions.full:
            return False
        found = self._find_tag(packet.header)
        delivered = 0
        if tlp_has_data(packet.header.fmt):
            capacity = packet.header.length_dw * 4 - (
                packet.header.lower_address & 3
            )
            delivered = min(packet.header.byte_count, capacity)
        tracker_error = False
        result_last = False
        if found is not None:
            tag = self.tags[found]
            tracker_error = (
                tag.expects_data
                and packet.header.completion_status == CompletionStatus.SUCCESS
                and (
                    delivered == 0
                    or delivered > tag.remaining
                    or packet.header.byte_count != tag.remaining
                    or packet.header.lower_address != tag.next_lower_address
                )
            ) or (not tag.expects_data and delivered != 0)
            result_last = (
                not tag.expects_data
                or packet.header.completion_status != CompletionStatus.SUCCESS
                or delivered >= tag.remaining
            )
            if not tracker_error and self.results.full:
                return False
        self.received_completions.push(ReceivedCompletion(packet=packet))
        if found is None:
            self.status.unexpected_completion = True
            self.status.completion_error = ErrorCode.UNEXPECTED_COMPLETION
            return True
        if tracker_error:
            self.status.unexpected_completion = True
            self.status.completion_error = ErrorCode.COMPLETION_OVERFLOW
            return True
        tag = self.tags[found]
        self.results.push(
            CompletionResult(
                context=tag.context,
                status=packet.header.completion_status,
                last=result_last,
            )
        )
        if result_last:
            self._retire_tag(found)
        else:
            tag.remaining -= delivered
            tag.next_lower_address = (tag.next_lower_address + delivered) & 0x7F
        return True

    def _service_received_packet(self) -> None:
        if self.pending_rx is None:
            self.pending_rx = self.data_link.pop_received_tlp()
        if self.pending_rx is None:
            return
        error = self._validate_received(self.pending_rx)
        if error != ErrorCode.NONE:
            self._rx_error(error)
            self.data_link.release_received_tlp(self.pending_rx)
            self.pending_rx = None
            return
        accepted = (
            self._route_completion(self.pending_rx)
            if tlp_is_completion(self.pending_rx.header.type)
            else self._route_target(self.pending_rx)
        )
        if accepted:
            self.data_link.release_received_tlp(self.pending_rx)
            self.pending_rx = None

    def tick(self) -> None:
        self.data_link.tick()
        if self.data_link.status.entered_inactive:
            self.phy_codec.reset()
            self._clear_transaction_state()
        self._service_received_packet()
        self._service_command()
        self._service_completion_request()
        self._service_generated_packets()

"""Cycle-stepped PCIe Gen1 Data Link Layer BFM."""

from copy import deepcopy
from typing import List, Optional

from .config import ModelConfig
from .flow_control import FlowControl
from .tlp import classify_tlp, tlp_lcrc
from .types import (
    BoundedQueue,
    CreditSet,
    Dllp,
    DllpType,
    ErrorCode,
    FlowControlCounterSet,
    LinkEvent,
    LinkEventKind,
    LinkState,
    LinkStatus,
    Tlp,
    TlpHeader,
    TrafficClass,
    data_credit_count,
    tlp_has_data,
)


SEQUENCE_MASK = 0xFFF


def _is_init1(dllp_type: DllpType) -> bool:
    return dllp_type in (
        DllpType.INIT_FC1_P,
        DllpType.INIT_FC1_NP,
        DllpType.INIT_FC1_CPL,
    )


def _is_init2(dllp_type: DllpType) -> bool:
    return dllp_type in (
        DllpType.INIT_FC2_P,
        DllpType.INIT_FC2_NP,
        DllpType.INIT_FC2_CPL,
    )


def _is_update(dllp_type: DllpType) -> bool:
    return dllp_type in (
        DllpType.UPDATE_FC_P,
        DllpType.UPDATE_FC_NP,
        DllpType.UPDATE_FC_CPL,
    )


def _init_type(state: LinkState, index: int) -> DllpType:
    if state == LinkState.FC_INIT1:
        return (
            DllpType.INIT_FC1_P,
            DllpType.INIT_FC1_NP,
            DllpType.INIT_FC1_CPL,
        )[index]
    return (
        DllpType.INIT_FC2_P,
        DllpType.INIT_FC2_NP,
        DllpType.INIT_FC2_CPL,
    )[index]


def _receive_credit_class(header: TlpHeader) -> TrafficClass:
    classified = classify_tlp(header)
    if classified != TrafficClass.UNSUPPORTED:
        return classified
    return TrafficClass.POSTED if tlp_has_data(header.fmt) else TrafficClass.NON_POSTED


class DataLinkLayer:
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.flow_control = FlowControl(self.config)
        self.phy_link_up = False
        self.link_rx = BoundedQueue[LinkEvent](ModelConfig.LINK_QUEUE_DEPTH)
        self.link_tx = BoundedQueue[LinkEvent](ModelConfig.LINK_QUEUE_DEPTH)
        self.control_tx = BoundedQueue[Dllp](ModelConfig.LINK_QUEUE_DEPTH)
        self.tlp_tx = BoundedQueue[Tlp](ModelConfig.TRANSACTION_QUEUE_DEPTH)
        self.tlp_rx = {
            TrafficClass.POSTED: BoundedQueue[Tlp](ModelConfig.TRANSACTION_QUEUE_DEPTH),
            TrafficClass.NON_POSTED: BoundedQueue[Tlp](
                ModelConfig.TRANSACTION_QUEUE_DEPTH
            ),
            TrafficClass.COMPLETION: BoundedQueue[Tlp](
                ModelConfig.TRANSACTION_QUEUE_DEPTH
            ),
        }
        self.status = LinkStatus()
        self.replay: List[LinkEvent] = []
        self.replay_cursor = 0
        self.replay_timer = 0
        self.replay_attempts = 0
        self.remote_init1_mask = 0
        self.remote_init2_mask = 0
        self.local_init_mask = 0
        self.init_resend_timer = 0
        self.fc_update_timer = 0
        self.rx_pop_cursor = 0
        self.reset()

    def reset(self) -> None:
        self.phy_link_up = False
        self._reset_link_state()

    def _reset_link_state(self) -> None:
        self.flow_control.reset()
        self.status = LinkStatus(state=LinkState.INACTIVE)
        self.replay.clear()
        self.replay_cursor = 0
        self.replay_timer = 0
        self.replay_attempts = 0
        self.remote_init1_mask = 0
        self.remote_init2_mask = 0
        self.local_init_mask = 0
        self.init_resend_timer = 0
        self.fc_update_timer = 0
        self.rx_pop_cursor = 0
        self.link_rx.clear()
        self.link_tx.clear()
        self.control_tx.clear()
        self.tlp_tx.clear()
        for queue in self.tlp_rx.values():
            queue.clear()

    def set_phy_link_up(self, link_up: bool) -> None:
        self.phy_link_up = link_up

    def push_link_rx(self, event: LinkEvent) -> bool:
        return self.link_rx.push(event)

    def pop_link_tx(self) -> Optional[LinkEvent]:
        return self.link_tx.pop()

    def submit_tlp(self, tlp: Tlp) -> bool:
        return self.tlp_tx.push(tlp)

    def can_transmit_tlp(self, tlp: Tlp) -> bool:
        return self.flow_control.can_transmit(
            classify_tlp(tlp.header), data_credit_count(tlp.payload_dw)
        )

    def pop_received_tlp(self) -> Optional[Tlp]:
        order = (
            TrafficClass.POSTED,
            TrafficClass.NON_POSTED,
            TrafficClass.COMPLETION,
        )
        for checked in range(3):
            index = (self.rx_pop_cursor + checked) % 3
            packet = self.tlp_rx[order[index]].pop()
            if packet is not None:
                self.rx_pop_cursor = (index + 1) % 3
                return packet
        return None

    def release_received_tlp(self, tlp: Tlp) -> None:
        if not self.flow_control.release_receive(
            _receive_credit_class(tlp.header), data_credit_count(tlp.payload_dw)
        ):
            self._record_error(ErrorCode.CREDIT_UNDERFLOW)

    def transmit_credits(self) -> CreditSet:
        return self.flow_control.transmit_available()

    def receive_credits(self) -> CreditSet:
        return self.flow_control.receive_available()

    def flow_control_counters(self) -> FlowControlCounterSet:
        return self.flow_control.counters()

    def _transition(self, state: LinkState) -> None:
        if self.status.state == state:
            return
        self.status.state = state
        self.status.entered_inactive = state == LinkState.INACTIVE
        self.status.entered_fc_init1 = state == LinkState.FC_INIT1
        self.status.entered_fc_init2 = state == LinkState.FC_INIT2
        self.status.entered_dl_active = state == LinkState.DL_ACTIVE
        self.status.flow_control_initialized = state == LinkState.DL_ACTIVE
        self.local_init_mask = 0
        self.init_resend_timer = 0

    def _record_error(self, error: ErrorCode, fatal: bool = False) -> None:
        self.status.protocol_error = True
        self.status.fatal_error = self.status.fatal_error or fatal
        self.status.last_error = error

    @staticmethod
    def _init_bit(dllp_type: DllpType) -> int:
        if dllp_type in (DllpType.INIT_FC1_P, DllpType.INIT_FC2_P):
            return 1
        if dllp_type in (DllpType.INIT_FC1_NP, DllpType.INIT_FC2_NP):
            return 2
        return 4

    @staticmethod
    def _sequence_is_older(sequence: int, reference: int) -> bool:
        distance = (reference - sequence) & SEQUENCE_MASK
        return distance != 0 and distance < 0x800

    def _emit_control(self, dllp: Dllp) -> None:
        if not self.control_tx.push(dllp):
            self._record_error(ErrorCode.RECEIVE_OVERFLOW)

    def _process_dllp(self, dllp: Dllp) -> None:
        if dllp.type == DllpType.ACK:
            self._acknowledge(dllp.sequence & SEQUENCE_MASK)
            return
        if dllp.type == DllpType.NAK:
            self._start_replay(dllp.sequence & SEQUENCE_MASK)
            return
        if _is_init1(dllp.type):
            if self.status.state == LinkState.DL_ACTIVE or not self.flow_control.receive(
                dllp, True
            ):
                self._record_error(ErrorCode.CREDIT_UNDERFLOW)
                return
            self.remote_init1_mask |= self._init_bit(dllp.type)
            if self.status.state == LinkState.FC_INIT1 and self.remote_init1_mask == 7:
                self._transition(LinkState.FC_INIT2)
            return
        if _is_init2(dllp.type):
            if self.status.state == LinkState.DL_ACTIVE or not self.flow_control.receive(
                dllp, True
            ):
                self._record_error(ErrorCode.CREDIT_UNDERFLOW)
                return
            self.remote_init2_mask |= self._init_bit(dllp.type)
            if (
                self.status.state == LinkState.FC_INIT2
                and self.remote_init2_mask == 7
                and self.local_init_mask == 7
            ):
                self._transition(LinkState.DL_ACTIVE)
            return
        if _is_update(dllp.type) and (
            self.status.state != LinkState.DL_ACTIVE
            or not self.flow_control.receive(dllp, False)
        ):
            self._record_error(ErrorCode.CREDIT_UNDERFLOW)

    def _process_rx_tlp(self, event: LinkEvent) -> None:
        if self.status.state != LinkState.DL_ACTIVE:
            return
        sequence = event.sequence & SEQUENCE_MASK
        if event.lcrc != tlp_lcrc(sequence, event.tlp):
            self._emit_control(
                Dllp(type=DllpType.NAK, sequence=self.status.expected_rx_sequence)
            )
            self._record_error(ErrorCode.LCRC)
            return
        if sequence != self.status.expected_rx_sequence:
            if self._sequence_is_older(sequence, self.status.expected_rx_sequence):
                self._emit_control(Dllp(type=DllpType.ACK, sequence=sequence))
            else:
                self._emit_control(
                    Dllp(
                        type=DllpType.NAK,
                        sequence=self.status.expected_rx_sequence,
                    )
                )
                self._record_error(ErrorCode.BAD_SEQUENCE)
            return
        traffic = _receive_credit_class(event.tlp.header)
        data_credits = data_credit_count(event.tlp.payload_dw)
        if not self.flow_control.reserve_receive(traffic, data_credits):
            self._emit_control(Dllp(type=DllpType.NAK, sequence=sequence))
            overflow = self.flow_control.receiver_overflow_detected
            self._record_error(
                ErrorCode.FLOW_CONTROL_OVERFLOW
                if overflow
                else ErrorCode.RECEIVE_OVERFLOW,
                fatal=overflow,
            )
            return
        if not self.tlp_rx[traffic].push(event.tlp):
            self.flow_control.release_receive(traffic, data_credits)
            self._emit_control(Dllp(type=DllpType.NAK, sequence=sequence))
            self._record_error(ErrorCode.RECEIVE_OVERFLOW)
            return
        self.status.expected_rx_sequence = (sequence + 1) & SEQUENCE_MASK
        self._emit_control(Dllp(type=DllpType.ACK, sequence=sequence))

    def _process_rx(self, event: LinkEvent) -> None:
        if event.kind == LinkEventKind.DLLP:
            self._process_dllp(event.dllp)
        else:
            self._process_rx_tlp(event)

    def _acknowledge(self, sequence: int) -> None:
        match = next(
            (
                index
                for index, event in enumerate(self.replay)
                if event.sequence == sequence
            ),
            None,
        )
        if match is None:
            return
        del self.replay[: match + 1]
        self.replay_timer = 0
        self.replay_attempts = 0
        if not self.replay:
            self.status.replay_active = False
            self.replay_cursor = 0
        elif self.status.replay_active:
            self.replay_cursor = 0

    def _start_replay(self, sequence: int) -> None:
        start = next(
            (
                index
                for index, event in enumerate(self.replay)
                if event.sequence == sequence
            ),
            None,
        )
        if start is None:
            return
        if self.replay_attempts >= self.config.max_replay_attempts:
            self._reset_link_state()
            self.status.entered_inactive = True
            self.status.protocol_error = True
            self.status.fatal_error = True
            self.status.last_error = ErrorCode.REPLAY_EXHAUSTED
            return
        self.replay_attempts += 1
        self.replay_cursor = start
        self.replay_timer = 0
        self.status.replay_active = True

    def _service_replay(self) -> None:
        if not self.status.replay_active or self.link_tx.full:
            return
        if self.replay_cursor >= len(self.replay):
            self.status.replay_active = False
            self.replay_cursor = 0
            return
        self.link_tx.push(self.replay[self.replay_cursor])
        self.replay_cursor += 1

    def _emit_initial_credit(self) -> None:
        if self.link_tx.full:
            return
        if self.local_init_mask == 7:
            self.init_resend_timer += 1
            if self.init_resend_timer < self.config.fc_init_resend_cycles:
                return
            self.local_init_mask = 0
            self.init_resend_timer = 0
        for index in range(3):
            bit = 1 << index
            if not self.local_init_mask & bit:
                dllp_type = _init_type(self.status.state, index)
                self.link_tx.push(
                    LinkEvent(
                        kind=LinkEventKind.DLLP,
                        dllp=self.flow_control.make_initial(dllp_type),
                    )
                )
                self.local_init_mask |= bit
                break
        if (
            self.status.state == LinkState.FC_INIT2
            and self.remote_init2_mask == 7
            and self.local_init_mask == 7
        ):
            self._transition(LinkState.DL_ACTIVE)

    def _emit_update_credit(self) -> None:
        if not self.flow_control.update_pending:
            return
        self.fc_update_timer += 1
        if self.fc_update_timer < self.config.fc_update_interval_cycles:
            return
        dllp = self.flow_control.next_update()
        if dllp is not None:
            self._emit_control(dllp)
        self.fc_update_timer = 0

    def _transmit_new_tlp(self) -> None:
        if (
            self.status.state != LinkState.DL_ACTIVE
            or self.link_tx.full
            or len(self.replay) >= ModelConfig.REPLAY_ENTRIES
        ):
            return
        packet = self.tlp_tx.front
        if packet is None:
            return
        traffic = classify_tlp(packet.header)
        data_credits = data_credit_count(packet.payload_dw)
        if not self.flow_control.can_transmit(traffic, data_credits):
            return
        event = LinkEvent(
            kind=LinkEventKind.TLP,
            tlp=deepcopy(packet),
            sequence=self.status.next_tx_sequence,
        )
        event.lcrc = tlp_lcrc(event.sequence, event.tlp)
        if not self.flow_control.consume_transmit(traffic, data_credits):
            return
        self.replay.append(deepcopy(event))
        self.tlp_tx.pop()
        self.link_tx.push(event)
        self.status.next_tx_sequence = (
            self.status.next_tx_sequence + 1
        ) & SEQUENCE_MASK
        self.replay_timer = 0

    def tick(self) -> None:
        self.status.entered_inactive = False
        self.status.entered_fc_init1 = False
        self.status.entered_fc_init2 = False
        self.status.entered_dl_active = False
        if not self.phy_link_up:
            if self.status.state != LinkState.INACTIVE:
                self._reset_link_state()
                self.status.entered_inactive = True
            return
        if self.status.state == LinkState.INACTIVE:
            self._transition(LinkState.FC_INIT1)
        incoming = self.link_rx.pop()
        if incoming is not None:
            self._process_rx(incoming)
        if not self.control_tx.empty and not self.link_tx.full:
            dllp = self.control_tx.pop()
            if dllp is not None:
                self.link_tx.push(LinkEvent(kind=LinkEventKind.DLLP, dllp=dllp))
        elif self.status.state in (LinkState.FC_INIT1, LinkState.FC_INIT2):
            self._emit_initial_credit()
        elif self.status.state == LinkState.DL_ACTIVE:
            self._emit_update_credit()
            self._service_replay()
            if not self.status.replay_active:
                self._transmit_new_tlp()
        if self.replay and not self.status.replay_active:
            self.replay_timer += 1
            if self.replay_timer >= self.config.replay_timeout_cycles:
                self._start_replay(self.replay[0].sequence)

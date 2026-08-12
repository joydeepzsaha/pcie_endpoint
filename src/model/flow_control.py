"""PCIe VC0 credit accounting and modulo rollover rules."""

from dataclasses import dataclass, field
from typing import Dict, Optional

from .config import ModelConfig
from .types import (
    CreditSet,
    Dllp,
    DllpType,
    FlowControlCounterSet,
    TrafficClass,
)


@dataclass
class _TxCounter:
    limit: int = 0
    consumed: int = 0
    infinite: bool = False
    initialized: bool = False


@dataclass
class _TxPool:
    header: _TxCounter = field(default_factory=_TxCounter)
    data: _TxCounter = field(default_factory=_TxCounter)


@dataclass
class _RxPool:
    header_capacity: int = 0
    data_capacity: int = 0
    header_used: int = 0
    data_used: int = 0
    header_limit: int = 0
    data_limit: int = 0
    header_received: int = 0
    data_received: int = 0
    dirty: bool = False


def _dllp_class(dllp_type: DllpType) -> TrafficClass:
    if dllp_type in (DllpType.INIT_FC1_P, DllpType.INIT_FC2_P, DllpType.UPDATE_FC_P):
        return TrafficClass.POSTED
    if dllp_type in (
        DllpType.INIT_FC1_CPL,
        DllpType.INIT_FC2_CPL,
        DllpType.UPDATE_FC_CPL,
    ):
        return TrafficClass.COMPLETION
    return TrafficClass.NON_POSTED


class FlowControl:
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.tx: Dict[TrafficClass, _TxPool] = {}
        self.rx: Dict[TrafficClass, _RxPool] = {}
        self.update_cursor = 0
        self.receiver_overflow_detected = False
        self.reset()

    @staticmethod
    def _clamp(value: int, maximum: int) -> int:
        return 1 if value == 0 else min(value, maximum)

    def reset(self) -> None:
        self.tx = {
            TrafficClass.POSTED: _TxPool(),
            TrafficClass.NON_POSTED: _TxPool(),
            TrafficClass.COMPLETION: _TxPool(),
        }
        capacities = {
            TrafficClass.POSTED: (
                self.config.posted_header_credits,
                self.config.posted_data_credits,
            ),
            TrafficClass.NON_POSTED: (
                self.config.nonposted_header_credits,
                self.config.nonposted_data_credits,
            ),
            TrafficClass.COMPLETION: (
                self.config.completion_header_credits,
                self.config.completion_data_credits,
            ),
        }
        self.rx = {}
        for traffic, (header, data) in capacities.items():
            pool = _RxPool(
                header_capacity=self._clamp(
                    header, ModelConfig.TRANSACTION_QUEUE_DEPTH
                ),
                data_capacity=self._clamp(data, 0x800),
            )
            pool.header_limit = pool.header_capacity
            pool.data_limit = pool.data_capacity
            self.rx[traffic] = pool
        self.update_cursor = 0
        self.receiver_overflow_detected = False

    @staticmethod
    def _available(counter: _TxCounter, mask: int) -> int:
        if counter.infinite:
            return mask
        if not counter.initialized:
            return 0
        remaining = (counter.limit - counter.consumed) & mask
        return remaining if remaining <= (mask + 1) // 2 else 0

    @staticmethod
    def _allocation_valid(limit: int, consumed_pending: int, mask: int) -> bool:
        remaining = (limit - consumed_pending) & mask
        return remaining <= (mask + 1) // 2

    @staticmethod
    def _receiver_overflow(allocated: int, received: int, mask: int) -> bool:
        # Strict '>' is required: CA == CR is a legal full-buffer condition.
        difference = (allocated - received) & mask
        return difference > (mask + 1) // 2

    def _update_counter(
        self,
        counter: _TxCounter,
        value: int,
        mask: int,
        initial: bool,
    ) -> bool:
        value &= mask
        if initial:
            if (
                not (self.config.initial_zero_credit_is_infinite and value == 0)
                and value > (mask + 1) // 2
            ):
                return False
            counter.limit = value
            counter.consumed = 0
            counter.infinite = (
                self.config.initial_zero_credit_is_infinite and value == 0
            )
            counter.initialized = True
            return True
        if not counter.initialized:
            return False
        if counter.infinite:
            return True
        advance = (value - counter.limit) & mask
        if advance > (mask + 1) // 2:
            return False
        counter.limit = value
        return True

    def receive(self, dllp: Dllp, initial: bool) -> bool:
        fc_types = {
            DllpType.INIT_FC1_P,
            DllpType.INIT_FC1_NP,
            DllpType.INIT_FC1_CPL,
            DllpType.INIT_FC2_P,
            DllpType.INIT_FC2_NP,
            DllpType.INIT_FC2_CPL,
            DllpType.UPDATE_FC_P,
            DllpType.UPDATE_FC_NP,
            DllpType.UPDATE_FC_CPL,
        }
        if dllp.type not in fc_types or dllp.vc != 0:
            return False
        pool = self.tx[_dllp_class(dllp.type)]
        header_ok = self._update_counter(pool.header, dllp.header_credits, 0xFF, initial)
        data_ok = self._update_counter(pool.data, dllp.data_credits, 0xFFF, initial)
        return header_ok and data_ok

    def can_transmit(self, traffic: TrafficClass, data_credits: int) -> bool:
        if traffic == TrafficClass.UNSUPPORTED:
            return False
        pool = self.tx[traffic]
        pending_header = (pool.header.consumed + 1) & 0xFF
        pending_data = (pool.data.consumed + data_credits) & 0xFFF
        return (
            pool.header.infinite
            or (
                pool.header.initialized
                and self._allocation_valid(pool.header.limit, pending_header, 0xFF)
            )
        ) and (
            pool.data.infinite
            or (
                pool.data.initialized
                and self._allocation_valid(pool.data.limit, pending_data, 0xFFF)
            )
        )

    def consume_transmit(self, traffic: TrafficClass, data_credits: int) -> bool:
        if not self.can_transmit(traffic, data_credits):
            return False
        pool = self.tx[traffic]
        if not pool.header.infinite:
            pool.header.consumed = (pool.header.consumed + 1) & 0xFF
        if not pool.data.infinite:
            pool.data.consumed = (pool.data.consumed + data_credits) & 0xFFF
        return True

    def reserve_receive(self, traffic: TrafficClass, data_credits: int) -> bool:
        if traffic == TrafficClass.UNSUPPORTED:
            return False
        pool = self.rx[traffic]
        next_header = (pool.header_received + 1) & 0xFF
        next_data = (pool.data_received + data_credits) & 0xFFF
        if (
            self._receiver_overflow(pool.header_limit, next_header, 0xFF)
            or self._receiver_overflow(pool.data_limit, next_data, 0xFFF)
            or pool.header_used >= pool.header_capacity
            or pool.data_used + data_credits > pool.data_capacity
        ):
            self.receiver_overflow_detected = True
            return False
        pool.header_received = next_header
        pool.data_received = next_data
        pool.header_used += 1
        pool.data_used += data_credits
        return True

    def release_receive(self, traffic: TrafficClass, data_credits: int) -> bool:
        if traffic == TrafficClass.UNSUPPORTED:
            return False
        pool = self.rx[traffic]
        if pool.header_used == 0 or pool.data_used < data_credits:
            return False
        pool.header_used -= 1
        pool.data_used -= data_credits
        pool.header_limit = (pool.header_limit + 1) & 0xFF
        pool.data_limit = (pool.data_limit + data_credits) & 0xFFF
        pool.dirty = True
        return True

    def _initial_for(self, traffic: TrafficClass, phase_two: bool) -> Dllp:
        types = {
            (TrafficClass.POSTED, False): DllpType.INIT_FC1_P,
            (TrafficClass.NON_POSTED, False): DllpType.INIT_FC1_NP,
            (TrafficClass.COMPLETION, False): DllpType.INIT_FC1_CPL,
            (TrafficClass.POSTED, True): DllpType.INIT_FC2_P,
            (TrafficClass.NON_POSTED, True): DllpType.INIT_FC2_NP,
            (TrafficClass.COMPLETION, True): DllpType.INIT_FC2_CPL,
        }
        pool = self.rx[traffic]
        return Dllp(
            type=types[(traffic, phase_two)],
            header_credits=pool.header_capacity,
            data_credits=pool.data_capacity,
        )

    def make_initial(self, dllp_type: DllpType) -> Dllp:
        phase_two = dllp_type in (
            DllpType.INIT_FC2_P,
            DllpType.INIT_FC2_NP,
            DllpType.INIT_FC2_CPL,
        )
        return self._initial_for(_dllp_class(dllp_type), phase_two)

    def _update_for(self, traffic: TrafficClass) -> Dllp:
        types = {
            TrafficClass.POSTED: DllpType.UPDATE_FC_P,
            TrafficClass.NON_POSTED: DllpType.UPDATE_FC_NP,
            TrafficClass.COMPLETION: DllpType.UPDATE_FC_CPL,
        }
        pool = self.rx[traffic]
        return Dllp(
            type=types[traffic],
            header_credits=pool.header_limit,
            data_credits=pool.data_limit,
        )

    def next_update(self) -> Optional[Dllp]:
        order = (
            TrafficClass.POSTED,
            TrafficClass.NON_POSTED,
            TrafficClass.COMPLETION,
        )
        for checked in range(3):
            index = (self.update_cursor + checked) % 3
            traffic = order[index]
            if self.rx[traffic].dirty:
                self.rx[traffic].dirty = False
                self.update_cursor = (index + 1) % 3
                return self._update_for(traffic)
        return None

    @property
    def update_pending(self) -> bool:
        return any(pool.dirty for pool in self.rx.values())

    def transmit_available(self) -> CreditSet:
        result = CreditSet()
        for traffic, target in (
            (TrafficClass.POSTED, result.posted),
            (TrafficClass.NON_POSTED, result.nonposted),
            (TrafficClass.COMPLETION, result.completion),
        ):
            pool = self.tx[traffic]
            target.header = self._available(pool.header, 0xFF)
            target.data = self._available(pool.data, 0xFFF)
            target.header_infinite = pool.header.infinite
            target.data_infinite = pool.data.infinite
        return result

    def receive_available(self) -> CreditSet:
        result = CreditSet()
        for traffic, target in (
            (TrafficClass.POSTED, result.posted),
            (TrafficClass.NON_POSTED, result.nonposted),
            (TrafficClass.COMPLETION, result.completion),
        ):
            pool = self.rx[traffic]
            target.header = pool.header_capacity - pool.header_used
            target.data = pool.data_capacity - pool.data_used
        return result

    def counters(self) -> FlowControlCounterSet:
        result = FlowControlCounterSet()
        mapping = (
            (
                TrafficClass.POSTED,
                result.posted_header,
                result.posted_data,
            ),
            (
                TrafficClass.NON_POSTED,
                result.nonposted_header,
                result.nonposted_data,
            ),
            (
                TrafficClass.COMPLETION,
                result.completion_header,
                result.completion_data,
            ),
        )
        for traffic, header, data in mapping:
            tx, rx = self.tx[traffic], self.rx[traffic]
            header.credit_limit = tx.header.limit
            header.credits_consumed = tx.header.consumed
            header.credit_allocated = rx.header_limit
            header.credits_received = rx.header_received
            header.infinite = tx.header.infinite
            data.credit_limit = tx.data.limit
            data.credits_consumed = tx.data.consumed
            data.credit_allocated = rx.data_limit
            data.credits_received = rx.data_received
            data.infinite = tx.data.infinite
        return result

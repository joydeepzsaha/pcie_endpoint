"""Static configuration for the packet-level PCIe Endpoint BFM."""

from dataclasses import dataclass, field
from typing import ClassVar, List


@dataclass
class ModelConfig:
    GEN1_TRANSFER_RATE: ClassVar[int] = 2_500_000_000
    PCIE_GENERATION: ClassVar[int] = 1
    DEFAULT_LINK_WIDTH: ClassVar[int] = 1
    MAX_PAYLOAD_DW: ClassVar[int] = 1024
    MAX_COMMAND_DW: ClassVar[int] = 2048
    LINK_QUEUE_DEPTH: ClassVar[int] = 32
    TRANSACTION_QUEUE_DEPTH: ClassVar[int] = 32
    REPLAY_ENTRIES: ClassVar[int] = 16
    MAX_TAGS: ClassVar[int] = 256
    VIRTUAL_CHANNEL_DEPTH: ClassVar[int] = 4
    BAR_COUNT: ClassVar[int] = 6

    completer_id: int = 0
    tag_count: int = 32
    max_payload_bytes: int = 128
    max_read_request_bytes: int = 128
    read_completion_boundary_bytes: int = 128

    bar_base: List[int] = field(
        default_factory=lambda: [0] * ModelConfig.BAR_COUNT
    )
    bar_mask: List[int] = field(
        default_factory=lambda: [0xFFFFFFFFFFFFF000] + [0] * 5
    )
    bar_enable: List[bool] = field(
        default_factory=lambda: [True] + [False] * 5
    )

    posted_header_credits: int = 32
    posted_data_credits: int = 256
    nonposted_header_credits: int = 32
    nonposted_data_credits: int = 64
    completion_header_credits: int = 32
    completion_data_credits: int = 256

    replay_timeout_cycles: int = 4096
    max_replay_attempts: int = 3
    fc_update_interval_cycles: int = 128
    fc_init_resend_cycles: int = 64
    initial_zero_credit_is_infinite: bool = True

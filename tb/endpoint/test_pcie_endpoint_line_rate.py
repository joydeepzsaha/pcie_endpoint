"""Gen1 x1/x4 logical line-rate tests for the integrated PCIe endpoint."""

from dataclasses import dataclass
import zlib

import cocotb
from cocotb.clock import Clock
from cocotb.queue import Queue
from cocotb.triggers import FallingEdge, RisingEdge, with_timeout
from cocotbext.pcie.core.dllp import Dllp, DllpType
from cocotbext.pcie.core.tlp import Tlp, TlpType
from cocotbext.pcie.core.utils import PcieId

from pcie_gen1_traffic import (
    Gen1Decoder,
    Gen1Encoder,
    PHY_USER_IS_DLLP,
    PHY_USER_IS_TLP,
    SymbolGroup,
    add_sequence_and_lcrc,
    build_ack_nak,
    build_fc_dllp,
    build_message_tlp,
    calculate_dllp_crc,
    expected_symbol_cycles,
    parse_message_tlp,
)


CMD_MEM_READ = 0
CMD_MEM_WRITE = 1
CMD_MSG = 6
CMD_MSG_DATA = 7
SYMBOL_CLOCK_HZ = 250_000_000


def word_bytes(data: int, keep: int) -> bytes:
    return bytes(
        (data >> (8 * lane)) & 0xFF
        for lane in range(4)
        if keep & (1 << lane)
    )


@dataclass
class DecodedFrame:
    data: bytes
    user: int
    symbol_cycles: int
    elapsed_cycles: int


class TxSymbolMonitor:
    def __init__(self, dut, lane_count: int):
        self.dut = dut
        self.decoder = Gen1Decoder(lane_count)
        self.frames = Queue()
        self.cycle = 0

    async def run(self):
        frame = bytearray()
        frame_user = 0
        frame_groups = 0
        frame_start_cycle = 0
        while True:
            await FallingEdge(self.dut.clk_i)
            self.cycle += 1
            if int(self.dut.rst_i.value):
                frame.clear()
                frame_user = 0
                frame_groups = 0
                self.decoder.reset()
                continue
            if int(self.dut.tx_symbol_valid_o.value) and int(
                self.dut.tx_symbol_ready_i.value
            ):
                sop = int(self.dut.tx_symbol_sop_o.value)
                eop = int(self.dut.tx_symbol_eop_o.value)
                if sop:
                    assert not frame, "new TX logical-PHY frame started before prior EOP"
                    frame_user = int(self.dut.tx_symbol_user_o.value)
                    frame_start_cycle = self.cycle
                    frame_groups = 0
                assert frame or sop, "TX symbol appeared without SOP"
                frame.extend(self.decoder.decode_group(
                    int(self.dut.tx_symbol_data_o.value),
                    int(self.dut.tx_symbol_keep_o.value),
                ))
                frame_groups += 1
                if eop:
                    await self.frames.put(DecodedFrame(
                        bytes(frame),
                        frame_user,
                        frame_groups,
                        self.cycle - frame_start_cycle + 1,
                    ))
                    frame.clear()

    async def recv(self, timeout_us=1000) -> DecodedFrame:
        return await with_timeout(self.frames.get(), timeout_us, "us")

    async def recv_link_tlp(self) -> DecodedFrame:
        while True:
            frame = await self.recv()
            if len(frame.data) != 6:
                return frame

    async def recv_dllp(self, expected_type: DllpType) -> Dllp:
        while True:
            frame = await self.recv()
            if len(frame.data) != 6:
                continue
            payload = frame.data[:4]
            if frame.data[4:] != calculate_dllp_crc(payload).to_bytes(2, "little"):
                continue
            decoded = Dllp().unpack(payload)
            if decoded.type == expected_type:
                return decoded


class RxPathMonitor:
    """Retain the most recent complete frame at every integrated RX boundary."""

    PATHS = ("s_phy_axis", "post_dll_axis", "mid_rx_axis")

    def __init__(self, dut):
        self.dut = dut
        self.active = {path: bytearray() for path in self.PATHS}
        self.last_frame = {path: None for path in self.PATHS}
        self.frames_seen = {path: 0 for path in self.PATHS}
        self.target_seen = False
        self.malformed_seen = False
        self.rx_error_seen = False
        self.rx_error_code = 0
        self.dll_crc_checked = False
        self.dll_crc_passed = False
        self.dll_nullified_at_check = False

    def reset(self):
        for path in self.PATHS:
            self.active[path].clear()
            self.last_frame[path] = None
            self.frames_seen[path] = 0
        self.target_seen = False
        self.malformed_seen = False
        self.rx_error_seen = False
        self.rx_error_code = 0
        self.dll_crc_checked = False
        self.dll_crc_passed = False
        self.dll_nullified_at_check = False

    async def run(self):
        while True:
            await FallingEdge(self.dut.clk_i)
            if int(self.dut.rst_i.value):
                self.reset()
                continue

            for path in self.PATHS:
                valid = int(getattr(self.dut, f"{path}_tvalid").value)
                ready = int(getattr(self.dut, f"{path}_tready").value)
                if valid and ready:
                    self.active[path].extend(word_bytes(
                        int(getattr(self.dut, f"{path}_tdata").value),
                        int(getattr(self.dut, f"{path}_tkeep").value),
                    ))
                    if int(getattr(self.dut, f"{path}_tlast").value):
                        self.last_frame[path] = bytes(self.active[path])
                        self.active[path].clear()
                        self.frames_seen[path] += 1

            self.target_seen |= bool(int(self.dut.target_request_valid_o.value))
            if int(self.dut.malformed_o.value):
                self.malformed_seen = True
            if int(self.dut.rx_error_valid_o.value):
                self.rx_error_seen = True
                self.rx_error_code = int(self.dut.rx_error_code_o.value)
            # ST_CHECK_CRC is value 4 in dllp2tlp's dll_rx_st_e.  Capture the
            # combinational comparison here because the live CRC registers are
            # reinitialized after the packet decision.
            if int(self.dut.dll_rx_state.value) == 4:
                self.dll_crc_checked = True
                self.dll_nullified_at_check = bool(
                    int(self.dut.dll_rx_nullified.value)
                )
                self.dll_crc_passed = (
                    bool(int(self.dut.dll_lcrc_match.value)) and
                    not self.dll_nullified_at_check and
                    int(self.dut.dll_received_sequence.value) ==
                    int(self.dut.dll_expected_sequence.value)
                )

    @staticmethod
    def _frame_result(name: str, actual: bytes | None, expected: bytes) -> str:
        if actual is None:
            return f"{name}=missing"
        if actual == expected:
            return f"{name}=exact({len(actual)}B)"
        mismatch = next(
            (index for index, pair in enumerate(zip(actual, expected))
             if pair[0] != pair[1]),
            min(len(actual), len(expected)),
        )
        return (
            f"{name}=mismatch(actual={len(actual)}B expected={len(expected)}B "
            f"first_byte={mismatch})"
        )

    def describe(self, protected: bytes, raw_tlp: bytes) -> str:
        results = [
            self._frame_result("decoded_phy", self.last_frame["s_phy_axis"], protected),
            self._frame_result("post_dll", self.last_frame["post_dll_axis"], raw_tlp),
            self._frame_result("parser_input", self.last_frame["mid_rx_axis"], raw_tlp),
        ]
        results.extend((
            f"dll_state={int(self.dut.dll_rx_state.value)}",
            f"dll_seq={int(self.dut.dll_received_sequence.value):03x}",
            f"dll_expected={int(self.dut.dll_expected_sequence.value):03x}",
            f"dll_nullified={int(self.dut.dll_rx_nullified.value)}",
            f"dll_crc_checked={int(self.dll_crc_checked)}",
            f"dll_crc_passed={int(self.dll_crc_passed)}",
            f"dll_nullified_at_check={int(self.dll_nullified_at_check)}",
            f"dll_response_is_nak={int(self.dut.dll_response_is_nak.value)}",
            f"dll_nak_scheduled={int(self.dut.dll_nak_scheduled.value)}",
            f"parser_state={int(self.dut.parser_state.value)}",
            f"parser_header_valid={int(self.dut.parser_header_valid.value)}",
            f"parser_header_legal={int(self.dut.parser_header_legal.value)}",
            f"parser_packet_ended={int(self.dut.parser_packet_ended.value)}",
            f"parser_completion={int(self.dut.parser_classified_completion.value)}",
            f"malformed_seen={int(self.malformed_seen)}",
            f"rx_error_seen={int(self.rx_error_seen)}",
            f"rx_error_code={self.rx_error_code}",
            f"code_error={int(self.dut.rx_code_error_o.value):x}",
            f"disparity_error={int(self.dut.rx_disparity_error_o.value):x}",
        ))
        return ", ".join(results)

    def assert_complete_path(self, protected: bytes, raw_tlp: bytes):
        assert self.last_frame["s_phy_axis"] == protected, self.describe(
            protected, raw_tlp
        )
        assert self.last_frame["post_dll_axis"] == raw_tlp, self.describe(
            protected, raw_tlp
        )
        assert self.last_frame["mid_rx_axis"] == raw_tlp, self.describe(
            protected, raw_tlp
        )


class LineRateTB:
    def __init__(self, dut):
        self.dut = dut
        self.lane_count = int(dut.logical_lane_count_o.value)
        assert self.lane_count in (1, 4)
        self.rx_encoder = Gen1Encoder(self.lane_count)
        cocotb.start_soon(Clock(dut.clk_i, 4, units="ns").start())
        self.tx_monitor = TxSymbolMonitor(dut, self.lane_count)
        self.rx_monitor = RxPathMonitor(dut)
        cocotb.start_soon(self.tx_monitor.run())
        cocotb.start_soon(self.rx_monitor.run())

    async def reset(self):
        d = self.dut
        self.rx_encoder.reset()
        self.rx_monitor.reset()
        d.rst_i.value = 1
        d.phy_link_up_i.value = 0
        d.idle_valid_i.value = 0
        d.transmit_enable_i.value = 0
        d.memory_enable_i.value = 1
        d.extended_tag_enable_i.value = 0
        d.max_payload_bytes_i.value = 128
        d.max_read_bytes_i.value = 128
        d.rcb_128b_i.value = 1
        d.command_valid_i.value = 0
        d.command_i.value = 0
        d.command_address_i.value = 0
        d.command_byte_count_i.value = 0
        d.command_tc_i.value = 0
        d.command_attr_i.value = 0
        d.command_message_route_i.value = 0
        d.command_message_code_i.value = 0
        d.command_context_i.value = 0
        d.command_prefix_valid_i.value = 0
        d.command_prefix_i.value = 0
        d.command_ecrc_enable_i.value = 0
        d.command_data_i.value = 0
        d.command_keep_i.value = 0
        d.command_data_valid_i.value = 0
        d.command_data_last_i.value = 0
        d.target_request_ready_i.value = 1
        d.target_data_ready_i.value = 1
        d.completion_request_valid_i.value = 0
        d.completion_request_header_i.value = 0
        d.completion_request_status_i.value = 0
        d.completion_request_byte_count_i.value = 0
        d.completion_request_lower_address_i.value = 0
        d.completion_request_ecrc_enable_i.value = 0
        d.completion_request_data_i.value = 0
        d.completion_request_keep_i.value = 0
        d.completion_request_data_valid_i.value = 0
        d.completion_request_data_last_i.value = 0
        d.received_completion_ready_i.value = 1
        d.received_completion_data_ready_i.value = 1
        d.result_ready_i.value = 1
        d.rx_symbol_data_i.value = 0
        d.rx_symbol_keep_i.value = 0
        d.rx_symbol_valid_i.value = 0
        d.rx_symbol_sop_i.value = 0
        d.rx_symbol_eop_i.value = 0
        d.rx_symbol_user_i.value = 0
        d.tx_symbol_ready_i.value = 1
        for _ in range(12):
            await RisingEdge(d.clk_i)
        d.rst_i.value = 0
        d.phy_link_up_i.value = 1
        d.idle_valid_i.value = 1
        d.transmit_enable_i.value = 1
        for _ in range(12):
            await RisingEdge(d.clk_i)

    async def wait_high(self, signal, cycles=10000, context=""):
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)
            if signal.value.is_resolvable and int(signal.value):
                return
        suffix = f" while {context}" if context else ""
        raise AssertionError(f"{signal._name} did not assert{suffix}")

    async def wait_target_request(
        self, protected: bytes, raw_tlp: bytes, cycles=10000, context=""
    ):
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)
            if (self.dut.target_request_valid_o.value.is_resolvable and
                    int(self.dut.target_request_valid_o.value)):
                self.rx_monitor.assert_complete_path(protected, raw_tlp)
                return
        suffix = f" while {context}" if context else ""
        raise AssertionError(
            "target_request_valid_o did not assert"
            f"{suffix}: {self.rx_monitor.describe(protected, raw_tlp)}"
        )

    async def send_rx_groups(self, groups, user: int):
        for group in groups:
            await FallingEdge(self.dut.clk_i)
            self.dut.rx_symbol_data_i.value = group.data
            self.dut.rx_symbol_keep_i.value = group.keep
            self.dut.rx_symbol_sop_i.value = group.sop
            self.dut.rx_symbol_eop_i.value = group.eop
            self.dut.rx_symbol_user_i.value = user
            self.dut.rx_symbol_valid_i.value = 1
            while True:
                await RisingEdge(self.dut.clk_i)
                if int(self.dut.rx_symbol_ready_o.value):
                    break
        await FallingEdge(self.dut.clk_i)
        self.dut.rx_symbol_valid_i.value = 0
        self.dut.rx_symbol_keep_i.value = 0
        self.dut.rx_symbol_sop_i.value = 0
        self.dut.rx_symbol_eop_i.value = 0

    async def send_rx_frame(self, payload: bytes, user: int):
        await self.send_rx_groups(self.rx_encoder.encode_frame(payload), user)

    async def initialize_flow_control(self):
        sequence = (
            DllpType.INIT_FC1_P,
            DllpType.INIT_FC1_NP,
            DllpType.INIT_FC1_CPL,
            DllpType.INIT_FC2_P,
            DllpType.INIT_FC2_P,
            DllpType.INIT_FC2_NP,
            DllpType.INIT_FC2_CPL,
        )
        for dllp_type in sequence:
            await self.send_rx_frame(
                build_fc_dllp(dllp_type), PHY_USER_IS_DLLP
            )
            for _ in range(24):
                await RisingEdge(self.dut.clk_i)
        await self.wait_high(
            self.dut.fc_initialized_o, context="initializing Data Link credits"
        )

    async def submit_command(
        self, command, address, payload=b"", byte_count=None,
        message_route=0, message_code=0, context=None, timeout_cycles=10000,
    ):
        d = self.dut
        if byte_count is None:
            byte_count = len(payload)
        await FallingEdge(d.clk_i)
        d.command_i.value = command
        d.command_address_i.value = address
        d.command_byte_count_i.value = byte_count
        d.command_message_route_i.value = message_route
        d.command_message_code_i.value = message_code
        d.command_context_i.value = (
            0x4000 | (address & 0xFFF) if context is None else context
        )
        d.command_valid_i.value = 1
        for _ in range(timeout_cycles):
            await RisingEdge(d.clk_i)
            if int(d.command_ready_o.value):
                break
        else:
            d.command_valid_i.value = 0
            raise AssertionError(
                "command_ready_o did not assert; the requester may be "
                "blocked by flow-control credits or a full retry buffer"
            )
        await FallingEdge(d.clk_i)
        d.command_valid_i.value = 0

        for offset in range(0, len(payload), 4):
            beat = payload[offset:offset + 4]
            d.command_data_i.value = int.from_bytes(beat.ljust(4, b"\x00"), "little")
            d.command_keep_i.value = (1 << len(beat)) - 1
            d.command_data_last_i.value = offset + 4 >= len(payload)
            d.command_data_valid_i.value = 1
            for _ in range(timeout_cycles):
                await RisingEdge(d.clk_i)
                if int(d.command_data_ready_o.value):
                    break
            else:
                d.command_data_valid_i.value = 0
                d.command_data_last_i.value = 0
                raise AssertionError(
                    "command_data_ready_o did not assert while sending "
                    "command payload"
                )
            await FallingEdge(d.clk_i)
        d.command_data_valid_i.value = 0
        d.command_data_last_i.value = 0


async def capture_axis_frame(dut, prefix: str) -> bytes:
    data = bytearray()
    while True:
        await FallingEdge(dut.clk_i)
        valid = int(getattr(dut, f"{prefix}_tvalid").value)
        ready = int(getattr(dut, f"{prefix}_tready").value)
        if valid and ready:
            data.extend(word_bytes(
                int(getattr(dut, f"{prefix}_tdata").value),
                int(getattr(dut, f"{prefix}_tkeep").value),
            ))
            if int(getattr(dut, f"{prefix}_tlast").value):
                return bytes(data)


async def capture_target_payload(dut) -> bytes:
    data = bytearray()
    while True:
        await FallingEdge(dut.clk_i)
        if int(dut.target_data_valid_o.value) and int(dut.target_data_ready_i.value):
            data.extend(word_bytes(
                int(dut.target_data_o.value), int(dut.target_keep_o.value)
            ))
            if int(dut.target_data_last_o.value):
                return bytes(data)


async def capture_received_completion(dut):
    while True:
        await FallingEdge(dut.clk_i)
        if int(dut.received_completion_valid_o.value) and int(
            dut.received_completion_ready_i.value
        ):
            header = {
                "fmt": int(dut.received_header_fmt.value),
                "type": int(dut.received_header_type.value),
                "requester_id": int(dut.received_header_requester_id.value),
                "completer_id": int(dut.received_header_completer_id.value),
                "tag": int(dut.received_header_tag.value),
                "status": int(dut.received_header_status.value),
                "byte_count": int(dut.received_header_byte_count.value),
                "lower_address": int(dut.received_header_lower_address.value),
            }
            break

    payload = bytearray()
    if header["fmt"] & 0b010:
        while True:
            await FallingEdge(dut.clk_i)
            if int(dut.received_completion_data_valid_o.value) and int(
                dut.received_completion_data_ready_i.value
            ):
                payload.extend(word_bytes(
                    int(dut.received_completion_data_o.value),
                    int(dut.received_completion_keep_o.value),
                ))
                if int(dut.received_completion_data_last_o.value):
                    break
    return header, bytes(payload)


async def capture_result(dut):
    while True:
        await FallingEdge(dut.clk_i)
        if int(dut.result_valid_o.value) and int(dut.result_ready_i.value):
            return (
                int(dut.result_context_o.value),
                int(dut.result_status_o.value),
                int(dut.result_last_o.value),
            )


async def drive_completion_request(dut, request_header: int, payload: bytes):
    await FallingEdge(dut.clk_i)
    dut.completion_request_header_i.value = request_header
    dut.completion_request_status_i.value = 0
    dut.completion_request_byte_count_i.value = len(payload)
    dut.completion_request_lower_address_i.value = (
        int(dut.target_header_address.value) & 0x7F
    )
    dut.completion_request_valid_i.value = 1
    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.completion_request_ready_o.value):
            break
    await FallingEdge(dut.clk_i)
    dut.completion_request_valid_i.value = 0

    for offset in range(0, len(payload), 4):
        beat = payload[offset:offset + 4]
        dut.completion_request_data_i.value = int.from_bytes(
            beat.ljust(4, b"\x00"), "little"
        )
        dut.completion_request_keep_i.value = (1 << len(beat)) - 1
        dut.completion_request_data_last_i.value = offset + 4 >= len(payload)
        dut.completion_request_data_valid_i.value = 1
        while True:
            await RisingEdge(dut.clk_i)
            if int(dut.completion_request_data_ready_o.value):
                break
        await FallingEdge(dut.clk_i)
    dut.completion_request_data_valid_i.value = 0
    dut.completion_request_data_last_i.value = 0


@cocotb.test()
async def tx_crosses_tlp_dll_and_gen1_logical_phy_at_lane_rate(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    payload = bytes((index * 29 + 7) & 0xFF for index in range(128))
    mid_capture = cocotb.start_soon(capture_axis_frame(dut, "mid_tx_axis"))
    tx_bytes_before = int(dut.tx_payload_byte_count_o.value)
    tx_cycles_before = int(dut.tx_active_cycle_count_o.value)
    await tb.submit_command(CMD_MEM_WRITE, 0x200, payload)
    mid_tlp = await with_timeout(mid_capture, 1000, "us")
    link_frame = await tb.tx_monitor.recv_link_tlp()

    assert link_frame.user == PHY_USER_IS_TLP
    assert int.from_bytes(link_frame.data[:2], "big") == 0
    assert link_frame.data[2:-4] == mid_tlp
    assert int.from_bytes(link_frame.data[-4:], "little") == (
        zlib.crc32(link_frame.data[:-4]) & 0xFFFFFFFF
    )
    assert payload in mid_tlp
    assert link_frame.symbol_cycles == expected_symbol_cycles(
        len(link_frame.data), tb.lane_count
    )

    for _ in range(2):
        await RisingEdge(dut.clk_i)
    counted_bytes = int(dut.tx_payload_byte_count_o.value) - tx_bytes_before
    counted_cycles = int(dut.tx_active_cycle_count_o.value) - tx_cycles_before
    assert counted_bytes >= len(link_frame.data)
    assert counted_cycles >= expected_symbol_cycles(len(link_frame.data), tb.lane_count)
    decoded_rate = len(link_frame.data) * SYMBOL_CLOCK_HZ / link_frame.elapsed_cycles
    expected_capacity = 250_000_000 * tb.lane_count
    dut._log.info(
        "Gen1 x%d TX protected bytes=%d symbol_cycles=%d elapsed_cycles=%d "
        "decoded_rate=%.3f MB/s capacity=%.3f MB/s",
        tb.lane_count,
        len(link_frame.data),
        link_frame.symbol_cycles,
        link_frame.elapsed_cycles,
        decoded_rate / 1e6,
        expected_capacity / 1e6,
    )

    await tb.send_rx_frame(
        build_ack_nak(DllpType.ACK, 0), PHY_USER_IS_DLLP
    )
    assert not int(dut.command_error_valid_o.value)
    assert not int(dut.tx_error_valid_o.value)


@cocotb.test()
async def tx_back_to_back_packets_measure_endpoint_utilization(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    payloads = [
        bytes((index * (packet_index + 5) + packet_index) & 0xFF for index in range(128))
        for packet_index in range(3)
    ]
    start_cycle = tb.tx_monitor.cycle
    active_before = int(dut.tx_active_cycle_count_o.value)
    for packet_index, payload in enumerate(payloads):
        await tb.submit_command(
            CMD_MEM_WRITE, 0x400 + packet_index * 0x100, payload
        )

    frames = [await tb.tx_monitor.recv_link_tlp() for _ in payloads]
    end_cycle = tb.tx_monitor.cycle
    active_after = int(dut.tx_active_cycle_count_o.value)
    total_protected_bytes = 0
    ideal_active_cycles = 0
    for sequence, (frame, payload) in enumerate(zip(frames, payloads)):
        assert int.from_bytes(frame.data[:2], "big") == sequence
        decoded = Tlp.unpack(frame.data[2:-4])
        assert decoded.fmt_type == TlpType.MEM_WRITE
        assert bytes(decoded.data) == payload
        expected_cycles = expected_symbol_cycles(len(frame.data), tb.lane_count)
        assert frame.symbol_cycles == expected_cycles
        total_protected_bytes += len(frame.data)
        ideal_active_cycles += expected_cycles

    elapsed_cycles = max(1, end_cycle - start_cycle)
    measured_active_cycles = active_after - active_before
    assert measured_active_cycles >= ideal_active_cycles
    utilization = ideal_active_cycles / elapsed_cycles
    decoded_rate = total_protected_bytes * SYMBOL_CLOCK_HZ / elapsed_cycles
    dut._log.info(
        "Gen1 x%d burst packets=%d protected_bytes=%d active_cycles=%d "
        "elapsed_cycles=%d utilization=%.2f%% decoded_rate=%.3f MB/s",
        tb.lane_count,
        len(frames),
        total_protected_bytes,
        measured_active_cycles,
        elapsed_cycles,
        utilization * 100.0,
        decoded_rate / 1e6,
    )

    for sequence in range(len(frames)):
        await tb.send_rx_frame(
            build_ack_nak(DllpType.ACK, sequence), PHY_USER_IS_DLLP
        )


@cocotb.test()
async def rx_crosses_gen1_logical_phy_dll_and_tlp_at_lane_rate(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    payload = bytes((index * 17 + 3) & 0xFF for index in range(128))
    packet = Tlp()
    packet.fmt_type = TlpType.MEM_WRITE
    packet.set_addr_be_data(0x300, payload)
    packet.requester_id = PcieId.from_int(0x1234)
    packet.tag = 0x5A
    raw_tlp = bytes(packet.pack())
    protected = add_sequence_and_lcrc(0, raw_tlp)

    dut.target_request_ready_i.value = 0
    dut.target_data_ready_i.value = 0
    mid_capture = cocotb.start_soon(capture_axis_frame(dut, "mid_rx_axis"))
    rx_bytes_before = int(dut.rx_payload_byte_count_o.value)
    rx_cycles_before = int(dut.rx_active_cycle_count_o.value)
    await tb.send_rx_frame(protected, PHY_USER_IS_TLP)

    await tb.wait_target_request(
        protected, raw_tlp, context="routing the decoded Memory Write"
    )
    assert int(dut.target_memory_o.value)
    assert int(dut.target_write_o.value)
    assert int(dut.target_bar_hit_o.value)
    assert int(dut.target_header_requester_id.value) == 0x1234
    assert int(dut.target_header_tag.value) == 0x5A
    assert int(dut.target_header_address.value) == 0x300

    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0
    target_capture = cocotb.start_soon(capture_target_payload(dut))
    dut.target_data_ready_i.value = 1
    assert await with_timeout(mid_capture, 1000, "us") == raw_tlp
    assert await with_timeout(target_capture, 1000, "us") == payload
    ack = await tb.tx_monitor.recv_dllp(DllpType.ACK)
    assert ack.seq == 0

    for _ in range(2):
        await RisingEdge(dut.clk_i)
    counted_bytes = int(dut.rx_payload_byte_count_o.value) - rx_bytes_before
    counted_cycles = int(dut.rx_active_cycle_count_o.value) - rx_cycles_before
    assert counted_bytes == len(protected)
    assert counted_cycles == expected_symbol_cycles(len(protected), tb.lane_count)
    assert not int(dut.rx_code_error_o.value)
    assert not int(dut.rx_disparity_error_o.value)
    assert not int(dut.malformed_o.value)
    assert not int(dut.rx_ecrc_error_o.value)
    dut._log.info(
        "Gen1 x%d RX protected bytes=%d active_cycles=%d decoded_capacity=%.3f MB/s",
        tb.lane_count,
        counted_bytes,
        counted_cycles,
        (250_000_000 * tb.lane_count) / 1e6,
    )


@cocotb.test()
async def tx_4dw_memory_write_mps_segmentation_preserves_data(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    base_address = 0x1_0000_0100
    payload = bytes((index * 11 + 9) & 0xFF for index in range(192))
    await tb.submit_command(CMD_MEM_WRITE, base_address, payload)
    frames = [await tb.tx_monitor.recv_link_tlp() for _ in range(2)]

    reconstructed = bytearray()
    for sequence, frame in enumerate(frames):
        assert int.from_bytes(frame.data[:2], "big") == sequence
        assert int.from_bytes(frame.data[-4:], "little") == (
            zlib.crc32(frame.data[:-4]) & 0xFFFFFFFF
        )
        tlp = Tlp.unpack(frame.data[2:-4])
        assert tlp.fmt_type == TlpType.MEM_WRITE_64
        assert tlp.address == base_address + sequence * 128
        assert tlp.length == (128 if sequence == 0 else 64) // 4
        reconstructed.extend(tlp.data)
    assert bytes(reconstructed) == payload

    await tb.send_rx_frame(
        build_ack_nak(DllpType.ACK, len(frames) - 1), PHY_USER_IS_DLLP
    )


@cocotb.test()
async def tx_unaligned_and_4k_split_memory_writes_preserve_valid_bytes(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    unaligned_payload = bytes.fromhex("10203040506070")
    await tb.submit_command(CMD_MEM_WRITE, 0x81, unaligned_payload)
    unaligned_frame = await tb.tx_monitor.recv_link_tlp()
    unaligned = Tlp.unpack(unaligned_frame.data[2:-4])
    assert unaligned.fmt_type == TlpType.MEM_WRITE
    assert unaligned.address == 0x80
    assert unaligned.first_be == 0xE
    assert unaligned.last_be == 0xF
    assert bytes(unaligned.data[1:]) == unaligned_payload
    await tb.send_rx_frame(build_ack_nak(DllpType.ACK, 0), PHY_USER_IS_DLLP)

    boundary_payload = bytes.fromhex("8182838485868788")
    await tb.submit_command(CMD_MEM_WRITE, 0xFFC, boundary_payload)
    boundary_frames = [await tb.tx_monitor.recv_link_tlp() for _ in range(2)]
    first = Tlp.unpack(boundary_frames[0].data[2:-4])
    second = Tlp.unpack(boundary_frames[1].data[2:-4])
    assert [int.from_bytes(frame.data[:2], "big") for frame in boundary_frames] == [1, 2]
    assert first.address == 0xFFC and bytes(first.data) == boundary_payload[:4]
    assert second.address == 0x1000 and bytes(second.data) == boundary_payload[4:]
    await tb.send_rx_frame(build_ack_nak(DllpType.ACK, 2), PHY_USER_IS_DLLP)


@cocotb.test()
async def tx_memory_read_and_rx_completion_return_application_data(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    address = 0x600
    context = 0x1A2B
    expected_data = bytes((index * 7 + 0x31) & 0xFF for index in range(16))
    mid_capture = cocotb.start_soon(capture_axis_frame(dut, "mid_tx_axis"))
    await tb.submit_command(
        CMD_MEM_READ, address, byte_count=len(expected_data), context=context
    )
    raw_request = await with_timeout(mid_capture, 1000, "us")
    request_frame = await tb.tx_monitor.recv_link_tlp()
    request = Tlp.unpack(raw_request)
    assert request.fmt_type == TlpType.MEM_READ
    assert request.address == address
    assert request.get_be_byte_count() == len(expected_data)
    assert request_frame.data[2:-4] == raw_request
    assert int(dut.outstanding_o.value) == 1

    await tb.send_rx_frame(build_ack_nak(DllpType.ACK, 0), PHY_USER_IS_DLLP)

    completion = Tlp.create_completion_data_for_tlp(
        request, PcieId.from_int(0)
    )
    completion.byte_count = len(expected_data)
    completion.lower_address = address & 0x7F
    completion.set_data(expected_data)
    raw_completion = bytes(completion.pack())
    completion_capture = cocotb.start_soon(capture_received_completion(dut))
    result_capture = cocotb.start_soon(capture_result(dut))
    await tb.send_rx_frame(
        add_sequence_and_lcrc(0, raw_completion), PHY_USER_IS_TLP
    )

    header, received_data = await with_timeout(completion_capture, 1000, "us")
    result = await with_timeout(result_capture, 1000, "us")
    assert header["requester_id"] == int(request.requester_id)
    assert header["tag"] == request.tag
    assert header["status"] == 0
    assert header["byte_count"] == len(expected_data)
    assert received_data == expected_data
    assert result == (context, 0, 1)
    assert int(dut.outstanding_o.value) == 0
    ack = await tb.tx_monitor.recv_dllp(DllpType.ACK)
    assert ack.seq == 0


@cocotb.test()
async def multiple_outstanding_reads_accept_out_of_order_completion_data(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    requests = []
    for address, context in ((0xA00, 0x1111), (0xB00, 0x2222)):
        await tb.submit_command(CMD_MEM_READ, address, byte_count=8, context=context)
        frame = await tb.tx_monitor.recv_link_tlp()
        requests.append(Tlp.unpack(frame.data[2:-4]))
    assert requests[0].tag != requests[1].tag
    assert int(dut.outstanding_o.value) == 2
    await tb.send_rx_frame(build_ack_nak(DllpType.ACK, 1), PHY_USER_IS_DLLP)

    for rx_sequence, request_index in enumerate((1, 0)):
        request = requests[request_index]
        context = 0x2222 if request_index else 0x1111
        payload = bytes(
            (request_index * 0x40 + byte_index) & 0xFF
            for byte_index in range(8)
        )
        completion = Tlp.create_completion_data_for_tlp(
            request, PcieId.from_int(0)
        )
        completion.byte_count = len(payload)
        completion.lower_address = request.address & 0x7F
        completion.set_data(payload)
        completion_capture = cocotb.start_soon(capture_received_completion(dut))
        result_capture = cocotb.start_soon(capture_result(dut))
        await tb.send_rx_frame(
            add_sequence_and_lcrc(rx_sequence, bytes(completion.pack())),
            PHY_USER_IS_TLP,
        )
        header, received_data = await with_timeout(completion_capture, 1000, "us")
        assert header["tag"] == request.tag
        assert received_data == payload
        assert await with_timeout(result_capture, 1000, "us") == (context, 0, 1)
        ack = await tb.tx_monitor.recv_dllp(DllpType.ACK)
        assert ack.seq == rx_sequence
    assert int(dut.outstanding_o.value) == 0


@cocotb.test()
async def rx_memory_read_and_tx_completion_cross_every_layer(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    address = 0x700
    completion_data = bytes((index * 13 + 5) & 0xFF for index in range(16))
    request = Tlp()
    request.fmt_type = TlpType.MEM_READ
    request.set_addr_be(address, len(completion_data))
    request.requester_id = PcieId.from_int(0x1234)
    request.tag = 0x4D
    raw_request = bytes(request.pack())

    dut.target_request_ready_i.value = 0
    protected_request = add_sequence_and_lcrc(0, raw_request)
    await tb.send_rx_frame(protected_request, PHY_USER_IS_TLP)
    await tb.wait_target_request(
        protected_request, raw_request, context="routing Memory Read"
    )
    assert int(dut.target_memory_o.value)
    assert int(dut.target_read_o.value)
    assert not int(dut.target_write_o.value)
    assert int(dut.target_header_requester_id.value) == 0x1234
    assert int(dut.target_header_tag.value) == 0x4D
    request_header = int(dut.target_request_header_o.value)
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0

    request_ack = await tb.tx_monitor.recv_dllp(DllpType.ACK)
    assert request_ack.seq == 0
    await drive_completion_request(dut, request_header, completion_data)
    completion_frame = await tb.tx_monitor.recv_link_tlp()
    assert int.from_bytes(completion_frame.data[:2], "big") == 0
    completion = Tlp.unpack(completion_frame.data[2:-4])
    assert completion.fmt_type == TlpType.CPL_DATA
    assert int(completion.requester_id) == 0x1234
    assert completion.tag == 0x4D
    assert completion.status == 0
    assert completion.byte_count == len(completion_data)
    assert bytes(completion.data) == completion_data
    await tb.send_rx_frame(build_ack_nak(DllpType.ACK, 0), PHY_USER_IS_DLLP)


@cocotb.test()
async def messages_and_messages_with_data_cross_tx_and_rx(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    tx_cases = [
        (
            route,
            0x7E if route == 5 else 0x30 + route,
            0x0000000012345000 + route,
            bytes.fromhex("1122334455667788") if route == 5 else b"",
        )
        for route in range(6)
    ]
    # RETRY_TLP_SIZE is three in the endpoint fixture.  Retire each full batch
    # with a cumulative ACK before submitting more traffic; otherwise the
    # fourth command correctly remains backpressured by the retry buffer.
    for batch_start in range(0, len(tx_cases), 3):
        batch = tx_cases[batch_start:batch_start + 3]
        for route, code, route_data, payload in batch:
            await tb.submit_command(
                CMD_MSG_DATA if payload else CMD_MSG,
                route_data,
                payload,
                byte_count=len(payload),
                message_route=route,
                message_code=code,
            )

        batch_frames = [await tb.tx_monitor.recv_link_tlp() for _ in batch]
        for batch_offset, (frame, expected) in enumerate(zip(batch_frames, batch)):
            sequence = batch_start + batch_offset
            route, code, route_data, payload = expected
            assert int.from_bytes(frame.data[:2], "big") == sequence
            message = parse_message_tlp(frame.data[2:-4])
            assert message.route == route
            assert message.code == code
            assert message.route_data == route_data
            assert message.payload == payload

        await tb.send_rx_frame(
            build_ack_nak(DllpType.ACK, batch_start + len(batch) - 1),
            PHY_USER_IS_DLLP,
        )

    for sequence, route in enumerate(range(6)):
        payload = bytes.fromhex("a1b2c3d4e5f60718") if route == 5 else b""
        route_data = 0x0102030405060708 + route
        raw_message = build_message_tlp(
            route=route,
            code=0x7F if payload else 0x20 + route,
            requester_id=0x1200 + route,
            tag=0,
            route_data=route_data,
            payload=payload,
        )
        dut.target_request_ready_i.value = 0
        dut.target_data_ready_i.value = 0
        mid_capture = cocotb.start_soon(capture_axis_frame(dut, "mid_rx_axis"))
        target_capture = (
            cocotb.start_soon(capture_target_payload(dut)) if payload else None
        )
        protected_message = add_sequence_and_lcrc(sequence, raw_message)
        await tb.send_rx_frame(protected_message, PHY_USER_IS_TLP)
        await tb.wait_target_request(
            protected_message, raw_message, context="routing Message TLP"
        )
        assert int(dut.target_message_o.value)
        assert not int(dut.target_unsupported_o.value)
        assert int(dut.target_message_route_o.value) == route
        assert int(dut.target_message_code_o.value) == (0x7F if payload else 0x20 + route)
        assert int(dut.target_message_data_o.value) == route_data
        assert int(dut.target_header_requester_id.value) == 0x1200 + route
        assert int(dut.target_header_tag.value) == 0
        dut.target_request_ready_i.value = 1
        await RisingEdge(dut.clk_i)
        dut.target_request_ready_i.value = 0
        dut.target_data_ready_i.value = 1
        assert await with_timeout(mid_capture, 1000, "us") == raw_message
        if payload:
            assert await with_timeout(target_capture, 1000, "us") == payload
        ack = await tb.tx_monitor.recv_dllp(DllpType.ACK)
        assert ack.seq == sequence


@cocotb.test()
async def mixed_posted_nonposted_and_message_traffic_preserves_order(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    write_payload = bytes.fromhex("00112233445566778899aabbccddeeff")
    await tb.submit_command(CMD_MEM_WRITE, 0x800, write_payload)
    await tb.submit_command(CMD_MEM_READ, 0x900, byte_count=8, context=0x2B3C)
    await tb.submit_command(
        CMD_MSG,
        0,
        byte_count=0,
        message_route=0,
        message_code=0x31,
    )

    frames = [await tb.tx_monitor.recv_link_tlp() for _ in range(3)]
    for sequence, frame in enumerate(frames):
        assert int.from_bytes(frame.data[:2], "big") == sequence
    write = Tlp.unpack(frames[0].data[2:-4])
    read = Tlp.unpack(frames[1].data[2:-4])
    message = parse_message_tlp(frames[2].data[2:-4])
    assert write.fmt_type == TlpType.MEM_WRITE
    assert bytes(write.data) == write_payload
    assert read.fmt_type == TlpType.MEM_READ
    assert read.address == 0x900
    assert message.route == 0 and message.code == 0x31
    await tb.send_rx_frame(build_ack_nak(DllpType.ACK, 2), PHY_USER_IS_DLLP)

    returned_data = bytes.fromhex("d0d1d2d3d4d5d6d7")
    completion = Tlp.create_completion_data_for_tlp(read, PcieId.from_int(0))
    completion.byte_count = len(returned_data)
    completion.lower_address = 0x900 & 0x7F
    completion.set_data(returned_data)
    completion_capture = cocotb.start_soon(capture_received_completion(dut))
    result_capture = cocotb.start_soon(capture_result(dut))
    await tb.send_rx_frame(
        add_sequence_and_lcrc(0, bytes(completion.pack())), PHY_USER_IS_TLP
    )
    _, received_data = await with_timeout(completion_capture, 1000, "us")
    assert received_data == returned_data
    assert await with_timeout(result_capture, 1000, "us") == (0x2B3C, 0, 1)
    assert int(dut.outstanding_o.value) == 0
    completion_ack = await tb.tx_monitor.recv_dllp(DllpType.ACK)
    assert completion_ack.seq == 0


@cocotb.test()
async def rx_illegal_8b10b_symbol_is_reported_and_packet_is_rejected(dut):
    tb = LineRateTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    packet = Tlp()
    packet.fmt_type = TlpType.MEM_WRITE
    packet.set_addr_be_data(0x80, bytes.fromhex("1122334455667788"))
    packet.requester_id = PcieId.from_int(1)
    protected = add_sequence_and_lcrc(0, bytes(packet.pack()))
    groups = tb.rx_encoder.encode_frame(protected)
    corrupt_index = min(2, len(groups) - 1)
    original = groups[corrupt_index]
    # 10'b0000000000 is not a legal data symbol. Only lane zero is replaced;
    # the remaining x4 lanes retain their correctly generated symbols.
    corrupted_data = original.data & ~0x3FF
    groups[corrupt_index] = SymbolGroup(
        corrupted_data, original.keep, original.sop, original.eop
    )
    await tb.send_rx_groups(groups, PHY_USER_IS_TLP)

    for _ in range(32):
        await RisingEdge(dut.clk_i)
        if int(dut.rx_code_error_o.value):
            break
    assert int(dut.rx_code_error_o.value), "illegal 8b/10b symbol was not reported"
    nak = await tb.tx_monitor.recv_dllp(DllpType.NAK)
    assert nak.seq == 0xFFF
    assert not int(dut.target_request_valid_o.value)

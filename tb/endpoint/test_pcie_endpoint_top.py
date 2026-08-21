''' 
Instructions to run the TLP-DLL- Phy facing Axi Stream.
fusesoc library add pcie-endpoint-controller ./
fusesoc run --target=sim fusesoc:pcie:tb_endpoint_protocol:1.0.0
'''

import zlib

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, with_timeout
from cocotbext.axi import AxiStreamBus, AxiStreamFrame, AxiStreamSink, AxiStreamSource
from cocotbext.pcie.core.dllp import Dllp, DllpType, FcScale
from cocotbext.pcie.core.tlp import Tlp, TlpType


PHY_USER_IS_DLLP = 1
PHY_USER_IS_TLP = 2
CMD_MEM_READ = 0
CMD_MEM_WRITE = 1


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


# Base 2.1 SS2.6.1 Table 2-37 p.137-138, Endpoint rows, at the bench MPS of 128 bytes
# (FC unit = 16 bytes, from the table's own 1024 -> 040h example): PH 1, PD 128/16 = 8,
# NPH 1, NPD 1 (no AtomicOp support), CPLH/CPLD "infinite FC units - initial credit
# value of all 0s".  Footnote 33 p.137: zero "is interpreted as infinite by the
# Transmitter, which will, therefore, never throttle" -- so this profile cannot starve
# completions; its power is NPH = 1, one non-posted request outstanding at a time.
MIN_CREDIT_EP = {
    DllpType.INIT_FC1_P:   (1, 8),
    DllpType.INIT_FC2_P:   (1, 8),
    DllpType.INIT_FC1_NP:  (1, 1),
    DllpType.INIT_FC2_NP:  (1, 1),
    DllpType.INIT_FC1_CPL: (0, 0),
    DllpType.INIT_FC2_CPL: (0, 0),
}


def build_ack_nak(dllp_type: DllpType, sequence: int) -> bytes:
    packet = Dllp()
    packet.type = dllp_type
    packet.seq = sequence & 0xFFF
    payload = bytes(packet.pack())
    return payload + calculate_dllp_crc(payload).to_bytes(2, "little")


def add_sequence_and_lcrc(sequence: int, tlp: bytes) -> bytes:
    body = (sequence & 0xFFF).to_bytes(2, "big") + bytes(tlp)
    return body + (zlib.crc32(body) & 0xFFFFFFFF).to_bytes(4, "little")


async def send_axis(source: AxiStreamSource, data: bytes, tuser: int):
    frame = AxiStreamFrame(data)
    frame.tuser = tuser
    await with_timeout(source.send(frame), 500, "us")


async def wait_high(clock, signal, cycles=4000):
    for _ in range(cycles):
        await RisingEdge(clock)
        if signal.value.is_resolvable and int(signal.value):
            return
    raise AssertionError(f"{signal._name} did not assert")


def word_bytes(data: int, keep: int) -> bytes:
    return bytes((data >> (8 * lane)) & 0xFF for lane in range(4) if keep & (1 << lane))


async def capture_mid_frame(dut, direction: str) -> bytes:
    if direction == "tx":
        data = dut.mid_tx_axis_tdata
        keep = dut.mid_tx_axis_tkeep
        valid = dut.mid_tx_axis_tvalid
        ready = dut.mid_tx_axis_tready
        last = dut.mid_tx_axis_tlast
    else:
        data = dut.mid_rx_axis_tdata
        keep = dut.mid_rx_axis_tkeep
        valid = dut.mid_rx_axis_tvalid
        ready = dut.mid_rx_axis_tready
        last = dut.mid_rx_axis_tlast

    frame = bytearray()
    while True:
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(valid.value) and int(ready.value):
            frame.extend(word_bytes(int(data.value), int(keep.value)))
            if int(last.value):
                return bytes(frame)


async def capture_target_payload(dut) -> bytes:
    payload = bytearray()
    while True:
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.target_data_valid_o.value) and int(dut.target_data_ready_i.value):
            payload.extend(
                word_bytes(int(dut.target_data_o.value), int(dut.target_keep_o.value))
            )
            if int(dut.target_data_last_o.value):
                return bytes(payload)


async def receive_link_tlp(sink: AxiStreamSink) -> bytes:
    while True:
        frame = await with_timeout(sink.recv(), 1000, "us")
        data = bytes(frame.tdata)
        if len(data) != 6:
            return data


async def receive_dllp_type(sink: AxiStreamSink, dllp_type: DllpType):
    while True:
        frame = await with_timeout(sink.recv(), 1000, "us")
        data = bytes(frame.tdata)
        if len(data) != 6:
            continue
        payload = data[:4]
        if data[4:] != calculate_dllp_crc(payload).to_bytes(2, "little"):
            continue
        decoded = Dllp().unpack(payload)
        if decoded.type == dllp_type:
            return decoded


async def initialize_flow_control(dut, phy_source, credit_profile=None):
    """The seven-DLLP InitFC exchange; credit_profile maps DllpType -> (hdr_fc, data_fc)."""
    sequence = (
        DllpType.INIT_FC1_P,
        DllpType.INIT_FC1_NP,
        DllpType.INIT_FC1_CPL,
        DllpType.INIT_FC2_P,
        DllpType.INIT_FC2_P,
        DllpType.INIT_FC2_NP,
        DllpType.INIT_FC2_CPL,
    )
    profile = credit_profile or {dllp_type: (32, 256) for dllp_type in sequence}
    for dllp_type in sequence:
        hdr_fc, data_fc = profile[dllp_type]
        await send_axis(phy_source, build_fc_dllp(dllp_type, hdr_fc, data_fc),
                        PHY_USER_IS_DLLP)
        for _ in range(24):
            await RisingEdge(dut.clk_i)
    await wait_high(dut.clk_i, dut.fc_initialized_o)
    assert int(dut.fc_ph_o.value) == profile[DllpType.INIT_FC2_P][0]
    assert int(dut.fc_nph_o.value) == profile[DllpType.INIT_FC2_NP][0]
    assert int(dut.fc_cplh_o.value) == profile[DllpType.INIT_FC2_CPL][0]


class EndpointTB:
    def __init__(self, dut):
        self.dut = dut
        cocotb.start_soon(Clock(dut.clk_i, 8, units="ns").start())
        self.phy_source = AxiStreamSource(
            AxiStreamBus.from_prefix(dut, "s_phy_axis"), dut.clk_i, dut.rst_i
        )
        self.phy_sink = AxiStreamSink(
            AxiStreamBus.from_prefix(dut, "m_phy_axis"), dut.clk_i, dut.rst_i
        )

    async def reset(self):
        d = self.dut
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
        for _ in range(8):
            await RisingEdge(d.clk_i)
        d.rst_i.value = 0
        d.phy_link_up_i.value = 1
        d.idle_valid_i.value = 1
        d.transmit_enable_i.value = 1
        for _ in range(8):
            await RisingEdge(d.clk_i)

    async def initialize_flow_control(self, credit_profile=None):
        await initialize_flow_control(self.dut, self.phy_source, credit_profile)

    async def submit_command(self, command: int, address: int, byte_count: int,
                             payload: bytes = b"", context: int = 0x1234):
        d = self.dut
        d.command_i.value = command
        d.command_address_i.value = address
        d.command_byte_count_i.value = byte_count
        d.command_context_i.value = context
        d.command_valid_i.value = 1
        await wait_high(d.clk_i, d.command_ready_o)
        await RisingEdge(d.clk_i)
        d.command_valid_i.value = 0

        for offset in range(0, len(payload), 4):
            beat = payload[offset:offset + 4]
            d.command_data_i.value = int.from_bytes(beat.ljust(4, b"\x00"), "little")
            d.command_keep_i.value = (1 << len(beat)) - 1
            d.command_data_last_i.value = offset + 4 >= len(payload)
            d.command_data_valid_i.value = 1
            await wait_high(d.clk_i, d.command_data_ready_o)
            await RisingEdge(d.clk_i)
        d.command_data_valid_i.value = 0
        d.command_data_last_i.value = 0


@cocotb.test()
async def application_input_reaches_data_link_output(dut):
    """Application command -> TLP boundary -> sequenced/LCRC link packet."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    mid_capture = cocotb.start_soon(capture_mid_frame(dut, "tx"))
    payload = bytes.fromhex("4433221188776655")
    await tb.submit_command(CMD_MEM_WRITE, 0x40, len(payload), payload)
    mid_tlp = await with_timeout(mid_capture, 500, "us")
    link_packet = await receive_link_tlp(tb.phy_sink)

    assert link_packet[2:-4] == mid_tlp
    assert int.from_bytes(link_packet[-4:], "little") == (
        zlib.crc32(link_packet[:-4]) & 0xFFFFFFFF
    )
    assert payload in mid_tlp
    assert not int(dut.command_error_valid_o.value)


@cocotb.test()
async def physical_input_reaches_target_through_mid_layer(dut):
    """Valid link packet -> stripped TLP boundary -> BAR target interface."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    payload = bytes.fromhex("0102030405060708")
    packet = Tlp()
    packet.fmt_type = TlpType.MEM_WRITE
    packet.set_addr_be_data(0x80, payload)
    packet.requester_id = 1
    packet.tag = 0x22
    raw_tlp = bytes(packet.pack())
    link_packet = add_sequence_and_lcrc(0, raw_tlp)

    dut.target_request_ready_i.value = 0
    mid_capture = cocotb.start_soon(capture_mid_frame(dut, "rx"))
    send_task = cocotb.start_soon(
        send_axis(tb.phy_source, link_packet, PHY_USER_IS_TLP)
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)
    saved_header = int(dut.target_request_header_o.value)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        assert int(dut.target_request_valid_o.value)
        assert int(dut.target_request_header_o.value) == saved_header

    assert int(dut.target_memory_o.value)
    assert int(dut.target_write_o.value)
    assert int(dut.target_bar_hit_o.value)
    assert int(dut.target_offset_o.value) == 0x80
    target_payload = cocotb.start_soon(capture_target_payload(dut))
    dut.target_request_ready_i.value = 1
    await with_timeout(send_task, 500, "us")
    stripped_tlp = await with_timeout(mid_capture, 500, "us")
    assert stripped_tlp == raw_tlp
    assert await with_timeout(target_payload, 500, "us") == payload


@cocotb.test()
async def data_link_nak_replays_transaction_layer_packet(dut):
    """The DLL retry path replays the exact TLP produced at the layer boundary."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    mid_capture = cocotb.start_soon(capture_mid_frame(dut, "tx"))
    await tb.submit_command(CMD_MEM_READ, 0x100, 16, context=0x55AA)
    mid_tlp = await with_timeout(mid_capture, 500, "us")
    first = await receive_link_tlp(tb.phy_sink)
    sequence = int.from_bytes(first[:2], "big") & 0xFFF
    assert first[2:-4] == mid_tlp

    await send_axis(
        tb.phy_source,
        build_ack_nak(DllpType.NAK, (sequence - 1) & 0xFFF),
        PHY_USER_IS_DLLP,
    )
    replay = await receive_link_tlp(tb.phy_sink)
    assert replay == first

    await send_axis(
        tb.phy_source,
        build_ack_nak(DllpType.ACK, sequence),
        PHY_USER_IS_DLLP,
    )


@cocotb.test()
async def corrupted_link_input_is_rejected_with_nak(dut):
    """A bad LCRC is stopped in the DLL and never reaches the TLP target."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    packet = Tlp()
    packet.fmt_type = TlpType.MEM_WRITE
    packet.set_addr_be_data(0x20, bytes.fromhex("a5a5a5a5"))
    packet.requester_id = 1
    packet.tag = 3
    corrupt = bytearray(add_sequence_and_lcrc(0, bytes(packet.pack())))
    corrupt[-1] ^= 1
    await send_axis(tb.phy_source, bytes(corrupt), PHY_USER_IS_TLP)

    nak = await receive_dllp_type(tb.phy_sink, DllpType.NAK)
    assert nak.seq == 0xFFF
    for _ in range(32):
        await RisingEdge(dut.clk_i)
        assert not int(dut.target_request_valid_o.value)


@cocotb.test()
async def flow_control_blocks_and_releases_mid_layer(dut):
    """An exhausted posted credit blocks VC0 until an UpdateFC DLLP arrives."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    await send_axis(
        tb.phy_source,
        build_fc_dllp(DllpType.UPDATE_FC_P, hdr_fc=0, data_fc=0),
        PHY_USER_IS_DLLP,
    )
    await wait_high(dut.clk_i, dut.fc_update_valid_o)

    mid_capture = cocotb.start_soon(capture_mid_frame(dut, "tx"))
    await tb.submit_command(
        CMD_MEM_WRITE, 0x120, 4, payload=bytes.fromhex("dec0adde")
    )
    await wait_high(dut.clk_i, dut.tx_fc_blocked_o)
    assert not mid_capture.done()

    await send_axis(
        tb.phy_source,
        build_fc_dllp(DllpType.UPDATE_FC_P, hdr_fc=32, data_fc=256),
        PHY_USER_IS_DLLP,
    )
    mid_tlp = await with_timeout(mid_capture, 500, "us")
    link_packet = await receive_link_tlp(tb.phy_sink)
    assert link_packet[2:-4] == mid_tlp

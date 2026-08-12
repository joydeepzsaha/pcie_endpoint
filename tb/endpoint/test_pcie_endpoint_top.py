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
from cocotbext.pcie.core.tlp import CplStatus, Tlp, TlpType
from cocotbext.pcie.core.utils import PcieId


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
        if int(dut.target_data_valid_o.value) and int(dut.target_data_ready_i.value):
            payload.extend(
                word_bytes(int(dut.target_data_o.value), int(dut.target_keep_o.value))
            )
            if int(dut.target_data_last_o.value):
                return bytes(payload)


async def receive_link_tlp(sink: AxiStreamSink) -> bytes:
    return bytes((await receive_link_frame(sink)).tdata)


async def receive_link_frame(sink: AxiStreamSink) -> AxiStreamFrame:
    while True:
        frame = await with_timeout(sink.recv(), 1000, "us")
        data = bytes(frame.tdata)
        if len(data) != 6:
            return frame


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
        d.codec_8b_data_i.value = 0
        d.codec_8b_disp_i.value = 0
        d.codec_decode_data_i.value = 0
        d.codec_decode_disp_i.value = 0
        d.scrambler_disable_i.value = 0
        d.scrambler_lfsr_i.value = 0xFFFF
        for _ in range(8):
            await RisingEdge(d.clk_i)
        d.rst_i.value = 0
        d.phy_link_up_i.value = 1
        d.idle_valid_i.value = 1
        d.transmit_enable_i.value = 1
        for _ in range(8):
            await RisingEdge(d.clk_i)

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
            await send_axis(self.phy_source, build_fc_dllp(dllp_type), PHY_USER_IS_DLLP)
            for _ in range(24):
                await RisingEdge(self.dut.clk_i)
        await wait_high(self.dut.clk_i, self.dut.fc_initialized_o)
        assert int(self.dut.fc_ph_o.value) == 32
        assert int(self.dut.fc_nph_o.value) == 32
        assert int(self.dut.fc_cplh_o.value) == 32

    async def submit_command(self, command: int, address: int, byte_count: int,
                             payload: bytes = b"", context: int = 0x1234,
                             tc: int = 0, attr: int = 0,
                             prefix: int | None = None, ecrc: bool = False):
        d = self.dut
        d.command_i.value = command
        d.command_address_i.value = address
        d.command_byte_count_i.value = byte_count
        d.command_tc_i.value = tc
        d.command_attr_i.value = attr
        d.command_context_i.value = context
        d.command_prefix_valid_i.value = prefix is not None
        d.command_prefix_i.value = 0 if prefix is None else prefix
        d.command_ecrc_enable_i.value = ecrc
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


def scrambler_step_reference(state: int) -> int:
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
async def exact_outbound_header_sequence_credit_and_classification(dut):
    """Check every generated request field plus sequence, credits, and tuser."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    initial_ph = int(dut.tx_posted_header_available.value)
    initial_pd = int(dut.tx_posted_data_available.value)
    payload = bytes.fromhex("00112233445566778899aabbccddeeff")
    await tb.submit_command(
        CMD_MEM_WRITE, 0x184, len(payload), payload,
        tc=5, attr=3, context=0xCAFE,
    )

    frame = await receive_link_frame(tb.phy_sink)
    link_packet = bytes(frame.tdata)
    assert int.from_bytes(link_packet[:2], "big") == 0
    frame_tuser = (
        frame.tuser if isinstance(frame.tuser, (list, tuple)) else [frame.tuser]
    )
    assert all(int(value) == PHY_USER_IS_TLP for value in frame_tuser)

    tlp = Tlp.unpack(link_packet[2:-4])
    assert tlp.fmt_type == TlpType.MEM_WRITE
    expected_requester_id = (
        (int(dut.cfg_bus_number_o.value) << 8)
        | (int(dut.cfg_device_number_o.value) << 3)
        | int(dut.cfg_function_number_o.value)
    )
    assert int(tlp.requester_id) == expected_requester_id
    assert tlp.address == 0x184
    assert tlp.length == 4
    assert tlp.first_be == 0xF
    assert tlp.last_be == 0xF
    assert int(tlp.tc) == 5
    assert int(tlp.attr) == 3
    assert not tlp.td
    assert not tlp.ep
    assert not tlp.th
    assert int(tlp.at) == 0
    assert bytes(tlp.data) == payload

    assert int(dut.tx_posted_header_available.value) == initial_ph - 1
    # One data credit represents up to 16 payload bytes.
    assert int(dut.tx_posted_data_available.value) == initial_pd - 1


@cocotb.test()
async def consecutive_unaligned_segmented_and_4dw_writes(dut):
    """Exercise consecutive writes, unaligned byte enables, MPS splits, and 4-DW."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    writes = [
        (0x81, bytes.fromhex("10203040506070")),
        (0x140, bytes.fromhex("a1b2c3d4")),
    ]
    for expected_sequence, (address, payload) in enumerate(writes):
        await tb.submit_command(CMD_MEM_WRITE, address, len(payload), payload)
        packet = await receive_link_tlp(tb.phy_sink)
        assert int.from_bytes(packet[:2], "big") == expected_sequence
        tlp = Tlp.unpack(packet[2:-4])
        assert tlp.address == (address & ~3)
        offset = address & 3
        assert tlp.first_be == (0xE if offset else 0xF)
        assert bytes(tlp.data)[offset:offset + len(payload)] == payload
        await send_axis(
            tb.phy_source,
            build_ack_nak(DllpType.ACK, expected_sequence),
            PHY_USER_IS_DLLP,
        )

    segmented_payload = bytes(index & 0xFF for index in range(300))
    await tb.submit_command(
        CMD_MEM_WRITE, 0x200, len(segmented_payload), segmented_payload
    )
    segments = []
    for expected_sequence in range(2, 5):
        packet = await receive_link_tlp(tb.phy_sink)
        assert int.from_bytes(packet[:2], "big") == expected_sequence
        segments.append(Tlp.unpack(packet[2:-4]))
        await send_axis(
            tb.phy_source,
            build_ack_nak(DllpType.ACK, expected_sequence),
            PHY_USER_IS_DLLP,
        )
    assert [item.length * 4 for item in segments] == [128, 128, 44]
    assert [item.address for item in segments] == [0x200, 0x280, 0x300]
    assert b"".join(bytes(item.data) for item in segments) == segmented_payload

    address_64 = 0x1_0000_0400
    payload_64 = bytes.fromhex("efbeadde78563412")
    await tb.submit_command(CMD_MEM_WRITE, address_64, len(payload_64), payload_64)
    packet = await receive_link_tlp(tb.phy_sink)
    assert int.from_bytes(packet[:2], "big") == 5
    tlp = Tlp.unpack(packet[2:-4])
    assert tlp.fmt_type == TlpType.MEM_WRITE_64
    assert tlp.address == address_64
    assert bytes(tlp.data) == payload_64


@cocotb.test()
async def outbound_prefix_and_ecrc_are_preserved(dut):
    """Check prefix placement and the ECRC produced over the unprefixed TLP."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    prefix = 0xA1B2C480
    payload = bytes.fromhex("dec0adde")
    await tb.submit_command(
        CMD_MEM_WRITE, 0x300, len(payload), payload,
        prefix=prefix, ecrc=True,
    )
    packet = await receive_link_tlp(tb.phy_sink)
    raw_tlp = packet[2:-4]
    assert raw_tlp[:4] == prefix.to_bytes(4, "little")
    assert int.from_bytes(raw_tlp[-4:], "little") == (
        zlib.crc32(raw_tlp[4:-4]) & 0xFFFFFFFF
    )


@cocotb.test()
async def existing_scrambler_and_8b10b_primitives_are_checked(dut):
    """Verify codec round trips/errors and the existing Gen1 LFSR step logic."""
    tb = EndpointTB(dut)
    await tb.reset()

    legal_codes = set()
    for disparity in (0, 1):
        for byte in range(256):
            dut.codec_8b_data_i.value = byte
            dut.codec_8b_disp_i.value = disparity
            await Timer(1, units="ps")
            code = int(dut.codec_10b_data.value)
            legal_codes.add(code)
            dut.codec_decode_data_i.value = code
            dut.codec_decode_disp_i.value = disparity
            await Timer(1, units="ps")
            assert not int(dut.codec_decode_code_error.value)
            assert not int(dut.codec_decode_disparity_error.value)
            assert int(dut.codec_decode_data.value) == byte
            assert int(dut.codec_decode_disp.value) == int(dut.codec_10b_disp.value)

    legal_k = [0x11C, 0x13C, 0x15C, 0x17C, 0x19C, 0x1BC, 0x1DC, 0x1FC,
               0x1F7, 0x1FB, 0x1FD, 0x1FE]
    for disparity in (0, 1):
        for symbol in legal_k:
            dut.codec_8b_data_i.value = symbol
            dut.codec_8b_disp_i.value = disparity
            await Timer(1, units="ps")
            code = int(dut.codec_10b_data.value)
            legal_codes.add(code)
            dut.codec_decode_data_i.value = code
            dut.codec_decode_disp_i.value = disparity
            await Timer(1, units="ps")
            assert not int(dut.codec_decode_code_error.value)
            assert not int(dut.codec_decode_disparity_error.value)
            assert int(dut.codec_decode_data.value) == symbol

    # Every 10-bit value not produced as a legal D/K symbol must be rejected,
    # or identified as a legal code with the wrong running disparity.
    for code in range(1024):
        dut.codec_decode_data_i.value = code
        dut.codec_decode_disp_i.value = 0
        await Timer(1, units="ps")
        if code not in legal_codes:
            assert int(dut.codec_decode_code_error.value)

    for state in [0, 1, 2, 3, 0x8000, 0xFFFF, 0xACE1, 0x1234, 0x5A5A]:
        dut.scrambler_disable_i.value = 0
        dut.scrambler_lfsr_i.value = state
        await Timer(1, units="ps")
        assert int(dut.scrambler_lfsr_o.value) == scrambler_step_reference(state)
        dut.scrambler_disable_i.value = 1
        await Timer(1, units="ps")
        assert int(dut.scrambler_lfsr_o.value) == state


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
    packet.requester_id = PcieId.from_int(1)
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
    ack = await receive_dllp_type(tb.phy_sink, DllpType.ACK)
    assert ack.seq == 0


@cocotb.test()
async def inbound_header_fields_payload_backpressure_and_poison(dut):
    """Check all exposed request fields and hold payload stable under backpressure."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    payload = bytes.fromhex("11223344556677")
    packet = Tlp()
    packet.fmt_type = TlpType.MEM_WRITE
    packet.set_addr_be_data(0x81, payload)
    packet.requester_id = PcieId.from_int(0x1234)
    packet.tag = 0xA5
    packet.tc = 6
    packet.attr = 3
    packet.ep = True
    packet.th = False
    packet.at = 0

    dut.target_request_ready_i.value = 0
    dut.target_data_ready_i.value = 0
    await send_axis(
        tb.phy_source,
        add_sequence_and_lcrc(0, bytes(packet.pack())),
        PHY_USER_IS_TLP,
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)

    assert int(dut.target_header_fmt.value) == 2
    assert int(dut.target_header_type.value) == 0
    assert int(dut.target_header_tc.value) == 6
    assert int(dut.target_header_attr.value) == 3
    assert int(dut.target_header_td.value) == 0
    assert int(dut.target_header_ep.value) == 1
    assert int(dut.target_header_th.value) == 0
    assert int(dut.target_header_at.value) == 0
    assert int(dut.target_header_length.value) == 2
    assert int(dut.target_header_requester_id.value) == 0x1234
    assert int(dut.target_header_tag.value) == 0xA5
    assert int(dut.target_header_first_be.value) == 0xE
    assert int(dut.target_header_last_be.value) == 0xF
    assert int(dut.target_header_address.value) == 0x80
    assert int(dut.target_header_prefix_present.value) == 0
    assert int(dut.target_memory_o.value)
    assert int(dut.target_write_o.value)
    # Poison is reported in the header; the current endpoint does not consume
    # or clear a poisoned request automatically.
    assert not int(dut.target_unsupported_o.value)

    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0
    await wait_high(dut.clk_i, dut.target_data_valid_o)
    stalled = (
        int(dut.target_data_o.value),
        int(dut.target_keep_o.value),
        int(dut.target_data_last_o.value),
    )
    for _ in range(8):
        await RisingEdge(dut.clk_i)
        assert int(dut.target_data_valid_o.value)
        assert stalled == (
            int(dut.target_data_o.value),
            int(dut.target_keep_o.value),
            int(dut.target_data_last_o.value),
        )

    target_payload = cocotb.start_soon(capture_target_payload(dut))
    dut.target_data_ready_i.value = 1
    delivered = await with_timeout(target_payload, 500, "us")
    assert delivered[1:1 + len(payload)] == payload


@cocotb.test()
async def bar_boundary_memory_disable_and_config_routing(dut):
    """Reject BAR crossing/disabled memory and route a matching Config Read."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()
    dut.target_request_ready_i.value = 0

    crossing = Tlp()
    crossing.fmt_type = TlpType.MEM_WRITE
    crossing.set_addr_be_data(0xFFC, bytes.fromhex("0001020304050607"))
    crossing.requester_id = PcieId.from_int(1)
    await send_axis(
        tb.phy_source,
        add_sequence_and_lcrc(0, bytes(crossing.pack())),
        PHY_USER_IS_TLP,
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)
    assert not int(dut.target_bar_hit_o.value)
    assert int(dut.target_unsupported_o.value)
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)

    dut.memory_enable_i.value = 0
    disabled = Tlp()
    disabled.fmt_type = TlpType.MEM_READ
    disabled.set_addr_be(0x100, 4)
    disabled.requester_id = PcieId.from_int(2)
    disabled.tag = 7
    await send_axis(
        tb.phy_source,
        add_sequence_and_lcrc(1, bytes(disabled.pack())),
        PHY_USER_IS_TLP,
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)
    assert not int(dut.target_bar_hit_o.value)
    assert int(dut.target_unsupported_o.value)
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0

    dut.memory_enable_i.value = 1
    config = Tlp()
    config.fmt_type = TlpType.CFG_READ_0
    config.set_addr_be(0x40, 4)
    config.requester_id = PcieId.from_int(3)
    config.tag = 9
    config.completer_id = PcieId.from_int(
        (int(dut.cfg_bus_number_o.value) << 8)
        | (int(dut.cfg_device_number_o.value) << 3)
        | int(dut.cfg_function_number_o.value)
    )
    await send_axis(
        tb.phy_source,
        add_sequence_and_lcrc(2, bytes(config.pack())),
        PHY_USER_IS_TLP,
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)
    assert int(dut.target_config_o.value)
    assert int(dut.target_config_hit_o.value)
    assert int(dut.target_config_offset_o.value) == 0x40
    assert int(dut.target_read_o.value)
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0
    config_read_link = await receive_link_tlp(tb.phy_sink)
    config_read_sequence = int.from_bytes(config_read_link[:2], "big") & 0xFFF
    config_read_completion = Tlp.unpack(config_read_link[2:-4])
    assert config_read_completion.fmt_type == TlpType.CPL_DATA
    assert config_read_completion.status == CplStatus.SC
    assert int(config_read_completion.requester_id) == int(config.requester_id)
    assert config_read_completion.tag == config.tag
    await send_axis(
        tb.phy_source,
        build_ack_nak(DllpType.ACK, config_read_sequence),
        PHY_USER_IS_DLLP,
    )

    config_write = Tlp()
    config_write.fmt_type = TlpType.CFG_WRITE_0
    config_write.set_addr_be_data(0x44, bytes.fromhex("78563412"))
    config_write.requester_id = PcieId.from_int(3)
    config_write.tag = 10
    config_write.completer_id = config.completer_id
    await send_axis(
        tb.phy_source,
        add_sequence_and_lcrc(3, bytes(config_write.pack())),
        PHY_USER_IS_TLP,
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)
    assert int(dut.target_config_o.value)
    assert int(dut.target_config_hit_o.value)
    assert int(dut.target_config_offset_o.value) == 0x44
    assert int(dut.target_write_o.value)
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    config_write_link = await receive_link_tlp(tb.phy_sink)
    config_write_sequence = int.from_bytes(config_write_link[:2], "big") & 0xFFF
    config_write_completion = Tlp.unpack(config_write_link[2:-4])
    assert config_write_completion.fmt_type == TlpType.CPL
    assert config_write_completion.status == CplStatus.SC
    assert int(config_write_completion.requester_id) == int(config_write.requester_id)
    assert config_write_completion.tag == config_write.tag
    await send_axis(
        tb.phy_source,
        build_ack_nak(DllpType.ACK, config_write_sequence),
        PHY_USER_IS_DLLP,
    )


@cocotb.test()
async def completion_generation_and_multiple_outstanding_requests(dut):
    """Generate a target completion and retain two independent requester tags."""
    tb = EndpointTB(dut)
    await tb.reset()
    await tb.initialize_flow_control()

    request = Tlp()
    request.fmt_type = TlpType.MEM_READ
    request.set_addr_be(0x100, 4)
    request.requester_id = PcieId.from_int(0x1234)
    request.tag = 0x44
    dut.target_request_ready_i.value = 0
    await send_axis(
        tb.phy_source,
        add_sequence_and_lcrc(0, bytes(request.pack())),
        PHY_USER_IS_TLP,
    )
    await wait_high(dut.clk_i, dut.target_request_valid_o)
    request_header = int(dut.target_request_header_o.value)
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0

    dut.completion_request_header_i.value = request_header
    dut.completion_request_status_i.value = 0
    dut.completion_request_byte_count_i.value = 4
    dut.completion_request_lower_address_i.value = request.get_lower_address()
    dut.completion_request_valid_i.value = 1
    await wait_high(dut.clk_i, dut.completion_request_ready_o)
    await RisingEdge(dut.clk_i)
    dut.completion_request_valid_i.value = 0

    dut.completion_request_data_i.value = 0x44332211
    dut.completion_request_keep_i.value = 0xF
    dut.completion_request_data_last_i.value = 1
    dut.completion_request_data_valid_i.value = 1
    await wait_high(dut.clk_i, dut.completion_request_data_ready_o)
    await RisingEdge(dut.clk_i)
    dut.completion_request_data_valid_i.value = 0
    dut.completion_request_data_last_i.value = 0

    completion_link_packet = await receive_link_tlp(tb.phy_sink)
    completion = Tlp.unpack(completion_link_packet[2:-4])
    assert completion.fmt_type == TlpType.CPL_DATA
    assert int(completion.requester_id) == 0x1234
    assert completion.tag == 0x44
    assert completion.byte_count == 4
    assert completion.lower_address == request.get_lower_address()
    assert bytes(completion.data) == bytes.fromhex("11223344")

    await tb.submit_command(CMD_MEM_READ, 0x400, 4, context=0x1111)
    first = Tlp.unpack((await receive_link_tlp(tb.phy_sink))[2:-4])
    await tb.submit_command(CMD_MEM_READ, 0x500, 4, context=0x2222)
    second = Tlp.unpack((await receive_link_tlp(tb.phy_sink))[2:-4])
    assert first.tag != second.tag
    assert int(dut.outstanding_o.value) == 2


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
    packet.requester_id = PcieId.from_int(1)
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

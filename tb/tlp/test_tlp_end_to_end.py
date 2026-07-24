import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


CMD_MEM_READ = 0
CMD_MEM_WRITE = 1
CMD_CFG_READ0 = 2
CMD_CFG_WRITE0 = 3
CMD_IO_READ = 4
CMD_IO_WRITE = 5

FMT_3DW_ND = 0
FMT_4DW_ND = 1
FMT_3DW_D = 2
FMT_4DW_D = 3
FMT_PREFIX = 4

TYPE_MEM = 0
TYPE_IO = 2
TYPE_CFG0 = 4
TYPE_CFG1 = 5
TYPE_CPL = 10

ERR_EARLY_EOP = 2
ERR_LATE_EOP = 3
ERR_BAD_KEEP = 4
ERR_BAD_FMT_TYPE = 5
ERR_BAD_LENGTH = 6
ERR_BAD_ADDRESS_FORMAT = 8
ERR_ECRC = 9


async def initialize(dut, mps=128, mrrs=128):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    for handle in dut:
        if handle._name.endswith("_i") and handle._name not in {"clk_i", "rst_i"}:
            try:
                handle.value = 0
            except (AttributeError, ValueError):
                pass

    dut.rst_i.value = 1
    dut.link_up_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.link_up_i.value = 1
    dut.transmit_enable_i.value = 1
    dut.requester_id_i.value = 0x1234
    dut.completer_id_i.value = 0x5678
    dut.bus_number_i.value = 0x25
    dut.device_number_i.value = 0x12
    dut.function_number_i.value = 3
    dut.memory_enable_i.value = 1
    dut.extended_tag_enable_i.value = 1
    dut.max_payload_bytes_i.value = mps
    dut.max_read_bytes_i.value = mrrs
    dut.rcb_128b_i.value = 1
    dut.m_dllp_axis_tready.value = 1
    dut.fc_initialized_i.value = 1
    dut.fc_ph_i.value = 64
    dut.fc_pd_i.value = 512
    dut.fc_nph_i.value = 64
    dut.fc_npd_i.value = 512
    dut.fc_cplh_i.value = 64
    dut.fc_cpld_i.value = 512
    dut.fc_update_valid_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid_i.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk_i)


async def capture_packets(dut, count, timeout=2000):
    packets = []
    packet = []
    for _ in range(timeout):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.m_dllp_axis_tvalid.value) and int(dut.m_dllp_axis_tready.value):
            packet.append((int(dut.m_dllp_axis_tdata.value),
                           int(dut.m_dllp_axis_tkeep.value)))
            if int(dut.m_dllp_axis_tlast.value):
                packets.append(packet)
                packet = []
                if len(packets) == count:
                    return packets
    raise AssertionError(f"timed out after receiving {len(packets)}/{count} TLPs")


async def submit_command(dut, command, address, byte_count, payload=None,
                         tc=0, attr=0, context=0x100, prefix=None, ecrc=False):
    dut.command_i.value = command
    dut.command_address_i.value = address
    dut.command_byte_count_i.value = byte_count
    dut.command_tc_i.value = tc
    dut.command_attr_i.value = attr
    dut.command_context_i.value = context
    dut.command_prefix_valid_i.value = prefix is not None
    dut.command_prefix_i.value = 0 if prefix is None else prefix
    dut.command_ecrc_enable_i.value = ecrc
    dut.command_valid_i.value = 1
    while not int(dut.command_ready_o.value):
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.command_valid_i.value = 0

    if payload is not None:
        for index, (word, keep) in enumerate(payload):
            dut.command_data_i.value = word
            dut.command_keep_i.value = keep
            dut.command_data_last_i.value = index == len(payload) - 1
            dut.command_data_valid_i.value = 1
            for _ in range(500):
                await Timer(1, units="ps")
                if int(dut.command_data_ready_o.value):
                    break
                await RisingEdge(dut.clk_i)
            else:
                raise AssertionError("local payload was never accepted")
            await RisingEdge(dut.clk_i)
        dut.command_data_valid_i.value = 0
        dut.command_data_last_i.value = 0


def decode_packet(packet):
    words = [word for word, _ in packet]
    index = 1 if ((words[0] >> 5) & 0x7) == FMT_PREFIX else 0
    dw0 = words[index]
    fmt = (dw0 >> 5) & 0x7
    tlp_type = dw0 & 0x1F
    encoded_length = (((dw0 >> 16) & 0x3) << 8) | ((dw0 >> 24) & 0xFF)
    length_dw = 1024 if encoded_length == 0 else encoded_length
    header_words = 4 if fmt in (FMT_4DW_ND, FMT_4DW_D) else 3
    digest = bool((dw0 >> 23) & 1)
    return {
        "prefix": index == 1,
        "dw0_index": index,
        "fmt": fmt,
        "type": tlp_type,
        "tc": (dw0 >> 12) & 0x7,
        "attr": (((dw0 >> 10) & 1) << 2) | ((dw0 >> 20) & 0x3),
        "length_dw": length_dw,
        "tag": (words[index + 1] >> 8) & 0xFF,
        "header_words": header_words,
        "digest": digest,
    }


async def send_rx_packet(dut, packet):
    for index, (word, keep) in enumerate(packet):
        dut.s_dllp_axis_tdata.value = word
        dut.s_dllp_axis_tkeep.value = keep
        dut.s_dllp_axis_tlast.value = index == len(packet) - 1
        dut.s_dllp_axis_tvalid.value = 1
        for _ in range(500):
            await Timer(1, units="ps")
            if int(dut.s_dllp_axis_tready.value):
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("receive parser remained backpressured")
        await RisingEdge(dut.clk_i)
    dut.s_dllp_axis_tvalid.value = 0
    dut.s_dllp_axis_tlast.value = 0


async def receive_target(dut, packet, expected_payload_words=0):
    dut.target_request_ready_i.value = 0
    dut.target_data_ready_i.value = 0
    await send_rx_packet(dut, packet)
    for _ in range(100):
        await Timer(1, units="ps")
        if int(dut.target_request_valid_o.value):
            break
        await RisingEdge(dut.clk_i)
    else:
        raise AssertionError("legal TLP was not delivered to the target")

    snapshot = {
        "header": int(dut.target_request_header_o.value),
        "class": int(dut.target_request_class_o.value),
        "memory": int(dut.target_memory_o.value),
        "config": int(dut.target_config_o.value),
        "config_hit": int(dut.target_config_hit_o.value),
        "config_type_one": int(dut.target_config_type_one_o.value),
        "config_offset": int(dut.target_config_offset_o.value),
        "read": int(dut.target_read_o.value),
        "write": int(dut.target_write_o.value),
        "unsupported": int(dut.target_unsupported_o.value),
        "bar_hit": int(dut.target_bar_hit_o.value),
    }
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        assert int(dut.target_request_valid_o.value) == 1
        assert int(dut.target_request_header_o.value) == snapshot["header"]

    dut.target_data_ready_i.value = 1
    dut.target_request_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.target_request_ready_i.value = 0
    payload = []
    for _ in range(max(200, expected_payload_words * 3)):
        await Timer(1, units="ps")
        if int(dut.target_data_valid_o.value):
            payload.append((int(dut.target_data_o.value), int(dut.target_keep_o.value)))
            last = int(dut.target_data_last_o.value)
            await RisingEdge(dut.clk_i)
            if last:
                break
        elif len(payload) < expected_payload_words:
            await RisingEdge(dut.clk_i)
        else:
            break
    dut.target_data_ready_i.value = 0
    assert len(payload) == expected_payload_words
    return snapshot, payload


def raw_request(fmt, tlp_type, address, length=1, first_be=0xF, last_be=0,
                requester=0xA5A5, tag=0x5A, payload=None, digest=None):
    payload = [] if payload is None else payload
    encoded = 0 if length == 1024 else length
    dw0 = (fmt << 5) | tlp_type | ((encoded & 0xFF) << 24) | (((encoded >> 8) & 3) << 16)
    if digest is not None:
        dw0 |= 1 << 23
    words = [(dw0, 0xF), ((requester << 16) | (tag << 8) | (last_be << 4) | first_be, 0xF)]
    if fmt in (FMT_4DW_ND, FMT_4DW_D):
        words.extend([((address >> 32) & 0xFFFFFFFF, 0xF), (address & 0xFFFFFFFC, 0xF)])
    else:
        words.append((address & 0xFFFFFFFC, 0xF))
    words.extend(payload)
    if digest is not None:
        words.append((digest, 0xF))
    return words


async def expect_rx_error(dut, packet, code):
    async def monitor():
        for _ in range(max(100, len(packet) * 3)):
            await Timer(1, units="ps")
            if int(dut.rx_error_valid_o.value):
                assert int(dut.rx_error_code_o.value) == code
                return
            await RisingEdge(dut.clk_i)
        raise AssertionError(f"expected receive error {code}")

    watcher = cocotb.start_soon(monitor())
    await send_rx_packet(dut, packet)
    await watcher
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def all_request_families_and_header_formats(dut):
    await initialize(dut)

    cases = [
        # command, address, count, payload, expected fmt/type/read/write
        (CMD_MEM_WRITE, 0x100, 4, [(0x44332211, 0xF)], FMT_3DW_D, TYPE_MEM, 0, 1),
        (CMD_MEM_READ, 0x1_0000_0100, 4, None, FMT_4DW_ND, TYPE_MEM, 1, 0),
        (CMD_IO_WRITE, 0x80, 4, [(0xAABBCCDD, 0xF)], FMT_3DW_D, TYPE_IO, 0, 1),
        (CMD_IO_READ, 0x84, 4, None, FMT_3DW_ND, TYPE_IO, 1, 0),
        (CMD_CFG_WRITE0, (0x25 << 24) | (0x12 << 19) | (3 << 16) | 0x40,
         4, [(0x11223344, 0xF)], FMT_3DW_D, TYPE_CFG0, 0, 1),
        (CMD_CFG_READ0, (0x25 << 24) | (0x12 << 19) | (3 << 16) | 0x44,
         4, None, FMT_3DW_ND, TYPE_CFG0, 1, 0),
    ]

    for number, case in enumerate(cases):
        command, address, count, payload, fmt, tlp_type, read, write = case
        capture = cocotb.start_soon(capture_packets(dut, 1))
        await submit_command(dut, command, address, count, payload=payload,
                             tc=number & 7, attr=(number ^ 3) & 7,
                             context=0x200 + number)
        packet = (await capture)[0]
        decoded = decode_packet(packet)
        assert decoded["fmt"] == fmt
        assert decoded["type"] == tlp_type
        assert decoded["length_dw"] == 1
        assert decoded["tc"] == (number & 7)
        assert decoded["attr"] == ((number ^ 3) & 7)

        target, target_payload = await receive_target(
            dut, packet, expected_payload_words=1 if payload else 0)
        assert target["read"] == read and target["write"] == write
        assert target["memory"] == (tlp_type == TYPE_MEM)
        assert target["config"] == (tlp_type == TYPE_CFG0)
        if tlp_type == TYPE_CFG0:
            assert target["config_hit"] == 1
            assert target["config_offset"] == (address & 0xFFC)
        if payload:
            assert target_payload[0] == payload[0]

    # Type-1 configuration requests are accepted on receive and decoded separately.
    cfg1_address = (0x25 << 24) | (0x12 << 19) | (3 << 16) | 0x80
    cfg1 = raw_request(FMT_3DW_ND, TYPE_CFG1, cfg1_address)
    target, _ = await receive_target(dut, cfg1)
    assert target["config"] == 1
    assert target["config_hit"] == 1
    assert target["config_type_one"] == 1


@cocotb.test()
async def prefix_ecrc_alignment_maximum_and_segmentation(dut):
    await initialize(dut, mps=128, mrrs=128)

    # Prefix + 4DW + unaligned payload + ECRC exercises every optional packet section.
    capture = cocotb.start_soon(capture_packets(dut, 1))
    await submit_command(dut, CMD_MEM_WRITE, 0x1_0000_0001, 7,
                         payload=[(0x44332211, 0xF), (0x00776655, 0x7)],
                         prefix=0x00000080, ecrc=True, tc=7, attr=5)
    packet = (await capture)[0]
    decoded = decode_packet(packet)
    assert decoded["prefix"] and decoded["digest"]
    assert decoded["fmt"] == FMT_4DW_D and decoded["length_dw"] == 2
    assert len(packet) == 1 + 4 + 2 + 1
    target, payload = await receive_target(dut, packet, expected_payload_words=2)
    assert target["memory"] == 1 and target["write"] == 1
    assert payload[0][1] == 0xE and payload[-1][1] == 0xF
    assert int(dut.rx_ecrc_error_o.value) == 0

    # A 300-byte MRd is split by MRRS and receives a unique tracked tag per TLP.
    capture = cocotb.start_soon(capture_packets(dut, 3))
    await submit_command(dut, CMD_MEM_READ, 0x1003, 300, context=0x777)
    packets = await capture
    decoded = [decode_packet(packet) for packet in packets]
    assert [item["length_dw"] for item in decoded] == [32, 32, 12]
    assert len({item["tag"] for item in decoded}) == 3
    assert int(dut.outstanding_o.value) == 3

    # Maximum legal payload encoding: Length field 0 represents 1024 DW.
    maximum = raw_request(FMT_3DW_D, TYPE_MEM, 0, length=1024,
                          first_be=0xF, last_be=0xF,
                          payload=[(index, 0xF) for index in range(1024)])
    target, maximum_payload = await receive_target(dut, maximum, 1024)
    assert target["memory"] == 1 and len(maximum_payload) == 1024
    assert maximum_payload[0][0] == 0 and maximum_payload[-1][0] == 1023


async def request_completion(dut, request_header, byte_count, lower_address,
                             payload=None, status=0, ecrc=False):
    capture = cocotb.start_soon(capture_packets(dut, 1))
    dut.completion_request_header_i.value = request_header
    dut.completion_request_status_i.value = status
    dut.completion_request_byte_count_i.value = byte_count
    dut.completion_request_lower_address_i.value = lower_address
    dut.completion_request_ecrc_enable_i.value = ecrc
    dut.completion_request_valid_i.value = 1
    while not int(dut.completion_request_ready_o.value):
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.completion_request_valid_i.value = 0
    if payload:
        for index, (word, keep) in enumerate(payload):
            dut.completion_request_data_i.value = word
            dut.completion_request_keep_i.value = keep
            dut.completion_request_data_last_i.value = index == len(payload) - 1
            dut.completion_request_data_valid_i.value = 1
            while not int(dut.completion_request_data_ready_o.value):
                await RisingEdge(dut.clk_i)
            await RisingEdge(dut.clk_i)
        dut.completion_request_data_valid_i.value = 0
        dut.completion_request_data_last_i.value = 0
    return (await capture)[0]


@cocotb.test()
async def request_to_completion_to_tag_retirement(dut):
    await initialize(dut)
    capture = cocotb.start_soon(capture_packets(dut, 1))
    await submit_command(dut, CMD_MEM_READ, 0x104, 4, context=0xBEEF, ecrc=True)
    request_packet = (await capture)[0]
    target, _ = await receive_target(dut, request_packet)
    assert int(dut.outstanding_o.value) == 1

    completion_packet = await request_completion(
        dut, target["header"], byte_count=4, lower_address=4,
        payload=[(0xDEADBEEF, 0xF)], ecrc=True)
    decoded = decode_packet(completion_packet)
    assert decoded["type"] == TYPE_CPL and decoded["fmt"] == FMT_3DW_D
    assert decoded["digest"]

    dut.received_completion_ready_i.value = 1
    dut.received_completion_data_ready_i.value = 1
    dut.result_ready_i.value = 0
    await send_rx_packet(dut, completion_packet)
    for _ in range(100):
        await Timer(1, units="ps")
        if int(dut.result_valid_o.value):
            break
        await RisingEdge(dut.clk_i)
    else:
        raise AssertionError("completion did not produce a requester result")
    assert int(dut.result_context_o.value) == 0xBEEF
    assert int(dut.result_status_o.value) == 0
    assert int(dut.result_last_o.value) == 1
    assert int(dut.outstanding_o.value) == 0
    dut.result_ready_i.value = 1
    await RisingEdge(dut.clk_i)

    # An unmatched completion is rejected and exposes a typed tracker error.
    bad_cpl = raw_request(FMT_3DW_ND, TYPE_CPL, 0, length=1024)
    # Completion DW1/DW2 differ from request headers.
    bad_cpl[1] = ((0x5678 << 16) | 4, 0xF)
    bad_cpl[2] = ((0x9999 << 16) | (0xEE << 8), 0xF)
    dut.result_ready_i.value = 1
    async def watch_unexpected():
        for _ in range(100):
            await Timer(1, units="ps")
            if int(dut.unexpected_completion_o.value):
                assert int(dut.completion_error_code_o.value) != 0
                return
            await RisingEdge(dut.clk_i)
        raise AssertionError("unmatched completion was not reported")

    watcher = cocotb.start_soon(watch_unexpected())
    await send_rx_packet(dut, bad_cpl)
    await watcher


@cocotb.test()
async def malformed_protocol_timing_ecrc_and_recovery(dut):
    await initialize(dut)

    await expect_rx_error(dut, [((1 << 24), 0x7)], ERR_BAD_KEEP)
    await expect_rx_error(dut, raw_request(FMT_3DW_D, TYPE_MEM, 0, payload=[]),
                          ERR_EARLY_EOP)

    late = raw_request(FMT_3DW_ND, TYPE_MEM, 0)
    late[-1] = (late[-1][0], 0xF)
    late.append((0x12345678, 0xF))
    await expect_rx_error(dut, late, ERR_LATE_EOP)

    await expect_rx_error(dut, raw_request(FMT_4DW_ND, TYPE_IO, 0x1_0000_0000),
                          ERR_BAD_FMT_TYPE)
    await expect_rx_error(dut, raw_request(FMT_4DW_ND, TYPE_MEM, 0x100),
                          ERR_BAD_ADDRESS_FORMAT)
    await expect_rx_error(dut, raw_request(FMT_3DW_ND, TYPE_CFG0, 0, length=2,
                                           last_be=0xF), ERR_BAD_LENGTH)

    # Generate a valid digest, corrupt it, and ensure the target never sees the TLP.
    capture = cocotb.start_soon(capture_packets(dut, 1))
    await submit_command(dut, CMD_MEM_READ, 0x200, 4, ecrc=True)
    corrupt = (await capture)[0]
    corrupt[-1] = (corrupt[-1][0] ^ 1, corrupt[-1][1])
    dut.target_request_ready_i.value = 0
    await expect_rx_error(dut, corrupt, ERR_ECRC)
    assert int(dut.target_request_valid_o.value) == 0

    # Recovery is mandatory: a legal request immediately following malformed traffic passes.
    legal = raw_request(FMT_3DW_ND, TYPE_MEM, 0x300)
    target, _ = await receive_target(dut, legal)
    assert target["memory"] == 1 and target["read"] == 1

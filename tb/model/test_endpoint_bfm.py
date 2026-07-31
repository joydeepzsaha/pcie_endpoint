"""Application- and packet-side tests for the complete Python Endpoint BFM."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from model import (  # noqa: E402
    CompletionRequest,
    CompletionStatus,
    DllpType,
    EndpointCommand,
    EndpointCommandCode,
    ErrorCode,
    LinkState,
    ModelConfig,
    PcieEndpointBfm,
    Tlp,
    TlpFmt,
    TlpType,
    tlp_ecrc,
)
from test_support import (  # noqa: E402
    activate,
    collect_tlps,
    config_request,
    dllp_event,
    fc_dllp,
    memory_read,
    memory_write,
    payload,
    tlp_event,
)


class CommandBusTests(unittest.TestCase):
    def test_unaligned_segmented_prefix_ecrc_write(self):
        endpoint = PcieEndpointBfm()
        activate(endpoint)
        endpoint.max_payload_bytes = 128
        command = EndpointCommand(
            code=EndpointCommandCode.MEMORY_WRITE,
            address=0x81,
            byte_count=300,
            traffic_class=5,
            attributes=3,
            prefix_valid=True,
            prefix=int(TlpFmt.PREFIX) << 29,
            ecrc_enable=True,
            payload=payload(300, 0x20),
        )
        self.assertTrue(endpoint.submit_command(command))
        packets = collect_tlps(endpoint, 16)
        self.assertEqual(len(packets), 3)
        self.assertEqual([packet.sequence for packet in packets], [0, 1, 2])
        self.assertEqual(packets[0].tlp.header.first_be, 0xE)
        self.assertEqual(packets[0].tlp.header.length_dw, 32)
        self.assertTrue(packets[0].tlp.header.prefix_present)
        self.assertEqual(packets[0].tlp.ecrc, tlp_ecrc(packets[0].tlp))
        self.assertEqual(packets[2].tlp.header.address, 0x180)

    def test_4dw_read_tag_and_invalid_command(self):
        endpoint = PcieEndpointBfm()
        activate(endpoint)
        read = EndpointCommand(
            code=EndpointCommandCode.MEMORY_READ,
            address=0x1_0000_1000,
            byte_count=16,
            context=0x1234,
        )
        self.assertTrue(endpoint.submit_command(read))
        packets = collect_tlps(endpoint, 6)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].tlp.header.fmt, TlpFmt.FOUR_DW_NO_DATA)
        self.assertEqual(endpoint.status.outstanding, 1)
        bad = EndpointCommand(
            code=EndpointCommandCode.CONFIG_WRITE0,
            byte_count=3,
        )
        self.assertFalse(endpoint.submit_command(bad))
        self.assertEqual(endpoint.status.command_error, ErrorCode.BAD_LENGTH)


class TargetBusTests(unittest.TestCase):
    def test_bar_config_decode_crossing_and_memory_disable(self):
        endpoint = PcieEndpointBfm()
        endpoint.set_function_id(2, 3, 1)
        endpoint.memory_enable = True
        self.assertTrue(
            endpoint.configure_bar(
                0, 0x80000000, 0xFFFFFFFFFFFFF000, True
            )
        )
        activate(endpoint)
        write = memory_write(
            0x80000040, [0x44332211, 0x88776655], tag=0x22
        )
        endpoint.push_link_rx(tlp_event(write, 0))
        endpoint.tick()
        target = endpoint.pop_target_request()
        self.assertTrue(target.memory)
        self.assertTrue(target.write)
        self.assertTrue(target.bar_hit)
        self.assertEqual(target.offset, 0x40)
        self.assertFalse(target.unsupported)

        config = config_request(False, 0x74, tag=3)
        config.header.destination_id = endpoint.function_id
        endpoint.push_link_rx(tlp_event(config, 1))
        endpoint.tick()
        target = endpoint.pop_target_request()
        self.assertTrue(target.config)
        self.assertTrue(target.config_hit)
        self.assertEqual(target.config_offset, 0x74)

        crossing = memory_read(0x80000FFC, 2, tag=4)
        endpoint.push_link_rx(tlp_event(crossing, 2))
        endpoint.tick()
        target = endpoint.pop_target_request()
        self.assertFalse(target.bar_hit)
        self.assertTrue(target.unsupported)

        endpoint.memory_enable = False
        disabled = memory_read(0x80000020, 1, tag=5)
        endpoint.push_link_rx(tlp_event(disabled, 3))
        endpoint.tick()
        self.assertTrue(endpoint.pop_target_request().unsupported)

    def test_bar_overlap(self):
        endpoint = PcieEndpointBfm()
        endpoint.memory_enable = True
        endpoint.configure_bar(0, 0x80000000, 0xFFFFFFFFFFFFF000, True)
        endpoint.configure_bar(1, 0x80000000, 0xFFFFFFFFFFFFF000, True)
        activate(endpoint)
        endpoint.push_link_rx(tlp_event(memory_read(0x80000040, 1), 0))
        endpoint.tick()
        target = endpoint.pop_target_request()
        self.assertTrue(target.bar_overlap)
        self.assertFalse(target.bar_hit)
        self.assertTrue(target.unsupported)


class CompletionTests(unittest.TestCase):
    def test_received_completion_context_and_unexpected_tag(self):
        endpoint = PcieEndpointBfm()
        endpoint.set_function_id(1, 0, 0)
        activate(endpoint)
        command = EndpointCommand(
            code=EndpointCommandCode.MEMORY_READ,
            address=0x4000,
            byte_count=16,
            context=0xA55A,
        )
        endpoint.submit_command(command)
        requests = collect_tlps(endpoint, 6)
        completion = Tlp(payload=[
            0x03020100,
            0x07060504,
            0x0B0A0908,
            0x0F0E0D0C,
        ])
        completion.header.fmt = TlpFmt.THREE_DW_DATA
        completion.header.type = TlpType.COMPLETION
        completion.header.length_dw = 4
        completion.header.requester_id = endpoint.function_id
        completion.header.tag = requests[0].tlp.header.tag
        completion.header.byte_count = 16
        endpoint.push_link_rx(tlp_event(completion, 0))
        endpoint.tick()
        self.assertIsNotNone(endpoint.pop_received_completion())
        result = endpoint.pop_result()
        self.assertEqual(result.context, 0xA55A)
        self.assertTrue(result.last)
        self.assertEqual(endpoint.status.outstanding, 0)

        completion.header.tag = 0x1F
        endpoint.push_link_rx(tlp_event(completion, 1))
        endpoint.tick()
        self.assertTrue(endpoint.status.unexpected_completion)
        self.assertEqual(
            endpoint.status.completion_error,
            ErrorCode.UNEXPECTED_COMPLETION,
        )

    def test_completion_generation_mps_rcb_and_error_status(self):
        endpoint = PcieEndpointBfm()
        endpoint.set_function_id(3, 0, 0)
        endpoint.max_payload_bytes = 128
        endpoint.rcb_128b = False
        activate(endpoint)
        request_header = memory_read(0, 1).header
        request_header.requester_id = 0x100
        request_header.tag = 9
        response = CompletionRequest(
            request_header=request_header,
            status=CompletionStatus.SUCCESS,
            byte_count=200,
            lower_address=0x20,
            ecrc_enable=True,
            payload=payload(200, 0x40),
        )
        self.assertTrue(endpoint.submit_completion(response))
        packets = collect_tlps(endpoint, 16)
        self.assertEqual(len(packets), 4)
        self.assertEqual(packets[0].tlp.header.byte_count, 200)
        self.assertEqual(packets[0].tlp.header.length_dw, 8)
        self.assertEqual(packets[0].tlp.header.completer_id, endpoint.function_id)

        error_response = CompletionRequest(
            request_header=request_header,
            status=CompletionStatus.UNSUPPORTED_REQUEST,
        )
        self.assertTrue(endpoint.submit_completion(error_response))
        packets = collect_tlps(endpoint, 6)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].tlp.header.fmt, TlpFmt.THREE_DW_NO_DATA)


class EndpointFlowAndResetTests(unittest.TestCase):
    def test_credit_starvation_update_and_release(self):
        config = ModelConfig(initial_zero_credit_is_infinite=False)
        endpoint = PcieEndpointBfm(config)
        activate(endpoint, header_credits=1, data_credits=0)
        command = EndpointCommand(
            code=EndpointCommandCode.MEMORY_WRITE,
            address=0x1000,
            byte_count=4,
            payload=payload(4),
        )
        endpoint.submit_command(command)
        endpoint.tick()
        endpoint.tick()
        self.assertTrue(endpoint.status.tx_fc_blocked)
        endpoint.push_link_rx(
            dllp_event(fc_dllp(DllpType.UPDATE_FC_P, 2, 1))
        )
        endpoint.tick()
        self.assertEqual(len(collect_tlps(endpoint, 4)), 1)
        self.assertFalse(endpoint.status.tx_fc_blocked)

    def test_link_down_clears_tags_and_application_queues(self):
        endpoint = PcieEndpointBfm()
        activate(endpoint)
        endpoint.submit_command(
            EndpointCommand(
                code=EndpointCommandCode.MEMORY_READ,
                address=0x100000000,
                byte_count=8,
                context=7,
            )
        )
        collect_tlps(endpoint, 4)
        self.assertEqual(endpoint.status.outstanding, 1)
        endpoint.set_phy_link_up(False)
        endpoint.tick()
        self.assertEqual(endpoint.link_status.state, LinkState.INACTIVE)
        self.assertEqual(endpoint.status.outstanding, 0)
        self.assertIsNone(endpoint.pop_target_request())


if __name__ == "__main__":
    unittest.main()

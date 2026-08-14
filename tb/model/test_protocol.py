"""Focused non-vendor tests for the Python codecs, FC, and Data Link BFM."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from model import (  # noqa: E402
    CompletionStatus,
    DataLinkLayer,
    Dllp,
    DllpType,
    ErrorCode,
    FlowControl,
    LinkEventKind,
    LinkState,
    ModelConfig,
    Tlp,
    TlpFmt,
    TlpType,
    TrafficClass,
    decode_dllp,
    decode_tlp,
    encode_dllp,
    encode_tlp,
    tlp_ecrc,
    validate_tlp,
)
from test_support import (  # noqa: E402
    dllp_event,
    fc_dllp,
    memory_read,
    memory_write,
    tlp_event,
)


class CodecTests(unittest.TestCase):
    def test_tlp_3dw_4dw_prefix_ecrc_and_length_zero_encoding(self):
        packet = memory_write(
            0x80000040,
            [0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00],
            requester_id=0x1234,
            tag=0x5A,
        )
        packet.header.traffic_class = 5
        packet.header.attributes = 3
        packet.header.prefix_present = True
        packet.header.prefix = int(TlpFmt.PREFIX) << 29
        packet.header.digest_present = True
        packet.ecrc = tlp_ecrc(packet)
        encoded = encode_tlp(packet)
        self.assertIsNotNone(encoded)
        self.assertEqual(encoded[0], packet.header.prefix)
        decoded = decode_tlp(encoded)
        self.assertIsNotNone(decoded)
        self.assertTrue(decoded.header.prefix_present)
        self.assertEqual(decoded.header.address, packet.header.address)
        self.assertEqual(decoded.payload, packet.payload)
        self.assertTrue(validate_tlp(packet, ModelConfig()).valid)

        read = memory_read(0x1200001000, 1024, requester_id=0xCAFE, tag=0xFF)
        encoded = encode_tlp(read)
        self.assertEqual(encoded[0] & 0x3FF, 0)
        decoded = decode_tlp(encoded)
        self.assertEqual(decoded.header.length_dw, 1024)
        self.assertEqual(decoded.header.fmt, TlpFmt.FOUR_DW_NO_DATA)

    def test_completion_and_dllp_crc(self):
        completion = Tlp()
        completion.header.fmt = TlpFmt.THREE_DW_NO_DATA
        completion.header.type = TlpType.COMPLETION
        completion.header.requester_id = 0x100
        completion.header.completer_id = 0x200
        completion.header.tag = 7
        completion.header.completion_status = CompletionStatus.UNSUPPORTED_REQUEST
        decoded = decode_tlp(encode_tlp(completion))
        self.assertEqual(decoded.header.length_dw, 0)
        self.assertEqual(
            decoded.header.completion_status,
            CompletionStatus.UNSUPPORTED_REQUEST,
        )

        dllp = fc_dllp(DllpType.INIT_FC1_CPL, 0xA5, 0xBCD)
        encoded = encode_dllp(dllp)
        decoded_dllp = decode_dllp(encoded)
        self.assertEqual(decoded_dllp.header_credits, 0xA5)
        corrupted = bytearray(encoded)
        corrupted[2] ^= 1
        self.assertIsNone(decode_dllp(bytes(corrupted)))


class FlowControlTests(unittest.TestCase):
    def test_cc_cl_gating_updates_and_rollover(self):
        config = ModelConfig(initial_zero_credit_is_infinite=True)
        flow = FlowControl(config)
        self.assertTrue(flow.receive(fc_dllp(DllpType.INIT_FC1_P, 2, 4), True))
        self.assertTrue(flow.receive(fc_dllp(DllpType.INIT_FC1_NP, 1, 0), True))
        self.assertTrue(flow.receive(fc_dllp(DllpType.INIT_FC1_CPL, 1, 3), True))
        self.assertTrue(flow.consume_transmit(TrafficClass.POSTED, 4))
        self.assertFalse(flow.can_transmit(TrafficClass.POSTED, 1))
        self.assertTrue(flow.receive(fc_dllp(DllpType.UPDATE_FC_P, 3, 5), False))
        self.assertTrue(flow.can_transmit(TrafficClass.POSTED, 1))
        self.assertTrue(flow.transmit_available().nonposted.data_infinite)

        flow.reset()
        self.assertTrue(flow.receive(fc_dllp(DllpType.INIT_FC1_P, 0x7F, 0), True))
        for _ in range(0x7F):
            self.assertTrue(flow.consume_transmit(TrafficClass.POSTED, 0))
        self.assertFalse(flow.can_transmit(TrafficClass.POSTED, 0))
        self.assertTrue(flow.receive(fc_dllp(DllpType.UPDATE_FC_P, 0xFF, 0), False))
        for _ in range(0x80):
            self.assertTrue(flow.consume_transmit(TrafficClass.POSTED, 0))
        self.assertTrue(flow.receive(fc_dllp(DllpType.UPDATE_FC_P, 1, 0), False))
        self.assertEqual(flow.transmit_available().posted.header, 2)

    def test_receiver_ca_cr_strict_overflow_check(self):
        flow = FlowControl(ModelConfig())
        for _ in range(224):
            self.assertTrue(flow.reserve_receive(TrafficClass.POSTED, 0))
            self.assertTrue(flow.release_receive(TrafficClass.POSTED, 0))
        counters = flow.counters()
        self.assertEqual(counters.posted_header.credit_allocated, 0)
        self.assertEqual(counters.posted_header.credits_received, 224)
        self.assertFalse(flow.receiver_overflow_detected)
        for _ in range(32):
            self.assertTrue(flow.reserve_receive(TrafficClass.POSTED, 0))
        counters = flow.counters()
        self.assertEqual(counters.posted_header.credit_allocated, 0)
        self.assertEqual(counters.posted_header.credits_received, 0)
        self.assertFalse(flow.receiver_overflow_detected)
        self.assertFalse(flow.reserve_receive(TrafficClass.POSTED, 0))
        self.assertTrue(flow.receiver_overflow_detected)


class DataLinkTests(unittest.TestCase):
    @staticmethod
    def activate(link: DataLinkLayer) -> None:
        link.set_phy_link_up(True)
        link.tick()
        for dllp_type in (
            DllpType.INIT_FC1_P,
            DllpType.INIT_FC1_NP,
            DllpType.INIT_FC1_CPL,
            DllpType.INIT_FC2_P,
            DllpType.INIT_FC2_NP,
            DllpType.INIT_FC2_CPL,
        ):
            link.push_link_rx(dllp_event(fc_dllp(dllp_type)))
            link.tick()
        for _ in range(4):
            link.tick()
        while link.pop_link_tx() is not None:
            pass

    def test_initialization_duplicate_bad_lcrc_and_ack(self):
        link = DataLinkLayer()
        self.activate(link)
        self.assertEqual(link.status.state, LinkState.DL_ACTIVE)
        request = memory_read(0x1000, 1)
        link.push_link_rx(tlp_event(request, 0))
        link.tick()
        self.assertIsNotNone(link.pop_received_tlp())
        response = link.pop_link_tx()
        self.assertEqual(response.kind, LinkEventKind.DLLP)
        self.assertEqual(response.dllp.type, DllpType.ACK)
        link.push_link_rx(tlp_event(request, 0))
        link.tick()
        self.assertIsNone(link.pop_received_tlp())
        self.assertEqual(link.pop_link_tx().dllp.type, DllpType.ACK)
        link.push_link_rx(tlp_event(request, 1, corrupt_lcrc=True))
        link.tick()
        self.assertEqual(link.status.last_error, ErrorCode.LCRC)
        self.assertEqual(link.pop_link_tx().dllp.type, DllpType.NAK)

    def test_nak_replay_and_link_down_cleanup(self):
        link = DataLinkLayer()
        self.activate(link)
        request = memory_read(0x2000, 1)
        self.assertTrue(link.submit_tlp(request))
        link.tick()
        original = link.pop_link_tx()
        self.assertEqual(original.kind, LinkEventKind.TLP)
        link.push_link_rx(
            dllp_event(Dllp(type=DllpType.NAK, sequence=original.sequence))
        )
        link.tick()
        replay = link.pop_link_tx()
        self.assertEqual(replay.sequence, original.sequence)
        self.assertEqual(replay.lcrc, original.lcrc)
        link.set_phy_link_up(False)
        link.tick()
        self.assertEqual(link.status.state, LinkState.INACTIVE)
        self.assertTrue(link.status.entered_inactive)


if __name__ == "__main__":
    unittest.main()

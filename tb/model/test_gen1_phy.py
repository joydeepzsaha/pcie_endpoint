"""Exhaustive-intent tests for bidirectional Gen1 scrambling and 8b/10b."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from model import (  # noqa: E402
    Gen1PhyCodec,
    Gen1Receiver,
    Gen1Scrambler,
    Gen1Transmitter,
    LEGAL_K_BYTES,
    PcieEndpointBfm,
    decode_8b10b,
    encode_8b10b,
    gen1_lfsr_step,
)


def lfsr_reference(state: int) -> int:
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


class EightBTenBTests(unittest.TestCase):
    def test_all_data_symbols_both_running_disparities(self):
        for disparity in (0, 1):
            for byte in range(256):
                encoded = encode_8b10b(byte, False, disparity)
                decoded = decode_8b10b(encoded.code, disparity)
                self.assertFalse(decoded.code_error)
                self.assertFalse(decoded.disparity_error)
                self.assertFalse(decoded.is_control)
                self.assertEqual(decoded.byte, byte)
                self.assertEqual(
                    decoded.running_disparity,
                    encoded.running_disparity,
                )

    def test_all_legal_control_symbols_and_illegal_control_input(self):
        for disparity in (0, 1):
            for byte in LEGAL_K_BYTES:
                encoded = encode_8b10b(byte, True, disparity)
                decoded = decode_8b10b(encoded.code, disparity)
                self.assertFalse(decoded.code_error)
                self.assertFalse(decoded.disparity_error)
                self.assertTrue(decoded.is_control)
                self.assertEqual(decoded.byte, byte)
        with self.assertRaises(ValueError):
            encode_8b10b(0x00, True, 0)

    def test_invalid_code_and_wrong_disparity_detection(self):
        legal_codes = {
            encode_8b10b(byte, False, disparity).code
            for byte in range(256)
            for disparity in (0, 1)
        }
        legal_codes.update(
            encode_8b10b(byte, True, disparity).code
            for byte in LEGAL_K_BYTES
            for disparity in (0, 1)
        )
        for code in range(1024):
            if code not in legal_codes:
                self.assertTrue(decode_8b10b(code, 0).code_error)
                self.assertTrue(decode_8b10b(code, 1).code_error)

        disparity_violation = next(
            (
                encode_8b10b(byte, False, 0).code
                for byte in range(256)
                if decode_8b10b(
                    encode_8b10b(byte, False, 0).code, 1
                ).disparity_error
            )
        )
        self.assertTrue(
            decode_8b10b(disparity_violation, 1).disparity_error
        )


class ScramblerTests(unittest.TestCase):
    def test_lfsr_matches_repository_byte_step_and_disable_holds(self):
        for state in (0, 1, 2, 3, 0x8000, 0xFFFF, 0xACE1, 0x1234, 0x5A5A):
            self.assertEqual(gen1_lfsr_step(state), lfsr_reference(state))
            self.assertEqual(gen1_lfsr_step(state, disabled=True), state)

    def test_scramble_descramble_continuous_data(self):
        transmitter = Gen1Scrambler()
        receiver = Gen1Scrambler()
        source = list(range(64))
        encoded = [transmitter.process(byte) for byte in source]
        decoded = [receiver.process(byte) for byte in encoded]
        self.assertEqual(decoded, source)
        self.assertEqual(transmitter.state, receiver.state)

    def test_control_bypass_skp_hold_and_com_reset(self):
        scrambler = Gen1Scrambler()
        initial = scrambler.state
        self.assertEqual(
            scrambler.process(0x1C, is_control=True, advance=False),
            0x1C,
        )
        self.assertEqual(scrambler.state, initial)
        scrambler.process(0x55)
        self.assertNotEqual(scrambler.state, initial)
        self.assertEqual(
            scrambler.process(
                0xBC,
                is_control=True,
                reset_after=True,
            ),
            0xBC,
        )
        self.assertEqual(scrambler.state, initial)


class BidirectionalPhyTests(unittest.TestCase):
    def test_tx_rx_roundtrip_with_independent_persistent_state(self):
        codec = Gen1PhyCodec()
        source = [
            (0xFB, True),   # STP
            (0x12, False),
            (0x34, False),
            (0x56, False),
            (0x78, False),
            (0xFD, True),   # END
        ]
        encoded = [
            codec.tx.encode(byte, is_control=is_control)
            for byte, is_control in source
        ]
        decoded = [
            codec.rx.decode(symbol.code)
            for symbol in encoded
        ]
        self.assertEqual(
            [(symbol.byte, symbol.is_control) for symbol in decoded],
            source,
        )
        self.assertFalse(any(symbol.code_error for symbol in decoded))
        self.assertFalse(any(symbol.disparity_error for symbol in decoded))
        self.assertEqual(
            codec.tx.scrambler.state,
            codec.rx.scrambler.state,
        )
        self.assertEqual(
            codec.tx.running_disparity,
            codec.rx.running_disparity,
        )

    def test_endpoint_exposes_tx_and_rx_symbol_paths_and_error_status(self):
        endpoint = PcieEndpointBfm()
        source = [(0xFB, True), (0xAB, False), (0xCD, False), (0xFD, True)]
        encoded = [
            endpoint.encode_phy_tx_symbol(byte, is_control=is_control)
            for byte, is_control in source
        ]
        decoded = [
            endpoint.decode_phy_rx_symbol(symbol.code)
            for symbol in encoded
        ]
        self.assertEqual(
            [(symbol.byte, symbol.is_control) for symbol in decoded],
            source,
        )
        legal_codes = {
            encode_8b10b(byte, False, disparity).code
            for byte in range(256)
            for disparity in (0, 1)
        }
        legal_codes.update(
            encode_8b10b(byte, True, disparity).code
            for byte in LEGAL_K_BYTES
            for disparity in (0, 1)
        )
        invalid = next(code for code in range(1024) if code not in legal_codes)
        endpoint.decode_phy_rx_symbol(invalid)
        self.assertTrue(endpoint.status.phy_rx_code_error)
        endpoint.clear_status_events()
        self.assertFalse(endpoint.status.phy_rx_code_error)

        disparity_code = next(
            (
                encode_8b10b(byte, False, 1).code
                for byte in range(256)
                if decode_8b10b(
                    encode_8b10b(byte, False, 1).code, 0
                ).disparity_error
            )
        )
        endpoint.decode_phy_rx_symbol(disparity_code)
        self.assertTrue(endpoint.status.phy_rx_disparity_error)


if __name__ == "__main__":
    unittest.main()

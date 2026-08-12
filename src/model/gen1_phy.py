"""Bidirectional PCIe Gen1 scrambler and 8b/10b symbol codec."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


LEGAL_K_BYTES = frozenset(
    {
        0x1C,  # K28.0 / SKP
        0x3C,  # K28.1 / FTS
        0x5C,  # K28.2 / SDP
        0x7C,  # K28.3 / IDL
        0x9C,  # K28.4 / RV2
        0xBC,  # K28.5 / COM
        0xDC,  # K28.6 / RV3
        0xFC,  # K28.7 / EIE
        0xF7,  # K23.7 / PAD
        0xFB,  # K27.7 / STP
        0xFD,  # K29.7 / END
        0xFE,  # K30.7 / EDB
    }
)


@dataclass(frozen=True)
class EncodedSymbol:
    code: int
    running_disparity: int
    byte: int
    is_control: bool


@dataclass(frozen=True)
class DecodedSymbol:
    byte: int = 0
    is_control: bool = False
    running_disparity: int = 0
    code_error: bool = False
    disparity_error: bool = False


def gen1_lfsr_step(state: int, disabled: bool = False) -> int:
    """Advance the repository's 16-bit Gen1 byte scrambler by eight bits."""
    state &= 0xFFFF
    if disabled:
        return state
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


def _reverse_16(value: int) -> int:
    return int(f"{value & 0xFFFF:016b}"[::-1], 2)


class Gen1Scrambler:
    """Symmetric per-lane Gen1 scrambler/descrambler."""

    def __init__(self, seed: int = 0xFFFF, disabled: bool = False):
        self.seed = seed & 0xFFFF
        self.disabled = disabled
        self.state = self.seed

    def reset(self) -> None:
        self.state = self.seed

    def process(
        self,
        byte: int,
        *,
        is_control: bool = False,
        scramble: bool = True,
        advance: bool = True,
        reset_after: bool = False,
    ) -> int:
        """Scramble or descramble one byte and update the per-lane LFSR.

        Control symbols bypass the XOR but normally advance the LFSR. Callers
        can set ``advance=False`` for SKP ordered-set symbols and
        ``reset_after=True`` for a COM that initializes the following stream.
        """
        byte &= 0xFF
        active = not self.disabled
        mask = _reverse_16(self.state) & 0xFF
        result = byte ^ mask if active and scramble and not is_control else byte
        if active and advance:
            self.state = gen1_lfsr_step(self.state)
        if active and reset_after:
            self.state = self.seed
        return result & 0xFF


def encode_8b10b(byte: int, is_control: bool, disparity: int) -> EncodedSymbol:
    """Encode one legal D.x.y or K.x.y symbol using the repository RTL logic."""
    byte &= 0xFF
    disparity &= 1
    if is_control and byte not in LEGAL_K_BYTES:
        raise ValueError(f"illegal 8b/10b control byte 0x{byte:02x}")
    bits = [(byte >> bit) & 1 for bit in range(8)]
    ai, bi, ci, di, ei, fi, gi, hi = bits
    ki = int(is_control)

    aeqb = int(ai == bi)
    ceqd = int(ci == di)
    l22 = (ai and bi and not ci and not di) or (
        ci and di and not ai and not bi
    ) or (not aeqb and not ceqd)
    l40 = ai and bi and ci and di
    l04 = not ai and not bi and not ci and not di
    l13 = (not aeqb and not ci and not di) or (
        not ceqd and not ai and not bi
    )
    l31 = (not aeqb and ci and di) or (not ceqd and ai and bi)

    ao = ai
    bo = (bi and not l40) or l04
    co = l04 or ci or (ei and di and not ci and not bi and not ai)
    do = di and not (ai and bi and ci)
    eo = (ei or l13) and not (ei and di and not ci and not bi and not ai)
    io = (
        (l22 and not ei)
        or (ei and not di and not ci and not (ai and bi))
        or (ei and l40)
        or (ki and ei and di and ci and not bi and not ai)
        or (ei and not di and ci and not bi and not ai)
    )
    pd1s6 = (ei and di and not ci and not bi and not ai) or (
        not ei and not l22 and not l31
    )
    nd1s6 = ki or (ei and not l22 and not l13) or (
        not ei and not di and ci and bi and ai
    )
    ndos6 = pd1s6
    pdos6 = ki or (ei and not l22 and not l13)
    alt7 = fi and gi and hi and (
        ki
        or (
            (not ei and di and l31)
            if disparity
            else (ei and not di and l13)
        )
    )
    fo = fi and not alt7
    go = gi or (not fi and not gi and not hi)
    ho = hi
    jo = (not hi and bool(gi ^ fi)) or alt7
    nd1s4 = fi and gi
    pd1s4 = (not fi and not gi) or (
        ki and ((fi and not gi) or (not fi and gi))
    )
    ndos4 = not fi and not gi
    pdos4 = fi and gi and hi
    compls6 = (pd1s6 and not disparity) or (nd1s6 and disparity)
    disp6 = disparity ^ int(bool(ndos6 or pdos6))
    compls4 = (pd1s4 and not disp6) or (nd1s4 and disp6)
    dispout = disp6 ^ int(bool(ndos4 or pdos4))
    output_bits = (
        int(bool(ao) ^ bool(compls6)),
        int(bool(bo) ^ bool(compls6)),
        int(bool(co) ^ bool(compls6)),
        int(bool(do) ^ bool(compls6)),
        int(bool(eo) ^ bool(compls6)),
        int(bool(io) ^ bool(compls6)),
        int(bool(fo) ^ bool(compls4)),
        int(bool(go) ^ bool(compls4)),
        int(bool(ho) ^ bool(compls4)),
        int(bool(jo) ^ bool(compls4)),
    )
    code = sum(bit << index for index, bit in enumerate(output_bits))
    return EncodedSymbol(code, dispout, byte, is_control)


def _build_decode_tables() -> Tuple[
    Dict[Tuple[int, int], EncodedSymbol],
    Dict[int, List[EncodedSymbol]],
]:
    exact: Dict[Tuple[int, int], EncodedSymbol] = {}
    any_disparity: Dict[int, List[EncodedSymbol]] = {}
    legal_symbols = [(byte, False) for byte in range(256)]
    legal_symbols.extend((byte, True) for byte in sorted(LEGAL_K_BYTES))
    for disparity in (0, 1):
        for byte, is_control in legal_symbols:
            encoded = encode_8b10b(byte, is_control, disparity)
            exact[(encoded.code, disparity)] = encoded
            any_disparity.setdefault(encoded.code, []).append(encoded)
    return exact, any_disparity


_DECODE_EXACT, _DECODE_ANY = _build_decode_tables()


def decode_8b10b(code: int, disparity: int) -> DecodedSymbol:
    """Decode a 10-bit symbol and report code and running-disparity errors."""
    code &= 0x3FF
    disparity &= 1
    exact = _DECODE_EXACT.get((code, disparity))
    if exact is not None:
        return DecodedSymbol(
            byte=exact.byte,
            is_control=exact.is_control,
            running_disparity=exact.running_disparity,
        )
    candidates = _DECODE_ANY.get(code)
    if candidates:
        candidate = candidates[0]
        return DecodedSymbol(
            byte=candidate.byte,
            is_control=candidate.is_control,
            running_disparity=candidate.running_disparity,
            disparity_error=True,
        )
    return DecodedSymbol(
        running_disparity=disparity,
        code_error=True,
    )


class Gen1Transmitter:
    """Persistent TX scrambler followed by 8b/10b running-disparity state."""

    def __init__(self, seed: int = 0xFFFF, disparity: int = 0):
        self.initial_disparity = disparity & 1
        self.scrambler = Gen1Scrambler(seed)
        self.running_disparity = self.initial_disparity

    def reset(self) -> None:
        self.scrambler.reset()
        self.running_disparity = self.initial_disparity

    def encode(
        self,
        byte: int,
        *,
        is_control: bool = False,
        scramble: bool = True,
        advance_lfsr: bool = True,
        reset_lfsr_after: bool = False,
    ) -> EncodedSymbol:
        encoded_byte = self.scrambler.process(
            byte,
            is_control=is_control,
            scramble=scramble,
            advance=advance_lfsr,
            reset_after=reset_lfsr_after,
        )
        encoded = encode_8b10b(
            encoded_byte, is_control, self.running_disparity
        )
        self.running_disparity = encoded.running_disparity
        return encoded

    def encode_stream(
        self,
        symbols: List[Tuple[int, bool]],
        *,
        scramble: bool = True,
    ) -> List[EncodedSymbol]:
        return [
            self.encode(byte, is_control=is_control, scramble=scramble)
            for byte, is_control in symbols
        ]


class Gen1Receiver:
    """Persistent 8b/10b decoder followed by the symmetric descrambler."""

    def __init__(self, seed: int = 0xFFFF, disparity: int = 0):
        self.initial_disparity = disparity & 1
        self.scrambler = Gen1Scrambler(seed)
        self.running_disparity = self.initial_disparity

    def reset(self) -> None:
        self.scrambler.reset()
        self.running_disparity = self.initial_disparity

    def decode(
        self,
        code: int,
        *,
        scramble: bool = True,
        advance_lfsr: bool = True,
        reset_lfsr_after: bool = False,
    ) -> DecodedSymbol:
        decoded = decode_8b10b(code, self.running_disparity)
        if decoded.code_error:
            return decoded
        self.running_disparity = decoded.running_disparity
        byte = self.scrambler.process(
            decoded.byte,
            is_control=decoded.is_control,
            scramble=scramble,
            advance=advance_lfsr,
            reset_after=reset_lfsr_after,
        )
        return DecodedSymbol(
            byte=byte,
            is_control=decoded.is_control,
            running_disparity=decoded.running_disparity,
            code_error=False,
            disparity_error=decoded.disparity_error,
        )

    def decode_stream(
        self,
        codes: List[int],
        *,
        scramble: bool = True,
    ) -> List[DecodedSymbol]:
        return [self.decode(code, scramble=scramble) for code in codes]


class Gen1PhyCodec:
    """Independent persistent TX and RX coding paths for one Gen1 lane."""

    def __init__(
        self,
        seed: int = 0xFFFF,
        tx_disparity: int = 0,
        rx_disparity: int = 0,
    ):
        self.tx = Gen1Transmitter(seed, tx_disparity)
        self.rx = Gen1Receiver(seed, rx_disparity)

    def reset(self) -> None:
        self.tx.reset()
        self.rx.reset()

"""Spec-golden models for the PCIe Gen1 receive path.

Every value here is computed from PCI Express Base Specification Rev 2.1; nothing is
captured from the DUT. Section and page citations are given per function.

  Base 2.1 sec 4.2.3 pp.198-199   scrambling rules (seed, COM, SKP, K codes, TS bodies)
  Base 2.1 App. C.1 pp.697-700    the reference 8-shift advance, the XOR mapping, and
                                  the two published golden tables used as anchors
  Base 2.1 Table 4-1  p.194       Special Symbol encodings
  Base 2.1 Table 4-2  pp.201-203  TS1 Ordered Set
  Base 2.1 Table 4-3  pp.203-205  TS2 Ordered Set
  Base 2.1 Table 4-4  p.205       Electrical Idle Ordered Set
  Base 2.1 sec 4.2.4.4 p.208      Lane Polarity Inversion
  Base 2.1 sec 4.2.7.1 p.261      SKP Ordered Set (transmitter form)

Full oracle table with the MindShare cross-check:
  pcie_docs/evidence/phy-rx-golden/ORACLES_PHY_RX.md
"""

# ---- Table 4-1 p.194: Special Symbols.  Dx.y / Kx.y -> byte = (y << 5) | x ----
COM = 0xBC   # K28.5
STP = 0xFB   # K27.7
SDP = 0x5C   # K28.2
END = 0xFD   # K29.7
EDB = 0xFE   # K30.7
PAD = 0xF7   # K23.7
SKP = 0x1C   # K28.0
FTS = 0x3C   # K28.1
IDL = 0x7C   # K28.3
EIE = 0xFC   # K28.7

# ---- Tables 4-2 / 4-3 identifiers, and sec 4.2.4.4 p.208 inverted forms ----
TS1_ID = 0x4A      # D10.2
TS2_ID = 0x45      # D5.2
TS1_ID_INV = 0xB5  # D21.5 -- what D10.2 becomes under polarity inversion
TS2_ID_INV = 0xBA  # D26.5 -- what D5.2 becomes under polarity inversion

GEN1 = 0x01        # rate_speed_e.gen1


def kx_y(x, y):
    """Dx.y / Kx.y to its 8-bit value.  Base 2.1 sec 4.2.1 / Appendix B."""
    return ((y & 0x7) << 5) | (x & 0x1F)


# ------------------------------------------------------------------ scrambler

def advance(lfsr):
    """Advance the LFSR one Symbol time = eight serial shifts.

    Verbatim from the reference implementation, Base 2.1 Appendix C.1 p.698.
    Polynomial G(X) = X^16 + X^5 + X^4 + X^3 + 1 (sec 4.2.3 p.199).
    """
    b = [(lfsr >> i) & 1 for i in range(16)]
    o = [0] * 16
    o[0] = b[8]
    o[1] = b[9]
    o[2] = b[10]
    o[3] = b[11] ^ b[8]
    o[4] = b[12] ^ b[9] ^ b[8]
    o[5] = b[13] ^ b[10] ^ b[9] ^ b[8]
    o[6] = b[14] ^ b[11] ^ b[10] ^ b[9]
    o[7] = b[15] ^ b[12] ^ b[11] ^ b[10]
    o[8] = b[0] ^ b[13] ^ b[12] ^ b[11]
    o[9] = b[1] ^ b[14] ^ b[13] ^ b[12]
    o[10] = b[2] ^ b[15] ^ b[14] ^ b[13]
    o[11] = b[3] ^ b[15] ^ b[14]
    o[12] = b[4] ^ b[15]
    o[13] = b[5]
    o[14] = b[6]
    o[15] = b[7]
    return sum(v << i for i, v in enumerate(o))


def xor_mask(lfsr):
    """The byte XORed with the data: data bit i ^ LFSR bit (15 - i).

    Base 2.1 App. C.1 p.699 (descrambit[0] ^= bit[15] ... descrambit[7] ^= bit[8])
    and sec 4.2.3 p.198 ("D15, is XORed with D0 of the data").
    """
    return sum((((lfsr >> (15 - i)) & 1) << i) for i in range(8))


class Descrambler:
    """Receive-side descrambler.  Scrambling and descrambling are the same
    operation (Base 2.1 App. C.1 p.698: "THE DESCRAMBLE ROUTINE IS IDENTICAL")."""

    SEED = 0xFFFF   # sec 4.2.3 p.199

    def __init__(self):
        self.lfsr = self.SEED

    def symbol(self, byte, is_k, in_ts=False):
        """Process one received Symbol, return the descrambled byte.

        in_ts  -- this Symbol lies inside a TS1/TS2 Ordered Set, so its D
                  characters are not descrambled (sec 4.2.3 p.199 bullet 3,
                  sec 4.2.4.1 p.201).  The LFSR still advances: the "do not
                  advance" exception is SKP only (bullet 2).
        """
        if is_k and byte == COM:
            self.lfsr = self.SEED        # bullet 5 + App. C.1: reset, no advance
            return byte
        if is_k and byte == SKP:
            return byte                  # bullet 2: no advance, no descramble
        out = byte
        if not is_k and not in_ts:       # bullets 3 and 4
            out = byte ^ xor_mask(self.lfsr)
        self.lfsr = advance(self.lfsr)   # one Symbol = eight shifts
        return out

    def run(self, stream):
        """stream: iterable of (byte, is_k, in_ts) -> list of descrambled bytes."""
        return [self.symbol(b, k, t) for b, k, t in stream]


# -------------------------------------------------------------- ordered sets

def ts_ordered_set(ident, link=PAD, lane=PAD, n_fts=0xFF, rate_id=0x02,
                   train_ctrl=0x00, tail=None):
    """A 16-Symbol TS1 or TS2 Ordered Set as (byte, is_k) pairs.

    Base 2.1 Table 4-2 pp.201-203 / Table 4-3 pp.203-205:
      0    K28.5 COM
      1    Link Number  (D0.0-D31.7, or K23.7 PAD)
      2    Lane Number  (D0.0-D31.0, or K23.7 PAD)
      3    N_FTS
      4    Data Rate Identifier
      5    Training Control
      6-15 TS identifier -- D10.2 for TS1, D5.2 for TS2

    tail -- optional explicit list of ten bytes for Symbols 6-15, used to build
            the deliberately-malformed sets that test the "6-15" requirement.
    """
    body = tail if tail is not None else [ident] * 10
    assert len(body) == 10, "Symbols 6-15 are ten Symbols"
    syms = [(COM, 1),
            (link, 1 if link == PAD else 0),
            (lane, 1 if lane == PAD else 0),
            (n_fts, 0), (rate_id, 0), (train_ctrl, 0)]
    syms += [(b, 0) for b in body]
    return syms


def eios():
    """Electrical Idle Ordered Set at 2.5 GT/s: COM + three IDL.
    Base 2.1 sec 4.2.4.2 p.205 and Table 4-4 p.205.  All four are K codes."""
    return [(COM, 1), (IDL, 1), (IDL, 1), (IDL, 1)]


def skp_os(n_skp=3):
    """SKP Ordered Set: COM followed by SKP Symbols.

    Transmitters send exactly three (sec 4.2.7.1 p.261).  Receivers must accept
    one to five (sec 4.2.7.2 p.262) -- that is why n_skp is a parameter.
    """
    assert 1 <= n_skp <= 5, "sec 4.2.7.2 p.262: one to five SKP Symbols"
    return [(COM, 1)] + [(SKP, 1)] * n_skp


def fts_os():
    """FTS Ordered Set: COM followed by three K28.1.  Base 2.1 sec 4.2.4.5 p.208."""
    return [(COM, 1), (FTS, 1), (FTS, 1), (FTS, 1)]


def fmt(pairs):
    """Render a symbol stream for log output."""
    out = []
    for p in pairs:
        b, k = p[0], p[1]
        out.append("%02x%s" % (b, "K" if k else ""))
    return " ".join(out)

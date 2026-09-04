"""Spec-golden model of Gen1 data scrambling — Base 2.1 §4.2.3 pp.198-199.

Written for tracker §54 #9(B)'s guard rows (fix-arc 5c).  Every expected value
here is COMPUTED FROM THE SPECIFICATION; none is captured from the DUT.

THE RULES, quoted from PCIE-base-spec.Rev2-1.pdf §4.2.3 p.199
-------------------------------------------------------------
  * "The COM Symbol initializes the LFSR."
  * "The LFSR value is advanced eight serial shifts for each Symbol except the
     SKP."
  * "All special Symbols (K codes) are not scrambled."
  * "The initialized value of an LFSR seed (D0-D15) is FFFFh.  Immediately after
     a COM exits the Transmit LFSR, the LFSR on the Transmit side is
     initialized.  EVERY TIME a COM enters the Receive LFSR on any Lane of that
     Link, the LFSR on the Receive side is initialized."
  * p.198: "An output of the LFSR, D15, is XORed with D0 of the data to be
     processed."

⚠️ "Every time a COM" carries NO EXEMPTION for the COM that opens a SKP Ordered
Set.  A SKP Ordered Set is COM + 3×SKP, so the conformant sequence is: the COM
initializes to FFFFh, the three SKPs do not advance it, and THE FIRST DATA SYMBOL
AFTER THE ORDERED SET IS XORED WITH FFFFh ITSELF.  That single consequence is
what these rows exist to pin, because gen1_scramble.sv:73 — the line that
delivers it — reads like a defect and was twice registered as one.

WHY THE ADVANCE FUNCTION IS REUSED RATHER THAN RE-DERIVED
---------------------------------------------------------
`advance()` is byte_scramble.sv's transition table.  Rung 3 drove that module
over all 65536 states exhaustively against the spec polynomial, so it is already
proven and copying it here introduces no unproven step.  What is NOT reused is
anything about gen1_scramble's own sequencing — the whole point is to check that
against an outside model.

⚠️ kgap_common.py is IMPORTED but NEVER MODIFIED.  verilate_scrambler_kgap
depends on it and a shared-helper edit would move that target's six rows for a
reason unrelated to this one.
"""

COM = 0xBC
SKP = 0x1C


def advance(q):
    """byte_scramble.sv's 8-serial-shift advance, bit i of the SystemVerilog
    vector at Python bit i."""
    b = [(q >> i) & 1 for i in range(16)]
    o = [0] * 16
    o[0] = b[8]
    o[1] = b[9]
    o[2] = b[10]
    o[3] = b[8] ^ b[11]
    o[4] = b[8] ^ b[9] ^ b[12]
    o[5] = b[8] ^ b[9] ^ b[10] ^ b[13]
    o[6] = b[9] ^ b[10] ^ b[11] ^ b[14]
    o[7] = b[10] ^ b[11] ^ b[12] ^ b[15]
    o[8] = b[0] ^ b[11] ^ b[12] ^ b[13]
    o[9] = b[1] ^ b[12] ^ b[13] ^ b[14]
    o[10] = b[2] ^ b[13] ^ b[14] ^ b[15]
    o[11] = b[3] ^ b[14] ^ b[15]
    o[12] = b[4] ^ b[15]
    o[13] = b[5]
    o[14] = b[6]
    o[15] = b[7]
    return sum(v << i for i, v in enumerate(o))


def mask(q):
    """The byte XORed with a data Symbol.  p.198: LFSR output D15 meets data D0,
    so data bit j meets LFSR bit 15-j."""
    return sum((((q >> (15 - j)) & 1) << j) for j in range(8))


def seeded_stream(data_words, phase):
    """Scramble `data_words` (16-bit PIPE words, ALL data Symbols) with an LFSR
    seeded FFFFh and pre-advanced `phase` Symbol times.

    phase == 0 is the Base 2.1 §4.2.3 p.199 requirement immediately after a SKP
    Ordered Set: the Ordered Set's COM initialized the LFSR, its three SKPs did
    not advance it, so the next data Symbol meets FFFFh itself.
    """
    lfsr = 0xFFFF
    for _ in range(phase):
        lfsr = advance(lfsr)
    out = []
    for w in data_words:
        lo = (w & 0xFF) ^ mask(lfsr)
        lfsr = advance(lfsr)
        hi = ((w >> 8) & 0xFF) ^ mask(lfsr)
        lfsr = advance(lfsr)
        out.append(lo | (hi << 8))
    return out


def matching_phases(data_words, published, window):
    """Every phase in range(window) whose spec-computed stream reproduces
    `published` exactly.  Returned as a list so a row can assert on its LENGTH
    (does the instrument discriminate?) as well as its CONTENT (is the phase the
    conformant one?) — two different claims that must not be conflated."""
    return [p for p in range(window)
            if seeded_stream(data_words, p) == list(published)]


def publication_skew(published, ordered_set_index, n_os_words):
    """Derive the DUT's data/valid publication skew FROM THIS RUN.

    data_valid_o is scrambler.sv:76's ONE-stage copy of data_valid_i while the
    data path is FOUR stages deep, so the first published beats carry reset
    state rather than driven Symbols.  Hard-coding that depth would make these
    rows fail for the wrong reason if the pipeline ever changed, so it is
    measured instead: the Ordered Set is the only K-coded thing in the stimulus,
    so wherever its K beats surface tells us the skew directly.
    """
    k_idx = [i for i, (_, k) in enumerate(published) if k]
    assert k_idx, "no K-coded beat was published -- the Ordered Set never arrived"
    assert len(k_idx) == n_os_words, (
        "expected %d K-coded beats for the Ordered Set, saw %d at %s"
        % (n_os_words, len(k_idx), k_idx))
    assert k_idx == list(range(k_idx[0], k_idx[0] + n_os_words)), (
        "the Ordered Set's K beats are not contiguous: %s" % k_idx)
    return k_idx[0] - ordered_set_index

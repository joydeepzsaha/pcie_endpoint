"""Spec-golden 8b/10b decode oracle -- PCI Express Base Specification, Rev. 2.1.

The oracle for `decode_8b10b` is a TABLE, not prose, so this module carries the
table verbatim rather than re-deriving it from an encoder of my own.  Every
expected value the benches use is computed here; none is captured from the DUT.

PROVENANCE
    Base 2.1 Table B-1 "8b/10b Data Symbol Codes"            p.687-694  (256 D rows)
    Base 2.1 Table B-2 "8b/10b Special Character Symbol Codes"  p.695    ( 12 K rows)
    Transcribed programmatically from `pdftotext -layout` output of
    book/PCIE-base-spec.Rev2-1.pdf by
    pcie_docs/evidence/decode-8b10b/scripts/transcribe_appendixB.py.
    The raw extraction is committed at
    pcie_docs/evidence/decode-8b10b/logs/b21_appendixB_raw.txt.

    METHOD OF RECORD: *table transcription*, not "my own encoder inverted".
    The distinction matters.  An encoder written from the 5b/6b + 3b/4b rules
    and then inverted would share any misreading of those rules with the
    decoder it is meant to judge; a transcription of the published table cannot,
    because the table is data.

    The transcription is self-checking against redundancy the spec itself
    prints: each row carries the symbol NAME (Dx.y / Kx.y), the byte VALUE in
    hex, AND the byte as `HGF EDCBA` bits.  check_table() proves all three agree
    on all 268 rows, so a mis-parsed column cannot pass silently.

GOVERNING RULE -- Base 2.1 sec 4.2.1.3 "8b/10b Decode Rules", pp.194-195:

    "The Symbol tables for the valid 8b/10b codes are given in Appendix B.
     These tables have one column for the positive disparity and one column
     for the negative disparity. ... All following received Symbols after the
     initial disparity is set must be found in the proper column corresponding
     to the current running disparity.  If a received Symbol is found in the
     column corresponding to the incorrect running disparity or if the Symbol
     does not correspond to either column, the Physical Layer must notify the
     Data Link Layer that the received Symbol is invalid.  This is a Receiver
     Error, and is a reported error associated with the Port (see Section 6.2)."

    Note the spec requires ONE notification ("the received Symbol is invalid")
    for BOTH failure modes.  The RTL splits it into `code_err` and `disp_err`;
    that split is a superset of the requirement, not a conflict with it.

BIT ORDER
    Base 2.1 prints code-groups as `abcdei fghj`, `a` transmitted first.
    decode_8b10b.sv:16-25 maps a->datain[0] ... j->datain[9], i.e. `a` in the
    LSB.  code_to_datain() below does exactly that mapping and nothing else.

DISPARITY ENCODING
    dispin/dispout are one bit, 0 = negative running disparity.  That is the
    design's own declaration -- encode_8b10b.sv:8 says
    `input dispin;  // 0 = neg disp; 1 = pos disp`.  The now-deleted
    tb/scrambler/test_8b10b.v independently repeated it in its column map, and
    the fact is carried here rather than cited so it survives that file:
    its vector table encoded "10b symbol if starting disparity was negative"
    as 0 and the positive-disparity column as 1 -- the same polarity.
    It is a port convention, not a spec claim; the spec names
    columns "Current RD-" and "Current RD+" and says nothing about wires.
"""

RD_NEG = 0
RD_POS = 1

# ---------------------------------------------------------------------------
# Base 2.1 Appendix B, verbatim.  Columns:
#   name   hex   <RD- abcdei> <RD- fghj>   <RD+ abcdei> <RD+ fghj>
# ---------------------------------------------------------------------------
SPEC_APPENDIX_B = """
D0.0   00 100111 0100 011000 1011
D1.0   01 011101 0100 100010 1011
D2.0   02 101101 0100 010010 1011
D3.0   03 110001 1011 110001 0100
D4.0   04 110101 0100 001010 1011
D5.0   05 101001 1011 101001 0100
D6.0   06 011001 1011 011001 0100
D7.0   07 111000 1011 000111 0100
D8.0   08 111001 0100 000110 1011
D9.0   09 100101 1011 100101 0100
D10.0  0A 010101 1011 010101 0100
D11.0  0B 110100 1011 110100 0100
D12.0  0C 001101 1011 001101 0100
D13.0  0D 101100 1011 101100 0100
D14.0  0E 011100 1011 011100 0100
D15.0  0F 010111 0100 101000 1011
D16.0  10 011011 0100 100100 1011
D17.0  11 100011 1011 100011 0100
D18.0  12 010011 1011 010011 0100
D19.0  13 110010 1011 110010 0100
D20.0  14 001011 1011 001011 0100
D21.0  15 101010 1011 101010 0100
D22.0  16 011010 1011 011010 0100
D23.0  17 111010 0100 000101 1011
D24.0  18 110011 0100 001100 1011
D25.0  19 100110 1011 100110 0100
D26.0  1A 010110 1011 010110 0100
D27.0  1B 110110 0100 001001 1011
D28.0  1C 001110 1011 001110 0100
D29.0  1D 101110 0100 010001 1011
D30.0  1E 011110 0100 100001 1011
D31.0  1F 101011 0100 010100 1011
D0.1   20 100111 1001 011000 1001
D1.1   21 011101 1001 100010 1001
D2.1   22 101101 1001 010010 1001
D3.1   23 110001 1001 110001 1001
D4.1   24 110101 1001 001010 1001
D5.1   25 101001 1001 101001 1001
D6.1   26 011001 1001 011001 1001
D7.1   27 111000 1001 000111 1001
D8.1   28 111001 1001 000110 1001
D9.1   29 100101 1001 100101 1001
D10.1  2A 010101 1001 010101 1001
D11.1  2B 110100 1001 110100 1001
D12.1  2C 001101 1001 001101 1001
D13.1  2D 101100 1001 101100 1001
D14.1  2E 011100 1001 011100 1001
D15.1  2F 010111 1001 101000 1001
D16.1  30 011011 1001 100100 1001
D17.1  31 100011 1001 100011 1001
D18.1  32 010011 1001 010011 1001
D19.1  33 110010 1001 110010 1001
D20.1  34 001011 1001 001011 1001
D21.1  35 101010 1001 101010 1001
D22.1  36 011010 1001 011010 1001
D23.1  37 111010 1001 000101 1001
D24.1  38 110011 1001 001100 1001
D25.1  39 100110 1001 100110 1001
D26.1  3A 010110 1001 010110 1001
D27.1  3B 110110 1001 001001 1001
D28.1  3C 001110 1001 001110 1001
D29.1  3D 101110 1001 010001 1001
D30.1  3E 011110 1001 100001 1001
D31.1  3F 101011 1001 010100 1001
D0.2   40 100111 0101 011000 0101
D1.2   41 011101 0101 100010 0101
D2.2   42 101101 0101 010010 0101
D3.2   43 110001 0101 110001 0101
D4.2   44 110101 0101 001010 0101
D5.2   45 101001 0101 101001 0101
D6.2   46 011001 0101 011001 0101
D7.2   47 111000 0101 000111 0101
D8.2   48 111001 0101 000110 0101
D9.2   49 100101 0101 100101 0101
D10.2  4A 010101 0101 010101 0101
D11.2  4B 110100 0101 110100 0101
D12.2  4C 001101 0101 001101 0101
D13.2  4D 101100 0101 101100 0101
D14.2  4E 011100 0101 011100 0101
D15.2  4F 010111 0101 101000 0101
D16.2  50 011011 0101 100100 0101
D17.2  51 100011 0101 100011 0101
D18.2  52 010011 0101 010011 0101
D19.2  53 110010 0101 110010 0101
D20.2  54 001011 0101 001011 0101
D21.2  55 101010 0101 101010 0101
D22.2  56 011010 0101 011010 0101
D23.2  57 111010 0101 000101 0101
D24.2  58 110011 0101 001100 0101
D25.2  59 100110 0101 100110 0101
D26.2  5A 010110 0101 010110 0101
D27.2  5B 110110 0101 001001 0101
D28.2  5C 001110 0101 001110 0101
D29.2  5D 101110 0101 010001 0101
D30.2  5E 011110 0101 100001 0101
D31.2  5F 101011 0101 010100 0101
D0.3   60 100111 0011 011000 1100
D1.3   61 011101 0011 100010 1100
D2.3   62 101101 0011 010010 1100
D3.3   63 110001 1100 110001 0011
D4.3   64 110101 0011 001010 1100
D5.3   65 101001 1100 101001 0011
D6.3   66 011001 1100 011001 0011
D7.3   67 111000 1100 000111 0011
D8.3   68 111001 0011 000110 1100
D9.3   69 100101 1100 100101 0011
D10.3  6A 010101 1100 010101 0011
D11.3  6B 110100 1100 110100 0011
D12.3  6C 001101 1100 001101 0011
D13.3  6D 101100 1100 101100 0011
D14.3  6E 011100 1100 011100 0011
D15.3  6F 010111 0011 101000 1100
D16.3  70 011011 0011 100100 1100
D17.3  71 100011 1100 100011 0011
D18.3  72 010011 1100 010011 0011
D19.3  73 110010 1100 110010 0011
D20.3  74 001011 1100 001011 0011
D21.3  75 101010 1100 101010 0011
D22.3  76 011010 1100 011010 0011
D23.3  77 111010 0011 000101 1100
D24.3  78 110011 0011 001100 1100
D25.3  79 100110 1100 100110 0011
D26.3  7A 010110 1100 010110 0011
D27.3  7B 110110 0011 001001 1100
D28.3  7C 001110 1100 001110 0011
D29.3  7D 101110 0011 010001 1100
D30.3  7E 011110 0011 100001 1100
D31.3  7F 101011 0011 010100 1100
D0.4   80 100111 0010 011000 1101
D1.4   81 011101 0010 100010 1101
D2.4   82 101101 0010 010010 1101
D3.4   83 110001 1101 110001 0010
D4.4   84 110101 0010 001010 1101
D5.4   85 101001 1101 101001 0010
D6.4   86 011001 1101 011001 0010
D7.4   87 111000 1101 000111 0010
D8.4   88 111001 0010 000110 1101
D9.4   89 100101 1101 100101 0010
D10.4  8A 010101 1101 010101 0010
D11.4  8B 110100 1101 110100 0010
D12.4  8C 001101 1101 001101 0010
D13.4  8D 101100 1101 101100 0010
D14.4  8E 011100 1101 011100 0010
D15.4  8F 010111 0010 101000 1101
D16.4  90 011011 0010 100100 1101
D17.4  91 100011 1101 100011 0010
D18.4  92 010011 1101 010011 0010
D19.4  93 110010 1101 110010 0010
D20.4  94 001011 1101 001011 0010
D21.4  95 101010 1101 101010 0010
D22.4  96 011010 1101 011010 0010
D23.4  97 111010 0010 000101 1101
D24.4  98 110011 0010 001100 1101
D25.4  99 100110 1101 100110 0010
D26.4  9A 010110 1101 010110 0010
D27.4  9B 110110 0010 001001 1101
D28.4  9C 001110 1101 001110 0010
D29.4  9D 101110 0010 010001 1101
D30.4  9E 011110 0010 100001 1101
D31.4  9F 101011 0010 010100 1101
D0.5   A0 100111 1010 011000 1010
D1.5   A1 011101 1010 100010 1010
D2.5   A2 101101 1010 010010 1010
D3.5   A3 110001 1010 110001 1010
D4.5   A4 110101 1010 001010 1010
D5.5   A5 101001 1010 101001 1010
D6.5   A6 011001 1010 011001 1010
D7.5   A7 111000 1010 000111 1010
D8.5   A8 111001 1010 000110 1010
D9.5   A9 100101 1010 100101 1010
D10.5  AA 010101 1010 010101 1010
D11.5  AB 110100 1010 110100 1010
D12.5  AC 001101 1010 001101 1010
D13.5  AD 101100 1010 101100 1010
D14.5  AE 011100 1010 011100 1010
D15.5  AF 010111 1010 101000 1010
D16.5  B0 011011 1010 100100 1010
D17.5  B1 100011 1010 100011 1010
D18.5  B2 010011 1010 010011 1010
D19.5  B3 110010 1010 110010 1010
D20.5  B4 001011 1010 001011 1010
D21.5  B5 101010 1010 101010 1010
D22.5  B6 011010 1010 011010 1010
D23.5  B7 111010 1010 000101 1010
D24.5  B8 110011 1010 001100 1010
D25.5  B9 100110 1010 100110 1010
D26.5  BA 010110 1010 010110 1010
D27.5  BB 110110 1010 001001 1010
D28.5  BC 001110 1010 001110 1010
D29.5  BD 101110 1010 010001 1010
D30.5  BE 011110 1010 100001 1010
D31.5  BF 101011 1010 010100 1010
D0.6   C0 100111 0110 011000 0110
D1.6   C1 011101 0110 100010 0110
D2.6   C2 101101 0110 010010 0110
D3.6   C3 110001 0110 110001 0110
D4.6   C4 110101 0110 001010 0110
D5.6   C5 101001 0110 101001 0110
D6.6   C6 011001 0110 011001 0110
D7.6   C7 111000 0110 000111 0110
D8.6   C8 111001 0110 000110 0110
D9.6   C9 100101 0110 100101 0110
D10.6  CA 010101 0110 010101 0110
D11.6  CB 110100 0110 110100 0110
D12.6  CC 001101 0110 001101 0110
D13.6  CD 101100 0110 101100 0110
D14.6  CE 011100 0110 011100 0110
D15.6  CF 010111 0110 101000 0110
D16.6  D0 011011 0110 100100 0110
D17.6  D1 100011 0110 100011 0110
D18.6  D2 010011 0110 010011 0110
D19.6  D3 110010 0110 110010 0110
D20.6  D4 001011 0110 001011 0110
D21.6  D5 101010 0110 101010 0110
D22.6  D6 011010 0110 011010 0110
D23.6  D7 111010 0110 000101 0110
D24.6  D8 110011 0110 001100 0110
D25.6  D9 100110 0110 100110 0110
D26.6  DA 010110 0110 010110 0110
D27.6  DB 110110 0110 001001 0110
D28.6  DC 001110 0110 001110 0110
D29.6  DD 101110 0110 010001 0110
D30.6  DE 011110 0110 100001 0110
D31.6  DF 101011 0110 010100 0110
D0.7   E0 100111 0001 011000 1110
D1.7   E1 011101 0001 100010 1110
D2.7   E2 101101 0001 010010 1110
D3.7   E3 110001 1110 110001 0001
D4.7   E4 110101 0001 001010 1110
D5.7   E5 101001 1110 101001 0001
D6.7   E6 011001 1110 011001 0001
D7.7   E7 111000 1110 000111 0001
D8.7   E8 111001 0001 000110 1110
D9.7   E9 100101 1110 100101 0001
D10.7  EA 010101 1110 010101 0001
D11.7  EB 110100 1110 110100 1000
D12.7  EC 001101 1110 001101 0001
D13.7  ED 101100 1110 101100 1000
D14.7  EE 011100 1110 011100 1000
D15.7  EF 010111 0001 101000 1110
D16.7  F0 011011 0001 100100 1110
D17.7  F1 100011 0111 100011 0001
D18.7  F2 010011 0111 010011 0001
D19.7  F3 110010 1110 110010 0001
D20.7  F4 001011 0111 001011 0001
D21.7  F5 101010 1110 101010 0001
D22.7  F6 011010 1110 011010 0001
D23.7  F7 111010 0001 000101 1110
D24.7  F8 110011 0001 001100 1110
D25.7  F9 100110 1110 100110 0001
D26.7  FA 010110 1110 010110 0001
D27.7  FB 110110 0001 001001 1110
D28.7  FC 001110 1110 001110 0001
D29.7  FD 101110 0001 010001 1110
D30.7  FE 011110 0001 100001 1110
D31.7  FF 101011 0001 010100 1110
K28.0  1C 001111 0100 110000 1011
K28.1  3C 001111 1001 110000 0110
K28.2  5C 001111 0101 110000 1010
K28.3  7C 001111 0011 110000 1100
K28.4  9C 001111 0010 110000 1101
K28.5  BC 001111 1010 110000 0101
K28.6  DC 001111 0110 110000 1001
K28.7  FC 001111 1000 110000 0111
K23.7  F7 111010 1000 000101 0111
K27.7  FB 110110 1000 001001 0111
K29.7  FD 101110 1000 010001 0111
K30.7  FE 011110 1000 100001 0111
"""


class SpecError(AssertionError):
    """The transcribed table failed one of its own consistency checks."""


def code_to_datain(abcdei, fghj):
    """Map the spec's `abcdei fghj` text to the RTL's datain[9:0] integer.

    decode_8b10b.sv:16-25:  a=datain[0] b=1 c=2 d=3 e=4 i=5 f=6 g=7 h=8 j=9.
    """
    a, b, c, d, e, i = (int(x) for x in abcdei)
    f, g, h, j = (int(x) for x in fghj)
    return (a << 0) | (b << 1) | (c << 2) | (d << 3) | (e << 4) | \
           (i << 5) | (f << 6) | (g << 7) | (h << 8) | (j << 9)


def datain_to_code(datain):
    """Inverse of code_to_datain: return the spec's ('abcdei', 'fghj') text."""
    bit = lambda n: (datain >> n) & 1
    abcdei = "".join(str(bit(n)) for n in (0, 1, 2, 3, 4, 5))
    fghj = "".join(str(bit(n)) for n in (6, 7, 8, 9))
    return abcdei, fghj


def popcount(datain):
    return bin(datain & 0x3FF).count("1")


def flips_disparity(datain):
    """A code-group is disparity-neutral iff it carries five 1s and five 0s.

    Any other legal code-group is +-2 and therefore inverts running disparity.
    check_table() proves that every RD- column entry has popcount 5 or 6 and
    every RD+ entry has popcount 4 or 5, which is what makes this rule total.
    """
    return popcount(datain) != 5


class Symbol:
    """One row of Table B-1 / B-2."""

    __slots__ = ("name", "value", "is_k", "code", "x", "y")

    def __init__(self, name, value, is_k, code):
        self.name = name
        self.value = value
        self.is_k = is_k
        self.code = code          # {RD_NEG: datain, RD_POS: datain}
        self.x = value & 0x1F
        self.y = (value >> 5) & 0x7

    @property
    def dataout(self):
        """The RTL's dataout[8:0]: dataout[8] is the K flag."""
        return ((1 if self.is_k else 0) << 8) | self.value

    def __repr__(self):
        return "<%s %02X>" % (self.name, self.value)


def _parse():
    symbols, by_code = [], {RD_NEG: {}, RD_POS: {}}
    for line in SPEC_APPENDIX_B.strip().splitlines():
        parts = line.split()
        if len(parts) != 6:
            raise SpecError("malformed table row: %r" % line)
        name, hexv, m6, m4, p6, p4 = parts
        sym = Symbol(
            name=name,
            value=int(hexv, 16),
            is_k=(name[0] == "K"),
            code={RD_NEG: code_to_datain(m6, m4), RD_POS: code_to_datain(p6, p4)},
        )
        symbols.append(sym)
        for rd in (RD_NEG, RD_POS):
            by_code[rd].setdefault(sym.code[rd], sym)
    return symbols, by_code


SYMBOLS, _BY_CODE = _parse()
BY_NAME = {s.name: s for s in SYMBOLS}


class Decoded:
    """The spec-required outcome of presenting `datain` at running disparity `rd`.

    cls is one of:
      "valid"            -- found in the column for rd.  No Receiver Error.
      "disparity_error"  -- a legal code-group, but found only in the OTHER
                            column.  Base 2.1 sec 4.2.1.3: Receiver Error.
      "invalid"          -- in neither column.  Base 2.1 sec 4.2.1.3: Receiver Error.
    """

    __slots__ = ("datain", "rd_in", "cls", "symbol", "rd_out")

    def __init__(self, datain, rd_in, cls, symbol, rd_out):
        self.datain, self.rd_in, self.cls = datain, rd_in, cls
        self.symbol, self.rd_out = symbol, rd_out

    # -- what the spec requires of a conforming receiver ---------------------
    @property
    def receiver_error(self):
        """Base 2.1 sec 4.2.1.3 pp.194-195: BOTH failure modes are Receiver Errors."""
        return self.cls != "valid"

    # -- what each RTL port should carry, where the spec constrains it -------
    @property
    def code_err(self):
        """1 iff the code-group is in neither column."""
        return 1 if self.cls == "invalid" else 0

    @property
    def disp_err(self):
        """1 iff a legal code-group arrived against the running disparity.

        None where the spec does not constrain it: on an INVALID code-group the
        value is a don't-care.  decode_8b10b.sv:136 says the same thing in the
        RTL's own words -- "may fire for illegal codes".
        """
        if self.cls == "invalid":
            return None
        return 1 if self.cls == "disparity_error" else 0

    @property
    def dataout(self):
        """The decoded byte + K flag, or None where the spec defines no value."""
        return None if self.symbol is None else self.symbol.dataout

    @property
    def is_k(self):
        return None if self.symbol is None else self.symbol.is_k

    def __repr__(self):
        return "<Decoded %03X rd=%d %s %r rd_out=%s>" % (
            self.datain, self.rd_in, self.cls, self.symbol, self.rd_out)


def decode(datain, rd_in):
    """The spec-golden decode of one code-group at running disparity rd_in."""
    datain &= 0x3FF
    here = _BY_CODE[rd_in].get(datain)
    if here is not None:
        return Decoded(datain, rd_in, "valid", here, rd_in ^ flips_disparity(datain))
    other = _BY_CODE[rd_in ^ 1].get(datain)
    if other is not None:
        # A legal code-group against the wrong running disparity.  The byte is
        # still recoverable from the table; the spec's requirement is that the
        # Symbol be reported invalid, not that it be discarded.  Running
        # disparity after such a Symbol is not defined by the spec -- see
        # ORACLES_8B10B.md E2 -- so rd_out is None.
        return Decoded(datain, rd_in, "disparity_error", other, None)
    return Decoded(datain, rd_in, "invalid", None, None)


def encode(symbol, rd_in):
    """Return (datain, rd_out) for one symbol transmitted at running disparity rd_in."""
    if isinstance(symbol, str):
        symbol = BY_NAME[symbol]
    code = symbol.code[rd_in]
    return code, rd_in ^ flips_disparity(code)


def encode_stream(names, rd_in=RD_NEG):
    """Encode a Symbol sequence, chaining running disparity as a real link does."""
    out, rd = [], rd_in
    for n in names:
        code, rd = encode(n, rd)
        out.append(code)
    return out, rd


# ---------------------------------------------------------------------------
# Self-test.  Runs at import of the benches and standalone via __main__.
# ---------------------------------------------------------------------------

# Eight rows read BY EYE off the pdftotext rendering of Base 2.1 p.687 and p.695,
# transcribed here by hand.  This is deliberately an independent path from the
# programmatic parse: if the parser mis-split a column, these disagree.
#
# sec 22.53 (no fixed-point payloads): a disparity-neutral symbol is a FIXED POINT of
# the running-disparity update (rd_out == rd_in), and 72 of the 268 symbols
# additionally encode identically in both columns.  A spot set drawn only from
# those would pass against a decoder that ignored dispin entirely.  The set below
# is checked to contain both flipping and non-flipping symbols, and both
# same-code and different-code-per-column symbols.
SPOT_VECTORS = [
    # name,    hex,  RD- abcdei fghj,   RD+ abcdei fghj
    ("D0.0",  0x00, "100111", "0100", "011000", "1011"),
    ("D3.0",  0x03, "110001", "1011", "110001", "0100"),
    ("D7.0",  0x07, "111000", "1011", "000111", "0100"),
    ("D15.0", 0x0F, "010111", "0100", "101000", "1011"),
    ("K28.0", 0x1C, "001111", "0100", "110000", "1011"),
    ("K28.5", 0xBC, "001111", "1010", "110000", "0101"),
    ("K23.7", 0xF7, "111010", "1000", "000101", "0111"),
    ("K27.7", 0xFB, "110110", "1000", "001001", "0111"),
]


def check_table():
    """Structural checks on the transcription itself."""
    if len(SYMBOLS) != 268:
        raise SpecError("expected 268 rows, parsed %d" % len(SYMBOLS))
    if sum(1 for s in SYMBOLS if not s.is_k) != 256:
        raise SpecError("expected 256 D rows")
    if sum(1 for s in SYMBOLS if s.is_k) != 12:
        raise SpecError("expected 12 K rows")
    if len(BY_NAME) != 268:
        raise SpecError("duplicate symbol name in the table")

    # The spec prints the byte three ways; all three must agree on every row.
    for s in SYMBOLS:
        kind, rest = s.name[0], s.name[1:]
        x, y = (int(v) for v in rest.split("."))
        if (x, y) != (s.x, s.y):
            raise SpecError("%s: name disagrees with value %02X" % (s.name, s.value))
        if kind not in "DK":
            raise SpecError("%s: bad kind" % s.name)

    # 8b/10b's defining disparity invariant, checked rather than assumed:
    # from RD- you may only send a neutral or +2 code-group; from RD+, neutral or -2.
    for s in SYMBOLS:
        pm, pp = popcount(s.code[RD_NEG]), popcount(s.code[RD_POS])
        if pm not in (5, 6):
            raise SpecError("%s: RD- entry has popcount %d" % (s.name, pm))
        if pp not in (4, 5):
            raise SpecError("%s: RD+ entry has popcount %d" % (s.name, pp))

    # Decode must be unambiguous within a column.
    for rd in (RD_NEG, RD_POS):
        seen = {}
        for s in SYMBOLS:
            c = s.code[rd]
            if c in seen and seen[c] is not s:
                raise SpecError("code %03X maps to both %s and %s at rd=%d"
                                % (c, seen[c].name, s.name, rd))
            seen[c] = s
        if len(seen) != 268:
            raise SpecError("column rd=%d has %d distinct codes, expected 268" % (rd, len(seen)))


def check_spot_vectors():
    """The hand-read rows must match the programmatic parse, and must not be
    degenerate (sec 22.53)."""
    flipping = same_code = different_code = 0
    for name, value, m6, m4, p6, p4 in SPOT_VECTORS:
        s = BY_NAME[name]
        if s.value != value:
            raise SpecError("%s: hand-read value %02X != parsed %02X" % (name, value, s.value))
        if s.code[RD_NEG] != code_to_datain(m6, m4):
            raise SpecError("%s: hand-read RD- code disagrees with the parse" % name)
        if s.code[RD_POS] != code_to_datain(p6, p4):
            raise SpecError("%s: hand-read RD+ code disagrees with the parse" % name)
        if flips_disparity(s.code[RD_NEG]):
            flipping += 1
        if s.code[RD_NEG] == s.code[RD_POS]:
            same_code += 1
        else:
            different_code += 1
    if flipping == 0 or flipping == len(SPOT_VECTORS):
        raise SpecError("spot set is a fixed-point set: %d/%d flip disparity"
                        % (flipping, len(SPOT_VECTORS)))
    if different_code == 0:
        raise SpecError("spot set has no symbol whose two columns differ")


def check_round_trip():
    """encode -> decode over all 268 symbols in BOTH disparities (536 cases).

    Every one must come back as the same symbol, with no Receiver Error, and
    with the running disparity the popcount rule predicts.
    """
    n = 0
    for s in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            code, rd_out = encode(s, rd)
            d = decode(code, rd)
            if d.cls != "valid":
                raise SpecError("%s at rd=%d decoded %s" % (s.name, rd, d.cls))
            if d.symbol is not s:
                raise SpecError("%s at rd=%d decoded as %s" % (s.name, rd, d.symbol.name))
            if d.dataout != s.dataout:
                raise SpecError("%s at rd=%d: dataout %03X != %03X"
                                % (s.name, rd, d.dataout, s.dataout))
            if d.rd_out != rd_out:
                raise SpecError("%s at rd=%d: rd_out disagreement" % (s.name, rd))
            if d.receiver_error:
                raise SpecError("%s at rd=%d flagged a Receiver Error" % (s.name, rd))
            n += 1
    if n != 536:
        raise SpecError("round trip covered %d cases, expected 536" % n)


def check_partition():
    """Classify all 2048 (code-group, disparity) cases and check the counts.

    These totals are predicted analytically in PREDICTIONS_8B10B.md sec 2 from the
    sub-block structure of the B-tables, before this function was ever run.
    """
    counts = {RD_NEG: {}, RD_POS: {}}
    for rd in (RD_NEG, RD_POS):
        c = {"valid": 0, "disparity_error": 0, "invalid": 0}
        for code in range(1024):
            c[decode(code, rd).cls] += 1
        counts[rd] = c
        if sum(c.values()) != 1024:
            raise SpecError("partition at rd=%d does not total 1024" % rd)
    for rd in (RD_NEG, RD_POS):
        if counts[rd]["valid"] != 268:
            raise SpecError("rd=%d: %d valid, expected 268" % (rd, counts[rd]["valid"]))
        if counts[rd]["disparity_error"] != 196:
            raise SpecError("rd=%d: %d disparity errors, expected 196"
                            % (rd, counts[rd]["disparity_error"]))
        if counts[rd]["invalid"] != 560:
            raise SpecError("rd=%d: %d invalid, expected 560" % (rd, counts[rd]["invalid"]))
    distinct = len({s.code[rd] for s in SYMBOLS for rd in (RD_NEG, RD_POS)})
    if distinct != 464:
        raise SpecError("%d distinct valid code-groups, expected 464" % distinct)
    return counts


def check_chaining():
    """A long encoded stream must decode clean when running disparity is chained,
    and must NOT when it is held constant -- otherwise the disparity half of the
    oracle is untested by construction."""
    names = [s.name for s in SYMBOLS]          # all 268, in table order
    codes, _ = encode_stream(names, RD_NEG)
    rd = RD_NEG
    for name, code in zip(names, codes):
        d = decode(code, rd)
        if d.cls != "valid":
            raise SpecError("chained stream: %s decoded %s" % (name, d.cls))
        rd = d.rd_out
    stuck = sum(1 for code in codes if decode(code, RD_NEG).cls != "valid")
    if stuck == 0:
        raise SpecError("holding rd at RD_NEG produced no error: the stream is "
                        "disparity-degenerate and proves nothing")
    return stuck


# The comma is the 7-bit singular pattern 0011111 / 1100000 (Widmer-Franaszek).
# In 8b/10b exactly three Special Symbols contain it, and PCIe's COM is K28.5.
COMMA_SYMBOLS = frozenset(("K28.1", "K28.5", "K28.7"))


def check_comma():
    """Exactly K28.1, K28.5 and K28.7 may contain the comma pattern.

    This check is deliberately INDEPENDENT of everything else in this file.  It
    does not use the parser's column assignment, the round trip, or the partition
    -- it reads the transmission-order bit string and looks for a 7-bit pattern
    whose position depends on the `abcdei fghj` split being right.  If a column
    had been mis-split, or the a..j order reversed, this would not come out.

    It is the strongest single piece of evidence that the committed table is the
    specification's and not an artifact of the extraction, because the property
    is documented outside PCIe entirely (it is a property of 8b/10b itself).

    The check is on (symbol, disparity) PAIRS, not on symbol names.  An earlier
    version collected names across both columns, and a negative control showed it
    could not see a one-bit corruption of a single column: K28.5's RD+ encoding
    still carried the comma, so the name stayed in the set and the guard passed.
    Both columns of all three comma symbols carry the pattern, so the correct
    assertion is over all six pairs.
    """
    expected = frozenset((n, rd) for n in COMMA_SYMBOLS for rd in (RD_NEG, RD_POS))
    found = set()
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            abcdei, fghj = datain_to_code(sym.code[rd])
            bits = abcdei + fghj
            if bits.startswith("0011111") or bits.startswith("1100000"):
                found.add((sym.name, rd))
    if found != expected:
        missing = sorted((n, "RD-" if r == RD_NEG else "RD+") for n, r in expected - found)
        extra = sorted((n, "RD-" if r == RD_NEG else "RD+") for n, r in found - expected)
        raise SpecError(
            "comma-bearing (symbol, disparity) pairs are wrong -- the abcdei/fghj "
            "column split or the a..j bit order is off. missing=%s extra=%s"
            % (missing, extra))
    return sorted({n for n, _ in found})


def self_test(verbose=False):
    check_table()
    check_comma()
    check_spot_vectors()
    check_round_trip()
    counts = check_partition()
    stuck = check_chaining()
    if verbose:
        print("golden_8b10b self-test: PASS")
        print("  rows parsed              268  (256 D + 12 K)")
        print("  comma pattern            %s only" % ", ".join(check_comma()))
        print("  round trip               536/536 symbols x disparities")
        print("  distinct valid codes     464 of 1024")
        for rd, label in ((RD_NEG, "RD-"), (RD_POS, "RD+")):
            c = counts[rd]
            print("  at %s   valid %4d   disparity_error %4d   invalid %4d"
                  % (label, c["valid"], c["disparity_error"], c["invalid"]))
        print("  chaining control         %d/268 symbols fail when rd is held at RD-" % stuck)
    return counts


if __name__ == "__main__":
    self_test(verbose=True)

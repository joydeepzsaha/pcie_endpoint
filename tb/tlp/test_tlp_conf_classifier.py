"""Area 5 -- Classifier (TL conformance sweep).

Drives tlp_classifier (combinational) through tb_tlp_comb and asserts the
posted / non-posted / completion routing across the type space, plus the
illegal-encoding rejections (unknown type, 4DW IO/CFG/CPL, over-length,
no-data CPL with nonzero length) -> UNSUPPORTED.

Golden derived from the PCIe request/completion taxonomy.
RTL cited: src/tlp/tlp_classifier.sv:24-71 ; tlp_class_e src/tlp/tlp_pkg.sv:29-34.
"""

import cocotb
from cocotb.triggers import Timer

# tlp_class_e ordinal (tlp_pkg.sv:29-34)
POSTED, NON_POSTED, COMPLETION, UNSUPPORTED = 0, 1, 2, 3

FMT_3DW_NO_DATA = 0b000
FMT_4DW_NO_DATA = 0b001
FMT_3DW_DATA = 0b010
FMT_4DW_DATA = 0b011
TYPE_MEM = 0b00000
TYPE_MEM_LOCK = 0b00001
TYPE_IO = 0b00010
TYPE_CFG0 = 0b00100
TYPE_CFG1 = 0b00101
TYPE_CPL = 0b01010
TYPE_SWAP = 0b01101       # AtomicOp -- present in enum, not classified -> unsupported


async def classify(dut, fmt, typ, length_dw=1):
    dut.fmt.value = fmt
    dut.tlp_type.value = typ
    dut.length_dw.value = length_dw
    dut.address.value = 0
    dut.memory_enable.value = 1
    dut.address_low.value = 0
    dut.byte_length.value = 4
    await Timer(2, units="ns")
    return dict(
        cls=int(dut.class_value.value),
        mem=int(dut.memory_request.value),
        cfg=int(dut.config_request.value),
        cpl=int(dut.completion.value),
        rd=int(dut.read_request.value),
        wr=int(dut.write_request.value),
        unsup=int(dut.unsupported.value),
    )


@cocotb.test()
async def mem_read_non_posted(dut):
    r = await classify(dut, FMT_3DW_NO_DATA, TYPE_MEM)
    assert r["cls"] == NON_POSTED and r["mem"] and r["rd"] and not r["wr"], r


@cocotb.test()
async def mem_write_posted(dut):
    r = await classify(dut, FMT_3DW_DATA, TYPE_MEM)
    assert r["cls"] == POSTED and r["mem"] and r["wr"] and not r["rd"], r


@cocotb.test()
async def mem64_read_non_posted(dut):
    r = await classify(dut, FMT_4DW_NO_DATA, TYPE_MEM)
    assert r["cls"] == NON_POSTED and r["mem"] and r["rd"], r


@cocotb.test()
async def cfg0_read_write(dut):
    r = await classify(dut, FMT_3DW_NO_DATA, TYPE_CFG0)
    assert r["cls"] == NON_POSTED and r["cfg"] and r["rd"] and not r["wr"], r
    w = await classify(dut, FMT_3DW_DATA, TYPE_CFG0)
    assert w["cls"] == NON_POSTED and w["cfg"] and w["wr"] and not w["rd"], w


@cocotb.test()
async def cfg1_is_config(dut):
    r = await classify(dut, FMT_3DW_NO_DATA, TYPE_CFG1)
    assert r["cfg"] == 1 and r["cls"] == NON_POSTED, r


@cocotb.test()
async def io_read_write_not_config(dut):
    r = await classify(dut, FMT_3DW_NO_DATA, TYPE_IO)
    assert r["cls"] == NON_POSTED and r["rd"] and r["cfg"] == 0, \
        f"IO must be non-posted, read, and NOT config_request: {r}"
    w = await classify(dut, FMT_3DW_DATA, TYPE_IO)
    assert w["cls"] == NON_POSTED and w["wr"] and w["cfg"] == 0, w


@cocotb.test()
async def completion_class(dut):
    r = await classify(dut, FMT_3DW_DATA, TYPE_CPL, length_dw=1)
    assert r["cls"] == COMPLETION and r["cpl"] and not r["mem"] and not r["cfg"], r
    n = await classify(dut, FMT_3DW_NO_DATA, TYPE_CPL, length_dw=0)
    assert n["cls"] == COMPLETION and n["cpl"], n


@cocotb.test()
async def unknown_and_lock_unsupported(dut):
    """MEM_LOCK, AtomicOp (SWAP), and an undefined type all -> UNSUPPORTED."""
    for typ in (TYPE_MEM_LOCK, TYPE_SWAP, 0b11000):
        r = await classify(dut, FMT_3DW_NO_DATA, typ)
        assert r["cls"] == UNSUPPORTED and r["unsup"], f"type {typ:#07b}: {r}"


@cocotb.test()
async def overlength_unsupported(dut):
    """length_dw > 1024 -> UNSUPPORTED (classifier.sv:49-52)."""
    r = await classify(dut, FMT_3DW_DATA, TYPE_MEM, length_dw=1025)
    assert r["cls"] == UNSUPPORTED and r["unsup"], r


@cocotb.test()
async def cfg_4dw_illegal(dut):
    """CFG/IO/CPL only use 3DW headers; a 4DW encoding -> UNSUPPORTED."""
    for typ in (TYPE_CFG0, TYPE_IO, TYPE_CPL):
        r = await classify(dut, FMT_4DW_NO_DATA, typ, length_dw=1)
        assert r["cls"] == UNSUPPORTED and r["unsup"] and r["cfg"] == 0 and r["cpl"] == 0, \
            f"4DW type {typ:#07b} must be unsupported: {r}"


@cocotb.test()
async def cpl_nodata_nonzero_length_illegal(dut):
    """A no-data CPL carrying Length!=0 -> UNSUPPORTED (classifier.sv:61-63)."""
    r = await classify(dut, FMT_3DW_NO_DATA, TYPE_CPL, length_dw=5)
    assert r["cls"] == UNSUPPORTED and r["unsup"] and r["cpl"] == 0, r

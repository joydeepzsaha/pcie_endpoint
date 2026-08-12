"""Deterministic packet helpers for the Python Endpoint BFM tests."""

from typing import List

from model import (
    BfmPayload,
    Dllp,
    DllpType,
    LinkEvent,
    LinkEventKind,
    PcieEndpointBfm,
    Tlp,
    TlpFmt,
    TlpType,
    tlp_lcrc,
)


def fc_dllp(
    dllp_type: DllpType,
    header_credits: int = 32,
    data_credits: int = 256,
) -> Dllp:
    return Dllp(
        type=dllp_type,
        header_credits=header_credits,
        data_credits=data_credits,
    )


def dllp_event(dllp: Dllp) -> LinkEvent:
    return LinkEvent(kind=LinkEventKind.DLLP, dllp=dllp)


def tlp_event(tlp: Tlp, sequence: int, corrupt_lcrc: bool = False) -> LinkEvent:
    event = LinkEvent(
        kind=LinkEventKind.TLP,
        tlp=tlp,
        sequence=sequence & 0xFFF,
    )
    event.lcrc = tlp_lcrc(event.sequence, event.tlp)
    if corrupt_lcrc:
        event.lcrc ^= 1
    return event


def memory_read(
    address: int,
    length_dw: int,
    requester_id: int = 0x0100,
    tag: int = 1,
) -> Tlp:
    packet = Tlp()
    packet.header.fmt = (
        TlpFmt.FOUR_DW_NO_DATA
        if address > 0xFFFFFFFF
        else TlpFmt.THREE_DW_NO_DATA
    )
    packet.header.type = TlpType.MEMORY
    packet.header.address = address
    packet.header.length_dw = length_dw
    packet.header.requester_id = requester_id
    packet.header.tag = tag
    packet.header.first_be = 0xF
    packet.header.last_be = 0 if length_dw == 1 else 0xF
    return packet


def memory_write(
    address: int,
    words: List[int],
    requester_id: int = 0x0100,
    tag: int = 0,
) -> Tlp:
    packet = Tlp(payload=list(words))
    packet.header.fmt = (
        TlpFmt.FOUR_DW_DATA
        if address > 0xFFFFFFFF
        else TlpFmt.THREE_DW_DATA
    )
    packet.header.type = TlpType.MEMORY
    packet.header.address = address
    packet.header.length_dw = len(words)
    packet.header.requester_id = requester_id
    packet.header.tag = tag
    packet.header.first_be = 0xF
    packet.header.last_be = 0 if len(words) == 1 else 0xF
    return packet


def config_request(
    write: bool,
    offset: int,
    value: int = 0,
    byte_enable: int = 0xF,
    requester_id: int = 0x0100,
    tag: int = 1,
) -> Tlp:
    packet = Tlp(payload=[value] if write else [])
    packet.header.fmt = (
        TlpFmt.THREE_DW_DATA if write else TlpFmt.THREE_DW_NO_DATA
    )
    packet.header.type = TlpType.CONFIG0
    packet.header.address = offset & 0xFFC
    packet.header.length_dw = 1
    packet.header.requester_id = requester_id
    packet.header.tag = tag
    packet.header.first_be = byte_enable
    return packet


def payload(byte_count: int, seed: int = 0) -> BfmPayload:
    result = BfmPayload(
        words=[0] * ((byte_count + 3) // 4),
        keep=[0] * ((byte_count + 3) // 4),
        beat_count=(byte_count + 3) // 4,
        last=True,
    )
    for index in range(byte_count):
        beat, lane = divmod(index, 4)
        result.words[beat] |= ((seed + index) & 0xFF) << (lane * 8)
        result.keep[beat] |= 1 << lane
    return result


def activate(
    endpoint: PcieEndpointBfm,
    header_credits: int = 32,
    data_credits: int = 256,
) -> None:
    endpoint.set_phy_link_up(True)
    endpoint.tick()
    phases = (
        DllpType.INIT_FC1_P,
        DllpType.INIT_FC1_NP,
        DllpType.INIT_FC1_CPL,
        DllpType.INIT_FC2_P,
        DllpType.INIT_FC2_NP,
        DllpType.INIT_FC2_CPL,
    )
    for dllp_type in phases:
        endpoint.push_link_rx(
            dllp_event(fc_dllp(dllp_type, header_credits, data_credits))
        )
        endpoint.tick()
    for _ in range(4):
        endpoint.tick()
    drain(endpoint)


def drain(endpoint: PcieEndpointBfm) -> List[LinkEvent]:
    events = []
    while True:
        event = endpoint.pop_link_tx()
        if event is None:
            return events
        events.append(event)


def collect_tlps(endpoint: PcieEndpointBfm, cycles: int) -> List[LinkEvent]:
    packets = []
    for _ in range(cycles):
        endpoint.tick()
        for event in drain(endpoint):
            if event.kind == LinkEventKind.TLP:
                packets.append(event)
    return packets

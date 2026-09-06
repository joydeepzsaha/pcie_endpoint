# (Open-Source) PCIe Endpoint Controller — **work in progress**

An open-source PCIe 1.0 (Gen1) endpoint controller in synthesizable SystemVerilog, intended as a
research and teaching platform for high-speed interconnect design and as a practical basis for
FPGA-based PCIe integration.

**Upstream:** this project began as [`isomoye-msu/pcie_datalink_layer`](https://github.com/isomoye-msu/pcie_datalink_layer)
by **Idris Somoye**, and most of the RTL below is his. Development now continues in this repository.

---

## Status

Verification is organised around a **99-target regression gate** whose artifact is byte-compared
between runs; a rung of work is not considered done until the gate reproduces. Layer coverage is
uneven and the honest summary is:

| area | state |
|---|---|
| Transaction Layer, enumeration, Data Link Layer | covered by the gate, spec-cited benches |
| LTSSM | covered, and under active defect repair — several conformance divergences are **open and recorded** |
| PHY (Gen1 TX/RX, 8b/10b, scrambler, ordered sets) | covered, spec-golden vectors from Base 2.1 |
| GTP/GTX/GTH transceiver integration | **not exercised by the gate** — synthesis only |
| x4 and above | **not supported**; several known structural gaps are recorded, not fixed |

⚠️ Open defects are tracked deliberately rather than hidden: some regression rows are **expected to
fail** and are marked `expect_fail`. **A failing row is not necessarily a regression** — check the
tracker before "fixing" one, because several of those rows exist specifically to keep a known
divergence visible.

---

## Repository structure

```
src/       synthesizable RTL
tb/        per-block testbenches (cocotb) and the .core files that wire them
verif/     PyUVM top-level PIPE-based constrained-random verification
docs/      design notes and documentation
example/   Vivado example-project scripts and reference integration
synth/     synthesis scripts and constraints
```

---

## Getting started

⚠️ **Read the two traps first — both silently produce a wrong result rather than an error.**

### Trap 1 — `fusesoc.conf` is per-directory, untracked, and gitignored

There is **no global `fusesoc.conf`** on a normal setup (not `/etc/fusesoc/`, not
`~/.config/fusesoc/`). FuseSoC reads a `fusesoc.conf` **from the current directory**, and this
repository's copy is untracked and ignored (`.gitignore`: `*.conf`), so it never arrives with a clone.

It contains an **absolute path**:

```ini
[library.pcie-endpoint-controller]
location = /absolute/path/to/your/checkout
sync-uri = ./
sync-type = local
auto-sync = true
```

⚠️ **Never copy this file between checkouts.** A second checkout that inherits a conf pointing at the
first will **silently build and test the first checkout** while reporting itself as testing the
second. Always write it fresh, pointing at the checkout you are in.

### Trap 2 — `fusesoc run` exits 0 when nothing ran

`fusesoc run` returns **0** on a cocotb test **failure**, and **also** returns 0 when **zero tests
ran** (a stale build directory yields `make: Nothing to be done for 'all'` and no test table at all).

⚠️ **Never judge a run by `$?`.** Parse the `TESTS=` line; **a run that printed no `TESTS=` line at
all did not test anything.** If you see that, remove the target's build directory
(`rm -rf build/*/<target>`) and re-run.

### Prerequisites

- Python 3, [FuseSoC](https://github.com/olofk/fusesoc) ≥ 2.4.4, [Edalize](https://github.com/olofk/edalize)
- [Verilator](https://github.com/verilator/verilator) (5.x) and cocotb
- Xilinx Vivado — only for synthesis and the GTP/GTX flows
- ⚠️ If the toolchain lives in a conda environment, non-interactive shells will **not** have it on
  `PATH`. Export it explicitly before running anything:

  ```bash
  export PATH="/path/to/conda/envs/<env>/bin:$PATH"
  # FST tracing includes <lz4.h>; without this the build dies with
  # "fatal error: lz4.h: No such file or directory"
  export CPATH="$(dirname "$(command -v fusesoc)")/../include:$CPATH"
  ```

### Clone — the cold-clone checklist

This is the procedure used to prove the regression gate reproduces from a clean checkout. Following
it exactly is the difference between testing your clone and testing something else.

```bash
git clone git@github.com:joydeepzsaha/pcie_gen1.git my_checkout
cd my_checkout

# ⚠️ --force is required; a plain `git submodule update --init` can leave a
# submodule at the wrong revision without failing.
git submodule update --init --force

# ⚠️ WRITE THIS FRESH.  Never copy it from another checkout (Trap 1).
cat > fusesoc.conf <<EOF
[library.pcie-endpoint-controller]
location = $(pwd)
sync-uri = ./
sync-type = local
auto-sync = true
EOF

pip install -r requirements.txt
```

Confirm isolation before trusting any result:

```bash
# must print THIS checkout's path, not another one
grep location fusesoc.conf
# must be absent in a fresh clone -- if present, it came from somewhere else
ls build/ 2>/dev/null
```

### Running a simulation

```bash
fusesoc run --target=<target> <core>
# e.g.
fusesoc run --target=verilate_tlp_parser fusesoc:pcie:tb_tlp
```

Target and core names live in the `.core` files under `tb/`. ⚠️ Targets are **not** interchangeable
between cores — running a target against the wrong core can silently elaborate a different design.

### Synthesis

```bash
fusesoc run --target=synth fusesoc:pcie:pcie_gtp:1.0.0
fusesoc run --target=synth fusesoc:pcie:pcie_gtx:1.0.0
```

---

## Verification approach

Benches are written against the **PCI Express Base Specification 2.1** with the clause and page cited
in the test, so a disagreement between RTL and bench can be adjudicated against the text rather than
against intuition. Where the specification is genuinely silent or implementation-defined, the choice
is stated in the bench as a choice.

Correctness claims are backed by **mutation testing**: a fix is not considered proven until a mutant
restoring the original defect turns the relevant row red, and controls confirm the kill is
attributable to the intended assertion rather than to collateral damage.

---

## Documentation

`docs/` holds the system overview, the PIPE interface description, the Data Link Layer architecture,
and resource/performance notes.

---

## Research and educational contributions

Provides an open-source PCIe endpoint controller aimed at research and education; supports
experimentation with high-speed interconnect design in RTL; demonstrates cocotb/Python-based hardware
verification; and serves communities — RISC-V among them — where PCIe is a commonly missing
peripheral.

---

## License

MIT. ⚠️ **A `LICENSE` file is not currently present in this repository** — the previous README
referred to one that does not exist. Adding it is outstanding.

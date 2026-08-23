#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# stage_s_filelist.sh -- emit the ordered RTL file list for the Stage-S units
# from the SAME .core filesets the simulation gate uses.
#
# ONE SOURCE OF TRUTH.  The synthesis file list is not maintained by hand.
# FuseSoC already resolves the dependency closure in package-before-module order
# for the Verilator targets; this script asks it for that order and strips the
# Verilator-only entries.  The alternative -- a FILES(...) array in the Tcl, as
# synth/s1_ooc.tcl:59-93 still carries for the older units -- is a second owner
# of the ordering, and a second owner drifts.
#
# ---------------------------------------------------------------------------
# WHY THIS IS A SEPARATE SCRIPT FROM THE VIVADO DRIVER
#
# fusesoc lives in the conda `pcie` environment; vivado must run in a shell that
# has NEVER sourced it (mixing the two has bitten this project before).  So the
# list is generated once, in the sim shell, and consumed by four Vivado runs in
# the other shell.  This file is the hand-off.
#
# ---------------------------------------------------------------------------
# Usage (from a shell with fusesoc on PATH -- conda activate pcie):
#
#   ./synth/stage_s_filelist.sh [outdir]
#
# Writes, for BOTH Stage-S units at once:
#   <outdir>/stage_s.f           one absolute path per line, in read order
#   <outdir>/stage_s.f.provenance   git rev, generation command, per-file md5
#
# BOTH UNITS SHARE ONE LIST.  pcie_rc_dl_top and pcie_enum_dl_top both pull
# fileset `rtl` = ::rc_core:1.0.0, whose files: list contains both tops and
# everything under them, so the two closures are byte-identical apart from the
# bench file (RECON_STAGE_S.md D6, measured).  One list, two -top values.
# ---------------------------------------------------------------------------
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd -P)"
OUTDIR="${1:-/var/tmp/kourosh_synth/stage-s}"

# The target used to elicit the closure. Either Stage-S target yields the same
# RTL list; rc_dl_top is named because it is the smaller of the two cones.
TARGET=verilate_rc_dl_top
CORE=fusesoc:pcie:tb_rc

if ! command -v fusesoc >/dev/null 2>&1; then
  echo "FATAL: fusesoc not on PATH. This script runs in the conda pcie env, not the Vivado shell." >&2
  exit 1
fi

mkdir -p "$OUTDIR" || exit 1

# A cold setup. A stale build/ could stage a source file that no longer matches
# the tree, and the whole point of generating the list is that it describes THIS
# tree. `--setup` stops before compiling: it stages sources and writes the .vc.
cd "$REPO" || exit 1
rm -rf "$REPO/build"
echo "== fusesoc run --setup --target=$TARGET $CORE"
fusesoc run --setup --target="$TARGET" "$CORE" >"$OUTDIR/fusesoc_setup.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  echo "FATAL: fusesoc --setup exited $rc; see $OUTDIR/fusesoc_setup.log" >&2
  exit 1
fi

VC="$REPO/build/fusesoc_pcie_tb_rc_1.0.0/$TARGET/fusesoc_pcie_tb_rc_1.0.0.vc"
STAGE="$REPO/build/fusesoc_pcie_tb_rc_1.0.0/$TARGET"
if [ ! -f "$VC" ]; then
  echo "FATAL: expected $VC to exist after --setup" >&2
  exit 1
fi

# The extraction rule.  Source lines in the .vc are relative paths under src/
# ending in .sv or .v; everything else is a Verilator switch, an -LDFLAGS line,
# or waiver.vlt (no extension match).  The single bench file lives under
# src/fusesoc_pcie_tb_rc_1.0.0/ and is the one thing dropped -- synthesis has no
# testbench.
grep -E '^src/.*\.(sv|v)$' "$VC" \
  | grep -v '^src/fusesoc_pcie_tb_rc_' \
  | sed "s|^|$STAGE/|" > "$OUTDIR/stage_s.f"

N=$(wc -l < "$OUTDIR/stage_s.f")
if [ "$N" -lt 50 ]; then
  echo "FATAL: extracted only $N files; the .vc format has changed. Inspect $VC." >&2
  exit 1
fi

# Provenance.  FuseSoC stages COPIES, not symlinks, so the list points into
# build/.  Recording the git rev plus a per-file md5 is what lets a reader prove
# the netlist describes this tree and not a stale staging directory.
{
  echo "# stage_s.f provenance"
  echo "generated_from_repo=$REPO"
  echo "git_rev=$(cd "$REPO" && git rev-parse HEAD)"
  echo "git_dirty=$(cd "$REPO" && git status --porcelain | wc -l)"
  echo "fusesoc_version=$(fusesoc --version 2>&1 | head -1)"
  echo "fusesoc_target=$TARGET"
  echo "fusesoc_core=$CORE"
  echo "vc=$VC"
  echo "file_count=$N"
  echo "# md5  staged_path"
  while IFS= read -r f; do md5sum "$f"; done < "$OUTDIR/stage_s.f"
} > "$OUTDIR/stage_s.f.provenance"

echo "== wrote $OUTDIR/stage_s.f ($N files)"
echo "== wrote $OUTDIR/stage_s.f.provenance"

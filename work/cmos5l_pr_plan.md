# PR plan: sg13cmos5l_stdcell_hv (symlink port of sg13g2_stdcell_hv)

Companion to IHP-Open-PDK PR #1103 (`libs.ref: add sg13g2_stdcell_hv`,
base `dev`, open, mergeable as of 2026-08-18). This second PR makes the
same 84-cell thick-oxide (3.3 V) library usable from the SG13CMOS5L PDK
**without copying a single byte of layout, netlist or timing data**.

## 1. Target, base branch, sequencing

| item | value |
|---|---|
| repo | `IHP-GmbH/ihp-sg13cmos5l` (separate repo, cloned *inside* an IHP-Open-PDK checkout) |
| base branch | `main` (all open PRs there target `main`; note: **not** `dev`) |
| head | `ChipDesign-BV/ihp-sg13cmos5l:sg13cmos5l_stdcell_hv` (fork; repo already has 14 forks, PRs come from forks) |
| commits | DCO sign-off (`git commit -s`), same as #1103 |
| reviewers | simi1505 (Simon Dorrer) and Mauricio-xx are the active maintainers there |

**Hard dependency:** every symlink resolves to
`../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/...`, i.e. into the sibling
IHP-Open-PDK checkout. That path only exists once **#1103 is merged into
`dev`**. The repo's own CI (`.github/workflows/rtl-to-gds.yml`) clones
`IHP-Open-PDK --branch dev` and overlays this repo onto it, so an HV
testcase would fail until then. Consequence: open this PR as a **draft**
that explicitly states "blocked on IHP-Open-PDK#1103", and only mark it
ready when #1103 lands. Dangling symlinks in a standalone clone are
normal here — all 200 existing symlinks in the repo behave the same way.

## 2. Why symlinks are the right mechanism (precedent, not invention)

The repo already carries **200 relative symlinks** into `ihp-sg13g2`,
including a whole library directory:

```
libs.ref/sg13cmos5l_sram      -> ../../ihp-sg13g2/libs.ref/sg13g2_sram
libs.tech/librelane/IHP_rcx_patterns.rules
                              -> ../../../ihp-sg13g2/libs.tech/librelane/openrcx/IHP_rcx_patterns.rules
libs.tech/ngspice/models/*hv* -> ../../../../ihp-sg13g2/libs.tech/ngspice/models/...
libs.tech/klayout/tech/lvs/rule_decks/*.lvs (30+)
libs.tech/klayout/tech/drc/rule_decks/{feol/5_7_thickgateox,beol/5_16_metal1,layers_def}.drc
```

Two of those matter technically, not just stylistically:

* the **HV device models are literally the same files** (`cornerMOShv.lib`,
  `sg13g2_moshv_mod.lib`, `psp103.osdi` … all symlinks to G2), so the
  liberty characterized for #1103 is valid in CMOS5L unchanged — no
  re-characterization is owed;
* `5_7_thickgateox.drc`, `5_16_metal1.drc` and `layers_def.drc` are
  symlinks too, so the thick-oxide and Metal1 rule set the cells were
  signed off against is bit-identical in both PDKs.

## 3. Deliverable tree

12 symlinks + 3 small real files + one 2-line patch. Nothing is copied.

### 3.1 `libs.ref/sg13cmos5l_stdcell_hv/` (real dir, 10 links)

LibreLane derives every view path from `$STD_CELL_LIBRARY`
(`libs.ref/$SCL/gds/$SCL.gds`, …), so a single directory symlink is *not*
enough — the files must carry CMOS5L names. Per-file symlinks give that
for free:

```
gds/sg13cmos5l_stdcell_hv.gds                  -> ../../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds
lef/sg13cmos5l_stdcell_hv.lef                  -> ../../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/lef/sg13g2_stdcell_hv.lef
lib/sg13cmos5l_stdcell_hv_typ_3p30V_25C.lib    -> ../../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib
spice/sg13cmos5l_stdcell_hv.spice              -> ../../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/spice/sg13g2_stdcell_hv.spice
cdl/sg13cmos5l_stdcell_hv.cdl                  -> ../../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/cdl/sg13g2_stdcell_hv.cdl
verilog/sg13cmos5l_stdcell_hv.v                -> ../../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/verilog/sg13g2_stdcell_hv.v
sym                                            -> ../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/sym
sch                                            -> ../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/sch
doc                                            -> ../../../ihp-sg13g2/libs.ref/sg13g2_stdcell_hv/doc
lef/sg13cmos5l_tech.lef                        -> ../../sg13cmos5l_stdcell/lef/sg13cmos5l_tech.lef
```

`sym/`, `sch/` and `doc/` are whole-directory links: their contents are
per-cell files whose names must equal the cell names anyway, so nothing
would be gained by 169 individual links.

**The one file that must NOT come from G2** is the tech LEF. #1103 copies
G2's `sg13g2_tech.lef` into the HV lib because the PDK config globs
`libs.ref/$SCL/lef/sg13g2_tech.lef`. CMOS5L's config expects
`libs.ref/$SCL/lef/sg13cmos5l_tech.lef` and the CMOS5L stack is
**M1-M4-TM1** (no Metal5, Via4, TopMetal2, TopVia2). Linking the CMOS5L
tech LEF from the LV library is both correct and self-maintaining.

### 3.2 `libs.tech/librelane/sg13cmos5l_stdcell_hv/` (7 links + 2 real files)

```
latch_map.v  mux2_map.v  mux4_map.v  tribuff_map.v  sdfbbp_map.v
synth_exclude.cells  pnr_exclude.cells
        -> ../../../../ihp-sg13g2/libs.tech/librelane/sg13g2_stdcell_hv/<same name>
tracks.info    REAL — copy of sg13cmos5l_stdcell/tracks.info
config.tcl     REAL — the only authored file of substance
```

The techmaps and exclude lists reference cell names (`sg13g2_hv_*`),
which are identical in both PDKs → symlink.

`tracks.info` must **not** be symlinked: the G2 grid lists Metal5 and
TopMetal2 and uses different pitches (M1 X 0.48, M3 X 0.48, TM1 3.28)
where CMOS5L uses M1 X 0.42, M2 0.48/0.48, M3 0.42, M4 0.48, TM1 2.28.
Both PDKs route `RT_MIN_LAYER = Metal2` upward, so Metal1 remains
pins/rails only, but the grid itself has to be the CMOS5L one.

`config.tcl` = the HV SCL config from #1103 with three deltas:

```tcl
# 1. the LIB dict lives in the SCL config in this PDK (unlike G2, where it
#    is PDK-level) -> no patch to libs.tech/librelane/config.tcl is needed
set ::env(LIB) [dict create]
dict set ::env(LIB) nom_typ_3p30V_25C "\
    $::env(PDK_ROOT)/$::env(PDK)/libs.ref/$::env(STD_CELL_LIBRARY)/lib/sg13cmos5l_stdcell_hv_typ_3p30V_25C.lib\
    $::env(PDK_ROOT)/$::env(PDK)/libs.ref/sg13cmos5l_io/lib/sg13cmos5l_io_typ_1p5V_3p3V_25C.lib\
"
set ::env(STA_CORNERS)   "nom_typ_3p30V_25C"
set ::env(DEFAULT_CORNER) "nom_typ_3p30V_25C"
set ::env(TIMING_VIOLATION_CORNERS) "*typ*"
# 2. override the PDK-level 1.20 V core voltage
set ::env(VDD_PIN_VOLTAGE) "3.30"
# 3. everything else verbatim from #1103: PLACE_SITE CoreSiteHV 0.48 x 7.14,
#    sg13g2_hv_* driving/tie/fill/decap/diode/CTS/tristate cells,
#    FP_PDN_RAIL_WIDTH 0.44, SYNTH_*_MAP paths under $STD_CELL_LIBRARY.
```

**To verify in the smoke test:** that the SCL config is sourced *after*
the PDK config so `VDD_PIN_VOLTAGE 3.30` wins over the PDK-level `1.20`.
If it does not, fall back to the #1103 approach — an
`if { $::env(STD_CELL_LIBRARY) eq "sg13cmos5l_stdcell_hv" }` block in
`libs.tech/librelane/config.tcl`. Everything else in that PDK-level file
(PDN layers, `MACRO_BLOCKAGES_LAYER`, `GRT_LAYER_ADJUSTMENTS`,
`RT_MIN/MAX_LAYER`) is already stack-correct for CMOS5L and must stay
untouched.

### 3.3 KLayout + xschem (parity with #1103)

* `libs.tech/klayout/tech/pymacros/sg13cmos5l_stdcell_hv.lym` — REAL file
  (the macro hardcodes the library name and a PDK-relative GDS path, so a
  symlink to the G2 `.lym` would look for `sg13g2_stdcell_hv` under
  `ihp-sg13cmos5l/libs.ref`). Same maintainer question as in #1103:
  upstream registers no stdcell GDS as a KLayout library today, so this
  file is optional — offer to drop it if they prefer.
* `libs.tech/xschem/xschemrc` — the same 2-line additive patch as #1103,
  pointed at the CMOS5L paths: append
  `libs.ref/sg13cmos5l_stdcell_hv/sym/xschem` to `XSCHEM_LIBRARY_PATH`
  and set `::SG13G2_HV_SCH` to `libs.ref/sg13cmos5l_stdcell_hv/sch/xschem`.
  Note this PDK keeps its LV stdcell symbols in
  `libs.tech/xschem/sg13cmos5l_stdcells/` as **renamed real files**, so
  the HV symbols coming in under `libs.ref/` is a deliberate divergence
  worth one sentence in the PR body.

## 4. The naming decision (call it out, do not bury it)

Symlinks preserve the **cell names**: the CMOS5L library ships cells
called `sg13g2_hv_inv_1`, not `sg13cmos5l_hv_inv_1`. That is inconsistent
with `sg13cmos5l_stdcell`, whose cells were renamed with
`scripts/rename_cells.py` (`sg13g2_` → `sg13cmos5l_`).

Recommendation: **keep the G2 names**, and say why in the PR body —

* the layout, netlist and timing are the *same artifact*, characterized
  against model files that CMOS5L itself symlinks from G2; renaming would
  fork 3.5 MB of views (GDS + LEF + liberty + spice + cdl + verilog + 169
  sym/sch files) that then drift from #1103 on every future revision;
* precedent: `sg13cmos5l_sram` keeps its `RM_IHPSG13_*` cell names;
* no collision risk with `sg13cmos5l_*` cells in a mixed design;
* if the maintainers want consistency, the rename belongs in the
  build/compile migration script the repo README says is being developed
  — `rename_cells.py` already does the GDS half. Offer to supply the
  matching LEF/liberty/spice/cdl/verilog/sym renamer as a follow-up so
  it is generated, never hand-maintained.

## 5. Verification to run before opening (nothing is inherited)

The CMOS5L decks are *not* identical to G2's — 19 rule-deck files are
local copies rather than symlinks — so the #1103 signoff does not carry
over automatically. Re-run, on a checkout with #1103's branch applied:

1. **Forbidden-layer check** (`3_2_forbidden_cmos5l.drc`). Already
   pre-verified here: the HV GDS uses only Activ 1/0, GatPoly 5/0,
   Cont 6/0, Metal1 8/0+8/2+8/25, Metal2 10/0+10/2+10/25 (3 shapes),
   Via1 19/0 (3 shapes), pSD 14/0, DigiBnd 16/0, NWell 31/0,
   ThickGateOx 44/0, TEXT 63/0, Recog.diode 99/31, prBoundary 189/4 —
   **none** of Metal5 / Via4 / TopMetal2 / TopVia2 / MIM / Vmim /
   nBuLay / TRANS. Expect 0 CMOS5L.FORB.* violations.
2. **KLayout modular + maximal decks** (`ihp-sg13cmos5l.drc`,
   `rule_decks/sg13cmos5l_maximal.drc`) on the single-cell array and the
   abutted array from `work/drc/`. Watch specifically:
   `3_1_offgrid` / `3_2_angle` (the CMOS5L copies lack G2's exclusion of
   DigiBnd/Recog/TEXT and the circular-polygon carve-out — if markers
   appear on those layers it is a deck gap, file it like #1106/#1107
   rather than changing layout), `7_4_pin`, `5_14_cont`, `5_17_metaln`.
   Note NW.c1/NW.c1.dig is absent from the CMOS5L nwell deck too (only
   NW.b/NW.b1/NW.f1), exactly as in G2 — the rev.3 well fix is still
   covered only by Magic.
3. **KLayout LVS** with `libs.tech/klayout/tech/lvs/sg13cmos5l.lvs` +
   `run_lvs.py`, all 84 cells against the spice view. The MOS
   extraction/derivation decks are symlinks from G2, so 84/84 is the
   expectation; netgen's `ihp-sg13cmos5l_setup.tcl` already lists
   `sg13_hv_nmos` / `sg13_hv_pmos`.
4. **Magic** with `ihp-sg13cmos5l.tech` — best-effort; the PDK config
   itself says Magic support is incomplete for CMOS5L
   (`PRIMARY_GDSII_STREAMOUT_TOOL = klayout`). Report it as such;
   do not gate the PR on it.
5. **OpenSTA** read of the symlinked liberty + `iverilog` of the verilog
   view (self-contained: no UDP primitives, so `sg13cmos5l_udp.v` is not
   needed).
6. **LibreLane end-to-end**: the counter from
   `ihp-sg13g2-ams-chip-template/macros/counter` with `PDK=ihp-sg13cmos5l`,
   `STD_CELL_LIBRARY=sg13cmos5l_stdcell_hv`, plus the design-level
   `SYNTH_EXTRA_MAPPING_FILE` line if scan flops are wanted. Compare
   against the same design on `sg13cmos5l_stdcell`.
7. **`libs.qa/stdcells/check_abutment.py`** on the HV GDS (that QA hook
   exists in this repo; #1103 has no equivalent gate).
8. **git visibility** — reuse `verify_tracked()` from
   `work/make_pdk_pr.py` (`git check-ignore --stdin --no-index`).
   The CMOS5L root `.gitignore` has no `*.spice` rule, so the #1103 trap
   does not repeat here, but the guard is free. Extra care for symlinks:
   confirm `git ls-files -s` shows mode `120000` for all 17 links, i.e.
   they were committed as links and not dereferenced into blobs.

## 6. Automation

Add `work/make_cmos5l_pr.py` next to `make_pdk_pr.py`, taking
`--pdk <IHP-Open-PDK checkout>` and operating on
`<pdk>/ihp-sg13cmos5l`. It should: create the two directories, create
every symlink with `os.symlink` using the **relative** targets above,
write `tracks.info` (copied from the LV SCL) and `config.tcl`, write the
`.lym`, apply the idempotent xschemrc patch, then run `verify_tracked()`
and a link-resolution check (`Path.resolve(strict=True)` on all 17
links). Keep it idempotent like `make_pdk_pr.py` so revisions are cheap.

## 7. PR body outline

1. What: 84 thick-oxide 3.3 V cells available in SG13CMOS5L as symlinks
   into `ihp-sg13g2` — 0 bytes of duplicated layout/timing data.
2. Blocked on IHP-Open-PDK#1103 (draft until it merges).
3. Table of the 17 symlinks + 3 real files + 1 patched file.
4. Why symlinks: the HV models, thick-oxide and Metal1 decks are already
   shared this way; single source of truth with #1103.
5. Verification results table (§5), including the "no forbidden layer"
   evidence and any deck gaps found.
6. Open questions for the maintainers:
   * cell naming (`sg13g2_hv_*` kept — rename in the migration script?);
   * the KLayout `.lym` (same question as #1103, drop if unwanted);
   * IO liberty paired with the 3.3 V core corner
     (`sg13cmos5l_io_typ_1p5V_3p3V_25C.lib` is the closest existing file;
     none is characterized for a 3.3 V core) — same open item as #1103;
   * should `rtl-to-gds.yml` gain an HV matrix entry, given the testcases
     repo is `Mauricio-xx/testcases-cmos5l-ihp` and would need a config?

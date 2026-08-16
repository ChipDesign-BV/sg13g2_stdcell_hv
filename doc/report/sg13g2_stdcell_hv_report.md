---
title: "sg13g2_stdcell_hv — Generation of a Thick-Oxide (3.3 V) Standard Cell Library"
subtitle: "IHP SG13G2 open PDK · derivation, all views, verification and physical sign-off"
author:
  - "Koen Van Caekenberghe, Ph.D."
  - "ChipDesign B.V."
  - "[info@chipdesign.be](mailto:info@chipdesign.be)"
date: "2026-08-16 (rev. 3, condensed: tie cells, shared-rail contact fix, P&R validation)"
logo: "ChipDesign_logo.png"
---

# Scope and result

The IHP SG13G2 open PDK ships no 3.3 V standard cells: its thick-oxide
devices appear only in the `sg13g2_io` pad ring. `sg13g2_stdcell_hv` fills
that gap — **all 84 cells** of `sg13g2_stdcell` rebuilt on `sg13_hv_nmos` /
`sg13_hv_pmos`, same topology, pin names and pin order, named `sg13g2_hv_*`
so both libraries coexist in one netlist.

| Deliverable | Coverage | Status |
|---|---|---|
| SPICE netlist (`spice/`) | 84 cells, 924 devices | verified against 3 independent views |
| CDL netlist (`cdl/`) | 84 cells + 2 tie cells | LVS reference, all 68 drawn cells match |
| Verilog (`verilog/`) | 84 modules | shared `ihp_*` UDPs, deliberately not duplicated |
| xschem symbols / schematics | 84 + gallery sheet | netlist-equivalence proven |
| GDS layout (`gds/`) | 68 cells (66 retargeted + 2 tie cells built here) | **DRC clean, LVS clean** |
| LEF abstracts (`lef/`) | 68 macros + `CoreSiteHV` site | generated from the GDS, pin sets verified against CDL |
| Liberty NLDM (`lib/`) | 66 cells, 600 timing tables | combinational + sequential; areas from layout |

Physical sign-off, one fixed invocation of the PDK's own klayout decks — on
the abutted two-row array and on the stricter **shared-rail array** (rows at
the true 7.14 µm pitch, mixed and mirrored vertical neighbours — what a
placed block actually produces):

| Check | This library | IHP thin-oxide control (same harness) |
|---|---|---|
| DRC, cell rules | **0** | 0 |
| DRC, cell rules, shared-rail mixed array | **0** | — |
| DRC, chip-level metal density | 7 | 6 |
| LVS | **68 / 68 match** | fill cells fail identically without the documented relaxation |

The density items are harness properties, not cell defects: metal density is
a check on a *filled* die, and the one differing count (`M1.j`, min 35 %
Metal1) reads 35.0 % over the padded array's bounding box against 37.1 %
over the actual cell area (control: 45.2 %).

The library has also carried a real block: two variants of the `spi_slave`
IP placed and routed through LibreLane/OpenROAD at 100 MHz pass the full
IHP signoff deck — zero geometry violations (section 6).

---

# The device transform

| | thin oxide | thick oxide |
|---|---|---|
| device model | `sg13_lv_nmos` / `sg13_lv_pmos` | `sg13_hv_nmos` / `sg13_hv_pmos` |
| gate length | 130 nm | **450 nm** (`Gat.a3` minimum) |
| NMOS width | — | unchanged |
| PMOS width | — | **× 2.40**, snapped per finger to the 5 nm grid |
| `as`/`ad`/`ps`/`pd` | — | recomputed from device geometry |
| supply | 1.2 V | 3.3 V |

Deliberate long-channel devices (decap 1.0 µm, `sighold` 700 nm,
`dlygate4sd3_1` 500 nm) keep their lengths; 914 devices moved to 450 nm.
The antenna cell is unchanged apart from its name (junction diodes).

**Why × 2.40.** The thin-oxide library is sized for a centred switching
threshold ($V_m/V_{DD} = 0.5046$ at $W_p/W_n = 1.5135$), not drive match.
At 3.3 V / 450 nm the PMOS is far weaker (219 vs 533 µA/µm) and the same
$V_m$ needs $W_p/W_n = 3.63$, i.e. $K_p = 3.63/1.5135 = 2.40$ on every
PMOS with every NMOS untouched — preserving each cell's internal stack
ratios. Across the library's 0.3–17.9 µm width range the required ratio
stays within ±5 % of 2.40 (`work/vm_sweep.py`, `work/ratio_check.py`).

**Parasitics** follow the vendor deck's geometry formulas; before any
generation they were validated by recomputing all 924 thin-oxide devices
(worst relative error $3.75\times10^{-4}$, the vendor's four printed
digits). The generator refuses to run if this validation fails.

**Cost**, measured on `inv_1` (`work/fo4.py`): input capacitance 2.67 →
5.87 fF (2.20×), FO4 delay 53.6 → 142.4 ps (2.66×). The thick-oxide NMOS
delivers *more* current per micron at 3.3 V than the thin-oxide at 1.2 V
(533 vs 391 µA/µm) — the loss is capacitance, not drive.

---

# The views

All netlist views are re-emitted from one internal model by
`work/gen_hv_lib.py`, so a device cannot silently diverge between views.

* **`spice/`** — 84 subckts, 924 PSP103 devices (OSDI/ngspice); widths
  synchronised to the drawn layout.
* **`cdl/`** — the same subcircuits as `M`-cards with `*.PININFO`, the LVS
  reference; compared field-by-field against SPICE by `verify_sch.py`.
* **`verilog/`** — 84 modules; deliberately no copy of `sg13g2_udp.v` (the
  `ihp_*` UDPs are shared — a second copy would collide).
* **`sym/`, `sch/`** — 84 symbols (thin-oxide drawn geometry, thick-oxide
  netlist prefix, `$::SG13G2_HV_SCH` resolution) and 84 schematics plus a
  generated gallery sheet; three-view consistency proven on all 924
  devices.
* **`gds/`** — 68 cells: 66 by 1-D retarget (section 4), tie cells built
  by `work/gen_tie_cells.py`. Uniform 7.140 µm row height (17 tracks),
  every width a 0.48 µm site multiple, all 5 758 contact/via cuts exactly
  0.16 × 0.16 µm, every rail tap on the site-centred 0.48 µm grid
  (`work/fix_rail_contacts.py`, section 6).
* **`lef/`** — 68 macros + `CoreSiteHV`, generated from the GDS: pins from
  the pin datatypes labelled by contained text, OBS = drawn metal minus pin
  geometry, antenna values recomputed from the netlist (the thin-oxide
  numbers are wrong for 3.5× longer gates). Parsed back with klayout and
  pin sets verified against the CDL.
* **`lib/`** — Liberty NLDM at 3.3 V / 25 °C typical (section 7).

---

# Layout generation

Hand-drawn 2-D layout cannot be regenerated by placement, but it can be
**1-D retargeted**: monotone piecewise-linear coordinate maps applied to
every vertex preserve topology, so connectivity survives by construction
(`work/layout_retarget.py`). The engineering is in the breakpoints and the
exceptions:

* **x-map**: gates widen 0.13 → 0.45 µm about their centres; contacted
  poly pitch 0.48 → 0.80 µm. One accepted consequence: `dlygate4sd2_1`
  staggers two gates at overlapping x, so its PMOS lands at a legal
  0.625 µm, carried consistently into every netlist view.
* **y-map**: PMOS band × 2.40 plus three channel inserts for the
  thick-oxide clearances (`NW.d1.dig` 0.215 µm, `pSD.j1` 0.100 µm,
  `pSD.i1` rail insert 0.430 µm), derived library-wide so every cell keeps
  one row height.
* **PMOS diffusion** is re-emitted per connected slab piece with channel
  slabs frozen — the only scheme that keeps exact 5 nm-grid device widths
  without merging, collapsing or renaming devices (each alternative was
  tried and caught by LVS or `Act.*` rules).
* **Cut layers are translated, never scaled**; contacts are re-tiled inside
  the new Activ at 0.36 µm pitch (`Cnt.b1` array spacing), grouped by
  polygon.
* **ThickGateOx** is drawn on the cell boundary grown 0.27 µm in x and
  0.42 µm in y — the y-margin proven by the N-row edge experiment (the
  TGO.a count stays 2 for any N and moves with the outer edge).
* **Five Metal1 re-routes** (`M1E_EDITS` in the generator) resolve the
  `M1.e` wide-metal gaps the retarget manufactures; each edit is verified
  in code (polygon count, `M1.a/b/c1`, 5 nm grid).
* **Netlist ↔ layout sync**: the drawn width is authoritative;
  `work/sync_netlist_widths.py` brings SPICE and CDL to the drawn geometry
  per *finger* and recomputes parasitics.
* **Site and tracks**: `TRACK_PAD` stretches the mid-cell dead zone to make
  exactly 17 horizontal 0.42 µm tracks; `pad_to_site` pads each width to
  the 0.48 µm site (13.75 µm total across the library). Mean cell area is
  **2.87×** the thin-oxide library (median 2.83, range 1.89–4.21).

---

# Functional verification

| Suite | Coverage | Result |
|---|---|---|
| `verify_logic.py` | 60 combinational cells, 452 vectors, both libraries in one deck | **PASS** |
| `verify_seq.py` | 16 stateful cells, 400 clocked samples | **PASS** |
| `verify_sch.py` | 84 schematics + CDL vs SPICE, 924 devices field-by-field | **PASS** |

The thin-oxide library is the golden reference — the transform changed
devices, never logic. The 12 high-impedance states of the tri-state cells
are exercised; illegal set/reset combinations are excluded rather than
counted as passes; both suites were re-run on the final, shipped netlists.

---

# Physical sign-off

**Methodology.** Cells are checked in abutted context, never standalone.
Two harnesses: `work/make_drc_top.py` (every cell in its own column,
mirrored second row at the padded bbox pitch) for cell-internal rules, and
`work/make_shared_rail_rows.py` — rows at the true 7.14 µm pitch,
orientations N/S/FS, rotated cell order per row, cells advanced by LEF
width — for everything only a placed block exhibits. Measurement rules,
each bought with a wrong conclusion: one fixed runner invocation (counts
from different flag sets are not comparable), diagnosis from flat
`klayout.db` rule replication (deep-mode marker coordinates mis-attribute
cells), and the IHP thin-oxide library run through the identical harness as
control. Pass/fail is parsed from the report database, never the exit code.

**DRC.** 781 raw violations after the first retarget were driven to zero
cell-rule items (density-only residue, same class as the control). One
defect class survived the original harness because it could not express it:
the retarget left each cell's **rail-tap contacts** at cell-specific x, and
in a placed block — where *different* cells share every rail — partially
overlapping taps merged into 0.19–0.32 µm bars: ~19 000 `Cnt`/`CntB`
markers on the first `spi_slave` signoff. `work/fix_rail_contacts.py`
re-tiles every rail tap onto the site-centred 0.48 µm grid, which both the
FS row flip and placement's x-mirror preserve, with in-code guards for
implant polarity, enclosures, gate clearance, contact spacing and tap
continuity (1 134 → 1 810 rail contacts). Full analysis with figures: the
companion report *The Shared-Rail Contact Clash in sg13g2_stdcell_hv*
(`shared_rail_contact_fix.pdf`, distributed alongside the library rather
than inside it).

**LVS.** All 68 drawn cells match, re-run in full after the re-tiling. The
four device-less `fill_*` cells need the runner's own
`--ignore_top_ports_mismatch` relaxation — IHP's own fill cells fail the
identical flow the same way. LVS caught five defect classes dimensional
checks could not (merged channels, collapsed notch devices, mis-paired
fingers, a dropped substrate tie, stale diode geometry), which is why the
per-cell sweep runs after every layout change.

**Block-level validation.** The `spi_slave` IP, in two variants, was
synthesised, placed and routed with this library through
LibreLane/OpenROAD at 100 MHz on ~354 × 400 µm dies. Both close timing
with zero setup/hold violations at the characterised corner, pass routing
DRC, antenna and Netgen LVS in the flow, pass gate-level simulation of the
routed netlist (all four SPI modes on the all-modes variant), and pass the
**full IHP signoff deck** with zero geometry violations — only the 8
chip-level density/filler markers a filled die resolves at tapeout. The
flow settings this takes (flip-flop mapping onto `sdfbbp_1`, excluded
cells, Metal1 routing, rails-only fillers) are documented in the
`spi-slave-ihp` repository.

---

# Liberty characterisation

`lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib` is produced with **CharLib**
against the shipped, layout-synchronised SPICE netlist on the PSP103/OSDI
models — 25 839 combinational simulations plus a 2 962-task sequential
run: 600 delay/slew tables over 66 cells (52 combinational, 9 flip-flops,
5 latches), none empty. Grids are the thin-oxide grids rescaled by the
measured 2.66× delay / 2.20× capacitance ratios; boolean functions are
translated from the thin-oxide Liberty and checked by truth-table
equivalence. Stock CharLib needed five committed tool workarounds (OSDI
shim, `ngspice-shared` backend, case-insensitive supply lookup, Liberty
syntax post-pass) and — for sequential cells, which stock CharLib cannot
characterise at all — custom clk→Q and setup/hold-bisection procedures
with a c2q-degradation pass criterion (`work/seq_delay_procedure.py`).

The shipped file is verified **as data** by `work/verify_lib.py`:
structure (600/600 tables populated), cross-view (all pins exist in the
CDL), physical (every `area` equals the drawn boundary to 1 nm²),
monotonicity along the load axis (1 931/1 932 series, one documented
pessimistic waiver: `xnor2_1` glitch latching), input capacitance against
an independent both-rails measurement (6.44 vs 5.87 fF, 9.7 % — this
check caught a 6.8–7.5× Miller defect in CharLib's default procedure),
and sequential arcs (14/14 cells: delay + setup + hold present, nothing
pinned at search bounds). A hand-written transient at a table corner
agrees to 0.3 %.

An independent characteriser, **lctime**, was run over eight cells on the
same grids and models: in the region STA exercises (real loads, slews
< 1 ns) the two agree to a median 2.9 % on delays and 0.0 % on
transitions; every disagreement region traces to a stimulus convention,
and a direct measurement sides with the shipped table (+0.15 % vs −19 %
at the probe point). lctime's input capacitance (+52 %) also corroborates
validating Cin against a direct measurement, not a characteriser.

Excluded from the Liberty, by configuration and with stated reasons: the
device-less cells, `tiehi`/`tielo`, the statetable clock gates, and the 6
tri-state cells (CharLib cannot express high-impedance outputs).

---

# Verification summary

| Check | Method | Scope | Result |
|---|---|---|---|
| Parasitic formulas | recompute vendor `as/ad/ps/pd` | all 924 thin-oxide devices | PASS, worst error 3.75×10⁻⁴ |
| Combinational logic | ngspice vs thin-oxide golden | 60 cells, 452 vectors, 12 high-Z states | **PASS** |
| Sequential logic | ngspice, clocked walk from reset | 16 stateful cells, 400 samples | **PASS** |
| Three-view consistency | symbols vs SPICE vs CDL | 84 cells, 924 devices | **PASS** |
| DRC, padded array | PDK deck, fixed invocation | 68 drawn cells | **0 cell rules**; 7 density items |
| DRC, shared-rail array | same deck, true-pitch mixed/mirrored rows | 68 cells × 4 rows | **0 cell rules**; density only |
| DRC control | identical harness on IHP `sg13g2_stdcell` | 84 cells | 0 cell rules, 6 density |
| LVS | PDK deck, per cell, after the rail re-tiling | 68 cells vs CDL | **68/68** |
| LEF | klayout parse-back + pin sets vs CDL | 68 macros | PASS, on-grid |
| P&R block validation | LibreLane `spi_slave` ×2 + full signoff deck | ~354 × 400 µm, 100 MHz | all clean; signoff **0 geometry violations**, 8 density markers |
| Liberty structure/views/areas | `verify_lib.py` 1–3 | 66 cells | PASS, areas exact to 1 nm² |
| Liberty monotonicity | `verify_lib.py` 4 | 1 932 delay series | 1 931 + 1 documented waiver |
| Liberty Cin | vs both-rails reference | `inv_1` | 6.44 vs 5.87 fF (9.7 %) |
| Liberty delay point-check | hand-written transient | table corner | 0.3 % |
| Independent characteriser | lctime, 8 cells, 3 132 points | STA region | median 2.9 % / 0.0 % |
| Sequential arcs | `verify_lib.py` 6 | 14 flip-flops/latches | **14/14 clean** |
| Site geometry | boundary scan | all 68 cells | 7.140 µm, widths on 0.48 µm site |

---

# Known limitations

* **16 cells have no layout** — eight D-flip-flop variants run NMOS Activ
  to the channel cut, eight others run PMOS Activ into the VDD rail;
  neither scales at a shared row height. All have full netlist, schematic,
  symbol and Verilog views. (`tiehi`/`tielo`, once on this list, were
  rebuilt by `work/gen_tie_cells.py`.)
* **P&R needs non-standard flow settings** — flip-flop mapping onto
  `sdfbbp_1`, an excluded-cell list, Metal1 routing for the off-grid pins,
  rails-only fillers (see the `spi-slave-ihp` flow configuration).
* **The 6 tri-state cells carry no Liberty timing**; they are
  simulation-verified.
* **One corner** (typical, 3.3 V, 25 °C); sequential leakage is a
  single-settled-state number; the delay cells' ratios shift with the
  450 nm minimum; the decaps store less per unit area.
* **Not silicon-proven, and not independently reviewed.**

---

# Reproducing the library

```sh
cd /foss/designs/sg13g2_stdcell_hv/work

python3 gen_hv_lib.py            # netlists, schematics, symbols, Verilog
python3 gen_gallery.py           # gallery sheet
python3 layout_retarget.py       # gds/ (66 cells; prints the 16 skips)
python3 gen_tie_cells.py         # + tiehi / tielo
python3 fix_rail_contacts.py     # rail taps onto the site-centred grid
python3 sync_netlist_widths.py   # SPICE + CDL follow the drawn geometry
python3 gen_lef.py               # lef/ (CoreSiteHV + 68 macros)
python3 make_drc_top.py          # padded two-row DRC context
python3 make_shared_rail_rows.py # shared-rail mixed-row DRC context

python3 verify_logic.py; python3 verify_seq.py; python3 verify_sch.py
./run_lvs.sh                     # per-cell LVS, 68/68
# DRC: PDK run_drc.py on drc/drc_top.gds and drc/shared_rail.gds

./run_charlib.sh ../lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib
# sequential cells via charlib_patched.py, then:
python3 merge_lib.py ../lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib <seq.lib>
python3 seq_leakage.py
python3 verify_lib.py            # gates the shipped Liberty as data
python3 lctime_compare.py        # independent characteriser cross-check
```

Every number in this report is reproducible from these scripts; the
`work/` directory and the `README.md` are the provenance of record.

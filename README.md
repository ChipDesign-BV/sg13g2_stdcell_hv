# sg13g2_stdcell_hv — thick-oxide (3.3 V) standard cells for IHP SG13G2

The IHP SG13G2 open PDK ships one standard cell library, `sg13g2_stdcell`,
built entirely from the 1.2 V thin-oxide devices (`sg13_lv_nmos` /
`sg13_lv_pmos`). The 3.3 V thick-oxide devices appear only inside the
`sg13g2_io` pad ring, which is not a standard cell library — it has 22 macros,
all pads, fillers and a corner, and nothing you can synthesise and place.

This library fills that gap: all 84 cells of `sg13g2_stdcell`, rebuilt on the
thick-oxide devices, with the same topology, the same pin names and the same
pin order. Layout covers 66 of the 84 cells, and those 66 are **DRC clean and
LVS clean** against the PDK's own klayout decks (the remaining DRC report
lines are chip-level metal-density rules that only apply to a filled die —
see the DRC result section) — placed on a 17-track site with LEF
abstracts. See [Layout](#layout) and
[What this library is not](#what-this-library-is-not) for what is still
missing: 18 cells have no GDS.

The cells are named `sg13g2_hv_*` and coexist with the thin-oxide library, so
1.2 V and 3.3 V logic can appear in one netlist.

## The transform

Applied to every logic device in all 84 cells:

| | thin oxide | thick oxide |
|---|---|---|
| device model | `sg13_lv_nmos` / `sg13_lv_pmos` | `sg13_hv_nmos` / `sg13_hv_pmos` |
| gate length | 130 nm | **450 nm** (DRC `Gat.a3` minimum for the 3.3 V FET) |
| NMOS width | — | unchanged |
| PMOS width | — | **× 2.40**, snapped per finger to the 5 nm grid |
| `as` / `ad` / `ps` / `pd` | — | recomputed from the device geometry |
| supply | 1.2 V | 3.3 V |

Gate lengths already at or above 450 nm are left alone, because they were
chosen deliberately rather than set by the minimum: the `decap_4` / `decap_8`
MOS capacitors (1.0 µm), the `sighold` keeper devices (700 nm), and
`dlygate4sd3_1` (500 nm). 914 devices had their length raised; the delay cells
`dlygate4sd2_1` (180/250 nm) and `o21ai_1` (150 nm) were below the thick-oxide
minimum and had to move up to 450 nm, which changes their delay ratio relative
to the thin-oxide versions.

`sg13g2_hv_antennanp` is unchanged apart from its name — it contains
`dantenna` / `dpantenna` junction diodes, not MOSFETs, and gate oxide
thickness does not apply to them.

### Why PMOS × 2.40

The thin-oxide `inv_1` uses Wp/Wn = 1.12/0.74 = 1.5135. Simulation shows that
is **not** a drive-matched ratio — at 1.2 V the pair gives Idsat_p/Idsat_n =
0.82, and equal drive would need Wp/Wn = 1.894. What 1.5135 *does* give is a
switching threshold at Vm/VDD = 0.5046, essentially mid-rail. So the thin-oxide
library is sized for a centred switching threshold, and that is the property
carried over.

At 3.3 V with L = 450 nm the thick-oxide PMOS is much weaker relative to its
NMOS (219 µA/µm against 533 µA/µm), and reaching the same Vm/VDD = 0.5046
needs Wp/Wn = 3.63 — a factor of 2.40 on the thin-oxide ratio. Applying that
factor to every PMOS and leaving every NMOS alone preserves each cell's
internal stack ratios, which is where the thin-oxide library encodes its
series-device compensation, while re-centring the switching threshold.

The ratio was checked for width dependence across the library's full
0.3–17.9 µm range and varies between 3.63 and 3.97, so one global factor
holds to about ±5 %.

Method: a self-biased inverter (input tied to output) settles at exactly Vm,
so one operating point per candidate ratio gives the answer with no sweep
interpolation. See `work/vm_sweep.py` and `work/ratio_check.py`.

### What it costs

Measured on `inv_1` versus `sg13g2_hv_inv_1` (`work/fo4.py`):

| | thin oxide @ 1.2 V | thick oxide @ 3.3 V | ratio |
|---|---|---|---|
| input capacitance | 2.67 fF | 5.87 fF | 2.20× |
| FO4 delay | 53.6 ps | 142.4 ps | 2.66× |

The thick-oxide NMOS actually delivers *more* current per micron at 3.3 V than
the thin-oxide one at 1.2 V (533 vs 391 µA/µm) — the higher supply more than
compensates for the 3.5× longer channel. The speed loss comes from
capacitance, not drive.

## Verification

The functional suites use the thin-oxide library as the golden reference: the
transform changed devices and voltages, never logic, so any topology error
shows up as a divergence. No truth tables were written by hand.

**Combinational — 60 cells, 452 vectors, PASS.** Every input combination of
every combinational cell, thin-oxide at 1.2 V and thick-oxide at 3.3 V in the
same deck, outputs digitised and required to match. 12 high-Z states on the
tri-state cells (`ebufn_*`, `einvn_*`) were exercised and matched; a 1 GΩ
resistor to mid-rail keeps a floating output distinguishable from a driven 0.

**Sequential — 16 cells, 400 samples, PASS.** The stateful cells have no
well-defined DC operating point, so they are clocked through a stimulus that
walks a binary counter over the non-clock inputs, twice, starting from a reset
period so both variants leave the indeterminate power-up state into the same
known state. Outputs are sampled late in every clock period. Samples where
`SET_B` and `RESET_B` are asserted at once are illegal input states with no
defined reference value and are excluded rather than counted as passes.

Stateful cells are identified from the thin-oxide Liberty file by `ff()`,
`latch()`, `statetable()` or `clock_gating_integrated_cell` — the last two
matter, because `lgcp_1` and `slgcp_1` are integrated clock gates that hold
state without an `ff`/`latch` group and are bistable.

**Views agree — 84 cells, 924 devices each, PASS.** The schematics, the CDL
and the SPICE netlist come out of different code paths in the generator, so a
device that got the wrong size in one view but not another would pass every
simulation check above (they all run on the SPICE netlist). All 84 schematics
are netlisted with xschem — through the symbols, so symbol→schematic
resolution is exercised too — and both they and the CDL are compared against
the SPICE netlist on subcircuit pin list and on every device's model, width,
length, finger count and multiplier.

The parasitic formulas used to regenerate `as`/`ad`/`ps`/`pd` were validated by
recomputing all 924 thin-oxide devices and comparing against the shipped
values: worst relative error 3.75e-4, entirely explained by the vendor
netlist printing 4 significant figures.

Reproduce with:

```sh
cd work
python3 verify_logic.py     # combinational equivalence
python3 verify_seq.py       # sequential equivalence
python3 verify_sch.py       # schematics and CDL vs SPICE netlist
```

## Liberty

`lib/` holds an NLDM characterization produced with CharLib at the 3.3 V
typical corner. Cell functions, pin directions and state elements are lifted
from the thin-oxide Liberty file, since the transform did not change any
cell's logic. The slew and load index grids are the thin-oxide grids rescaled
by the measured 2.66× delay and 2.20× capacitance ratios, so the tables cover
the same electrical territory as the original rather than an arbitrary range.

> **66 of the 84 cells are characterized, sequential cells included.**
> The 9 flip-flops (scan variants included) carry clk→Q delay tables,
> setup/hold constraints and leakage; the 5 latches carry en→Q delays and
> closing-edge setup/hold. The 6 tri-state cells are not characterized
> (CharLib has no three-state output form), nor are the 12 no-arc /
> statetable cells listed below.
>
> Stock CharLib 2.1.0 cannot do this: its sequential delay procedure is an
> unimplemented stub and its setup/hold contour procedure builds transients
> that exhaust memory on these cells. work/seq_delay_procedure.py provides
> both (clk→Q measurement and setup/hold by bisection with a c2q-degradation
> criterion), registered through CharLib's own procedure registry; see the
> report for the twelve config and procedure defects that had to be found
> first. Sequential leakage is a single-state measurement
> (work/seq_leakage.py), unlike the all-states enumeration of the
> combinational cells.

Twelve cells are excluded by the configuration, each for a stated reason: the
seven `fill_*` / `decap_*` / `antennanp` / `sighold` cells have no output pin
and no timing arcs; `tiehi` / `tielo` have no timing tables in the thin-oxide
library either; `lgcp_1` and `slgcp_1` are statetable-based integrated clock
gates and CharLib has no input form for a statetable.

Historically, **20 cells were configured but produced nothing** — all 14
flip-flops and latches (`dfrbp_*`, `dfrbpq_*`, `dlh*`, `dll*`, `sdf*`) and all 6
tri-state cells (`ebufn_*`, `einvn_*`). CharLib emits an empty library for
them without running a single simulation and without reporting an error, so
with `omit_on_failure` they vanish silently; the run log does not mention them
at all. The custom procedures above recovered the 14 flip-flops and latches;
the 6 tri-state cells still need work on CharLib itself, or a different
characterizer.

Cell functions are translated from Liberty syntax into CharLib's by
`work/boolexpr.py`. The two are not the same language — Liberty has `*`, `+`,
`^` and postfix `'`, CharLib understands only `!`, `~`, `&`, `|` and has no XOR
at all — so XOR is expanded to `(a & !b) | (!a & b)`. Every translated function
is checked by evaluating both forms over their full truth table before it is
written out; a cell whose translation is not equivalent is dropped rather than
characterized from a wrong function.

The result is validated by reading it back with OpenSTA (`sta -no_init`),
which parses it without warnings.

The shipped tables are also cross-checked against an **independent
characterizer**: `work/lctime_compare.py` runs lctime (LibreCell,
AGPL-3.0, also in the IIC-OSIC-TOOLS container) over eight representative
combinational cells on the same grids and models and aligns all 3 132
common table points. At real loads and STA-relevant slews the two tools
agree to a median 2.9 % on delays and 0.0 % on output transitions; the
systematic band at multi-ns slews is lctime interpreting slew as the full
0–100 % ramp rather than Liberty's 20–80 % time (a direct ngspice
measurement sides with the shipped table, +0.15 % vs −19 %), and lctime's
input-capacitance estimate is +52 % against the direct reference where
the shipped value is +9.7 %. Details in the report and in the script's
docstring.

### Running CharLib here

`work/run_charlib.sh` exists because five separate things have to be worked
around. None is caused by the library.

1. **`PYTHONPATH` shadows the venv.** It is set globally and lists the system
   `dist-packages` ahead of any virtualenv, so CharLib gets the system PySpice
   1.5 instead of its own 1.6. PySpice 1.5 has no top-level `Circuit`, and
   CharLib dies with `module 'PySpice' has no attribute 'Circuit'`. The script
   clears `PYTHONPATH`.

2. **ngspice server mode ignores `.spiceinit`.** PySpice drives ngspice as
   `ngspice -s`. ngspice reads `.spiceinit` in batch and interactive mode but
   not in server mode, so the PDK's `osdi ...psp103.osdi` lines never run —
   and every SG13G2 MOSFET is a PSP103 Verilog-A model loaded through OSDI.
   Without them ngspice reports `Unknown model type psp103va` and refuses the
   circuit. `work/ngspice-osdi-shim/ngspice` injects a `pre_osdi` block after
   the title line (`pre_`-prefixed commands run before the netlist is parsed);
   verified to give results identical to a batch run. The same shim pins
   `num_threads=1`, because server mode also ignores the thread setting and
   CharLib's own concurrency times ngspice's threading buries the machine —
   simulations that take 0.4 s alone were taking minutes.

3. **CharLib cannot find the supply current.** Its leakage procedure does
   `analysis.branches[settings.primary_power.name.lower()]`, but PySpice 1.6's
   `fix_case()` files branches under the circuit's own spelling and always
   emits a voltage source with a capital `V`. The branch is therefore `VDD` or
   `Vdd`, never `vdd`, and every leakage measurement raises `KeyError: 'vdd'`.
   No supply name avoids it. `work/charlib_patched.py` makes the branch lookup
   case-insensitive at runtime and then hands over to CharLib's CLI, so the
   shared install under `/foss/tools/charlib` is left untouched.

4. **The simulation backend must be `ngspice-shared`.** With
   `ngspice-subprocess`, PySpice parses only the raw file and never reads
   `.meas` results back — `PySpice/Spice/NgSpice/RawFile.py` has no
   measurement handling at all. Every delay measurement then comes back empty
   and the emitted Liberty has `timing()` groups containing no
   `cell_rise` / `cell_fall` / `*_transition` tables. This one is easy to miss
   because leakage, area and pin capacitance are still populated, so the file
   looks plausible until a timing tool reads it and finds nothing.

5. **The emitted Liberty needs fixing up.** CharLib writes the pin function
   with its left-hand side attached — `function : "Y = !(A)"` — where Liberty
   wants the expression alone, and it writes `pulling_resistance_unit : "1uA"`
   (a current unit) and a `bus_naming_style` OpenSTA rejects.
   `work/fix_lib.py` corrects all three; `run_charlib.sh` applies it
   automatically.

> **`area` in the Liberty file is an estimate, not a measurement.** This
> library has no layout. The estimate assumes each cell keeps the thin-oxide
> device arrangement, so the poly pitch count per cell is unchanged and only
> the pitch and row height grow: contacted poly pitch 0.48 → 0.80 µm (keeping
> the thin-oxide gate-to-contact budget around the longer gate) and row height
> 3.78 → 5.39 µm (to fit the widest PMOS finger, 1.155 → 2.770 µm). Treat it
> as an order-of-magnitude figure for synthesis, not as silicon area.

## Layout

`gds/sg13g2_stdcell_hv.gds` holds **66 of the 84 cells**, produced by
`work/layout_retarget.py`.

The thin-oxide GDS is hand-drawn 2-D layout, not a regular template, so a
placement-based generator would have to rebuild every cell — and would not be
LVS-correct without a router. What can be done exactly instead is a **1-D
retarget**: a monotone piecewise-linear coordinate map applied to every vertex.
A monotone map never reorders or merges geometry, so it preserves which shape
touches which, and therefore the circuit topology. Only the device dimensions
change, which is exactly what the thick-oxide transform is.

Two maps per cell:

* **x** — every gate is widened 0.13 → 0.45 µm. The map is identity outside
  the gates, so gate-to-gate gaps and the 0.11 µm contact-to-gate clearance
  carry over untouched. The slope is fixed at 0.45/0.13 rather than derived
  from the interval: several cells stagger the NMOS and PMOS gate by 20–50 nm,
  so their x-intervals overlap and merge, and scaling the merged span would
  leave each gate short of 0.45. Gates already at or above 0.45 µm — the delay
  cells and the `sighold` keeper, at 0.5–1.0 µm — are left alone.

* **y** — one slope-2.40 segment across a **library-wide** PMOS band
  (1.925–3.630 µm). A linear segment scales *every* sub-interval inside it by
  the same factor, so all PMOS widths scale by 2.40 wherever they sit. The
  band must be library-wide, not per cell: deriving it per cell produced six
  different cell heights, which is not a standard cell library at all. The
  NMOS band is untouched, because NMOS widths do not change.

Contacts are a fixed 0.16 µm square and must not be stretched, so they are
removed before the map and re-tiled afterwards inside the new Activ. Three
things matter there, each learned from a DRC run rather than assumed:
contacts must be grouped by the *polygon* they sit in and not by x alone (the
VSS and VDD rail taps share an x, and grouping by x tiled contacts straight up
through the field between them); the pitch is 0.36 µm rather than the
thin-oxide library's 0.34, because `Cnt.b1` raises the required spacing to
0.2 µm once an array exceeds 4 rows and 4 columns, which the 2.4× taller PMOS
now does; and a contact's box is built by snapping one corner and adding the
size, since snapping both edges independently rounds 0.16 µm to 0.155/0.165.

ThickGateOx is drawn over the cell boundary grown by `TGO.a` (0.27 µm) in x
and by 0.42 µm in y, so abutted cells merge into one region — `TGO.e` merges
anything closer than 0.86 µm — and no internal `TGO.b`/`TGO.d` edge appears
inside a row. The extra 0.15 µm in y matters at an *unabutted* row edge (the
outermost row of a block or a test array): the shared rail's Activ crosses
the cell boundary by 0.15 µm, and a plain 0.27 µm margin leaves only 0.12 µm
of ThickGateOx past it — a `TGO.a` violation that shows up exactly twice on
any N-row test array, once per outer edge. With 0.42 µm the cells are correct
even at a block edge.

### LVS

`work/run_lvs.sh` runs the PDK's LVS deck per cell against `cdl/`. Per cell
rather than over the whole GDS, because the library has no top level and a
per-cell result says *which* cells pass.

Two things are worth knowing before trusting any LVS number here:

* **The PDK runner exits 0 even when the netlists do not match.** Keying
  pass/fail off the exit status reports every cell as passing; the verdict has
  to be read out of the log.
* **Run the control first.** IHP's own thin-oxide cell passes this same flow,
  which is what establishes that a failure is in the layout and not the setup.
  That control is also what showed the `fill_*` result below is not a defect.

LVS caught five defects that dimensional checks could not, because each leaves
a layout whose measurements are correct:

* Every **rail-tap contact was dropped** by a floating-point comparison — a
  0.30 µm tap gives `hi - lo` = 0.15999999999999998 against a 0.16 µm contact.
  That removed the substrate tie and the NMOS bulk extracted as a floating net.
* **Contact re-tiling created shorts**: tiling the full diffusion height put
  contacts under a *different* Metal1 wire, shorting it to diffusion. This is
  why contacts are no longer regenerated at all — see `retile_contacts`.
* **Only a hardcoded layer list was transformed.** Metal2, Via1 and marker
  layers stayed at thin-oxide coordinates, which clipped the antenna diode's
  extracted area.
* **Ungated Activ was being stretched.** Antenna diodes are diodes, not
  channels; scaling them changes area and perimeter. They are now translated.
* **Folded devices were mis-paired** in the netlist sync: `ng=4` draws four
  channels, so `buf_4`'s four devices correspond to six drawn gates.

### DRC result

**Clean.** A single fixed invocation of the PDK runner (`run_drc.py
--path=... --topcell=drc_top`, no extra flags) on the abutted two-row array
reports zero cell-rule violations, like IHP's own thin-oxide library through
the identical harness:

| | this library | IHP thin-oxide control |
|---|---|---|
| cell rules (`M1.*` spacing/width, `Act.*`, `Gat.*`, `TGO.*`, …) | **0** | **0** |
| density (`M1.j` … `TM2.c`) | 7 | 6 |

The density items are a property of the harness, not of either library: a
standard cell library contains no Metal2 and above, and metal density is a
chip-level check on a *filled* die. The one count that differs, `M1.j`
(min 35 % Metal1), is quantified rather than waved away: the deck measures
density over the marker bounding box including the empty ThickGateOx
margin, where the padded 17-track array reads 35.0 % — over the actual cell
area it is 37.1 % — while the denser, unpadded thin-oxide control array
reads 45.2 % and never trips it. A placed block carries metal fill and does
not see this.

Getting to zero took three fixes beyond the retarget itself, each reached by
replicating the failing rule flat with the `klayout.db` API rather than
reading marker text (lyrdb coordinates are in per-variant cell frames in deep
mode, and mapping them as top-cell µm attributes violations to the wrong
cells — an earlier draft of this file blamed four cells that had nothing
wrong with them):

* **`Act.c`/`Act.a` — 5 nm staircase steps in the retargeted PMOS Activ.**
  Each slab's bottom edge is `mapped_top − snap(2.40·h)`, computed
  independently per slab, and the source's own 5 nm jogs land neighbouring
  slabs one grid step apart. A step within 0.23 µm of a gate edge is `Act.c`;
  a 0.12 µm slab flanked by steps was `Act.a`. Fixed by aligning sub-grid
  steps between x-adjacent slabs — with **channel slabs frozen**. The first
  version aligned everything, which moved channel edges by 5 nm and made two
  formerly identical devices differ (2.400 vs 2.405 µm); the netlist sync
  pairs devices to drawn channels by sorted width, which is ambiguous between
  near-equal devices on different nets, and five cells lost their LVS net
  correspondence. Only source/drain slabs move, toward their channel
  neighbours, so the repair provably cannot change any device.
* **`M1.e` — five sites where the retarget manufactures the wide-metal
  condition.** The rule needs a line ≥ 0.30 µm wide *and* a parallel run
  > 1.0 µm; the y-map thickens lines past 0.30 and the x-map lengthens runs
  past 1.0, so 0.18 µm gaps that were legal in the thin-oxide cells became
  illegal with nothing moved. Generic edge-trimming cannot fix them — every
  gap abuts a contact column or a pin pad — so each site has an explicit
  hand re-route in `M1E_EDITS` (`work/layout_retarget.py`): raised pin-pad
  bottoms in `dlygate4sd2_1` and `mux2_1`, a raised strap and a 15 nm bite
  that splits a 2.33 µm parallel run in `sdfbbp_1`, a narrowed pin pad in
  `and4_2`. Every edit is verified in code: polygon count unchanged (no
  split nets), `M1.a` width, `M1.b` space/notch, `M1.c1` contact enclosure,
  5 nm grid. The guards caught two wrong first attempts — a flush cut that
  left a 0.106 µm diagonal width, and a bite on a line too narrow to bite.
* **`TGO.a` — the y-margin, see the ThickGateOx paragraph above.** The pair
  of violations on the test array's outer edges was first shown to be an
  edge artifact (stacking 3 rows instead of 2 keeps the count at exactly 2,
  `work/make_drc_rows.py`), then eliminated outright by the 0.42 µm y-margin.

> A note on measuring this. The runner executes different rule-table sets
> depending on its flags — `--no_density` runs the monolithic deck and emits
> 4 files where the default emits 5, and an earlier run produced 40. Counts
> from runs with different flags are **not comparable**. Always quote a
> number together with the invocation that produced it, and diagnose from a
> flat rule replication, not from marker text.

### LVS result

**All 66 cells match.** The 62 cells that contain devices pass with the
strict flags. The four `fill_*` cells contain no devices at all — klayout
then extracts a port-less empty circuit, the CDL subckt declares VDD/VSS, and
the comparer reports that port-list difference as a mismatch; IHP's own
`sg13g2_fill_1` and `sg13g2_fill_4` fail the identical flow the same way.
For exactly those four cells `work/run_lvs.sh` passes
`--ignore_top_ports_mismatch`, which is the runner's own relaxation for this
case: the port check is vacuous for a cell that extracts to an empty circuit,
while every cell with devices keeps the strict comparison where a port
mismatch is a real defect.

Getting there needed the device widths to be exact. The retarget scales by
2.40 and 2.40 x 5 nm = 12 nm, so a scaled width does not always land on the
5 nm layout grid; snapping the two Activ edges independently then gives the
same 1.12 um thin-oxide device 2.685 um at one y and 2.690 um at another, and
the netlist cannot say which is which. `retarget_pmos_activ` cuts each PMOS
Activ into vertical slabs and re-emits each slab at
`mapped_top - snap(KP * height)`.

Two details there are load-bearing, and both were learned by breaking them:

* **Per connected piece, not per slab bounding box.** A non-convex Activ can
  have two disjoint lobes at the same x; the bounding box spans the gap between
  them and merges two channels, which silently deleted two PMOS from
  `dfrbp_1`.
* **Per slab, not per polygon.** A notch is how this library gives devices in
  one diffusion different widths, so forcing a whole polygon to one height
  collapses them -- `and2_1`'s three PMOS all became 2.69 um.

### Verified

* **DRC clean and LVS clean, all 66 cells** — see
  [DRC result](#drc-result) and [LVS result](#lvs-result).
* Uniform row height, **7.140 µm = 17 horizontal routing tracks**
  (0.42 µm pitch), across all 66 cells; every cell width is a multiple of
  the 0.48 µm `CoreSiteHV` site, so the cells place on the same grids as
  the thin-oxide 9-track library. `lef/sg13g2_stdcell_hv.lef` carries the
  site and the 66 macros, generated from the GDS by `work/gen_lef.py` with
  pin sets verified against the CDL and antenna values recomputed from the
  netlist.
* Every gate length and width matches the scaled thin-oxide layout to within
  the 5 nm grid, with one exception: `dlygate4sd2_1`, whose NMOS (0.18 µm) and
  PMOS (0.25 µm) gates overlap in x with *different* lengths. A single 1-D map
  cannot scale two overlapping intervals independently, so its PMOS lands at
  0.625 µm — legal, and carried consistently in the SPICE, CDL *and*
  schematic views (`verify_sch.py` checks all three).
* All 5082 contacts are exactly 0.16 × 0.16 µm.

### Not done

* **18 cells have no layout.** They run a PMOS Activ up into the VDD rail, or
  bring an NMOS Activ up to the library channel cut; either way the band
  cannot be scaled without moving the rail off the cell boundary and breaking
  abutment. They are listed by `layout_retarget.py`.
* Not silicon-proven, and not reviewed by anyone who was not also its author.
  DRC/LVS-clean means the checks pass, not that the cells are known good in
  fabrication.

Cells checked in an abutted context, not standalone: `work/make_drc_top.py`
builds a row of every cell with a second row mirrored above it so the two
share a rail, because the rails and ThickGateOx are only legal because cells
abut.

## What this library is not

- **Layout is partial.** 66 of 84 cells have GDS (see [Layout](#layout)); 18
  do not. The 66 are DRC clean and LVS clean and carry LEF abstracts on a
  17-track site, but no block has actually been placed and routed with
  them yet.
- **Not silicon proven.** Everything here is simulation against the PDK models.
- **Delay cells behave differently.** `dlygate4sd2_1` and `o21ai_1` used gate
  lengths below the thick-oxide minimum, so their delay ratios have shifted.
- **The decap cells are weaker per unit area.** Thicker oxide means less
  capacitance for the same geometry; `decap_4` / `decap_8` keep their
  thin-oxide dimensions and simply store less.

## Directory layout

```
sg13g2_stdcell_hv/
├── spice/sg13g2_stdcell_hv.spice     84 subcircuits, thick-oxide devices
├── cdl/sg13g2_stdcell_hv.cdl         LVS netlist
├── verilog/sg13g2_stdcell_hv.v       behavioural models, modules renamed
├── sch/xschem/*.sch                  84 schematics
│   └── sg13g2_hv_stdcells.sch        all 84 cells on one sheet (the gallery)
├── sym/xschem/*.sym                  84 symbols (copies of the thin-oxide ones)
├── lef/sg13g2_stdcell_hv.lef         66 macros + CoreSiteHV (0.48 x 7.14)
├── lib/                              Liberty, 3.3 V typical
├── gds/sg13g2_stdcell_hv.gds         66 of 84 cells, retargeted (see Layout)
├── doc/sg13g2_stdcell_hv.celllist
├── xschem_lib_sg13g2_stdcell_hv.tcl  xschem registration
└── work/                             generator, verification and provenance
```

The Verilog deliberately does **not** ship a copy of `sg13g2_udp.v`: the UDP
primitives are named `ihp_*` and are shared, so a second copy would collide if
both libraries were loaded. Include the PDK's original alongside this file.

This tree follows the PDK's `libs.ref` layout but lives outside `$PDK_ROOT`,
so the shared PDK install is left untouched.

## Using it

### xschem

Source the registration file after the PDK `xschemrc`:

```tcl
source $env(PDK_ROOT)/$env(PDK)/libs.tech/xschem/xschemrc
source /foss/designs/sg13g2_stdcell_hv/xschem_lib_sg13g2_stdcell_hv.tcl
```

Then open `sch/xschem/sg13g2_hv_stdcells.sch` to see the whole library on one
sheet — the thick-oxide counterpart of the PDK's `IHP130_stdcells.sch`. It
covers all 84 cells grouped by function, and the placement is computed from
each symbol's drawn extent by `work/gen_gallery.py` rather than hand-placed,
so nothing overlaps whatever the pin count.

The symbols are copies of the thin-oxide ones — same drawn geometry, same pin
names, same pin order. Two things differ: the template prefix is
`sg13g2_hv_`, so an instance netlists to `sg13g2_hv_<cell>`; and they carry
`type=subcircuit` and resolve their schematic through `$::SG13G2_HV_SCH`,
which the `.tcl` sets. The thin-oxide symbols instead go through the PDK's
`hierarchy_config` proc, which is hard-wired to the `sg13g2_stdcell` schematic
directory and has no thick-oxide view.

### ngspice

```spice
.lib $PDK_ROOT/$PDK/libs.tech/ngspice/models/cornerMOShv.lib mos_tt
.lib $PDK_ROOT/$PDK/libs.tech/ngspice/models/cornerDIO.lib dio_tt
.include /foss/designs/sg13g2_stdcell_hv/spice/sg13g2_stdcell_hv.spice
```

The diode models are only needed if you instantiate `sg13g2_hv_antennanp`,
which is built from `dantenna` / `dpantenna` rather than MOSFETs. Without them
ngspice reports `unknown subckt: ... dantenna` and refuses the whole netlist.
The thin-oxide library has exactly the same dependency.

Note that ngspice only reads `.spiceinit` — and so only loads the PDK's OSDI
PSP103 models — in batch and interactive mode, not in server mode (`ngspice
-s`). Tools driving ngspice through PySpice hit this; see
`work/ngspice-osdi-shim/ngspice` for the workaround.

## Regenerating

```sh
cd work
python3 vm_sweep.py             # re-derive the PMOS width factor
python3 ratio_check.py          # sizing-criterion and width-independence checks
python3 gen_hv_lib.py           # regenerate the library
python3 verify_logic.py         # combinational equivalence
python3 verify_seq.py           # sequential equivalence
python3 verify_sch.py           # schematics and CDL vs SPICE netlist
python3 gen_charlib_config.py   # build the CharLib configuration
./run_charlib.sh ../lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib
# sequential cells (flops + latches) use the custom procedures in
# seq_delay_procedure.py, registered by charlib_patched.py at startup:
env -u PYTHONPATH sh -c "PATH=$PWD/ngspice-osdi-shim:\$PATH \
  /foss/tools/charlib/bin/python charlib_patched.py run \
  charlib_sg13g2_stdcell_hv.yml -f 'sg13g2_hv_(sdf|dfr|dlh|dll)' \
  -o seq.lib -j 6"
python3 merge_lib.py ../lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib seq.lib
python3 seq_leakage.py          # single-state leakage for the 14 cells
python3 verify_lib.py           # gates the shipped Liberty as data
python3 lctime_compare.py       # independent characterizer cross-check

python3 layout_retarget.py      # gds/ (66 cells, prints the 18 skips)
python3 sync_netlist_widths.py  # SPICE + CDL follow the drawn geometry
python3 gen_lef.py              # lef/ (site + 66 macros)
python3 make_drc_top.py         # abutted 2-row DRC context
./run_lvs.sh                    # per-cell LVS
# DRC: PDK run_drc.py on work/drc/drc_top.gds, default flags
```

`gen_hv_lib.py` refuses to generate if its parasitic formulas stop reproducing
the thin-oxide library, so a PDK update that changes the device geometry
constants fails loudly instead of silently producing wrong parasitics.

## Licence

Derived from `sg13g2_stdcell`, Copyright 2023 IHP PDK Authors, Apache License
2.0. This derived work is distributed under the same terms.

# sg13g2_stdcell_hv — thick-oxide (3.3 V) standard cells for IHP SG13G2

The IHP SG13G2 open PDK ships one standard cell library, `sg13g2_stdcell`,
built entirely from the 1.2 V thin-oxide devices (`sg13_lv_nmos` /
`sg13_lv_pmos`). The 3.3 V thick-oxide devices appear only inside the
`sg13g2_io` pad ring, which is not a standard cell library — it has 22 macros,
all pads, fillers and a corner, and nothing you can synthesise and place.

This library fills that gap: all 84 cells of `sg13g2_stdcell`, rebuilt on the
thick-oxide devices, with the same topology, the same pin names and the same
pin order, plus two tie cells built here (see [Tie cells](#tie-cells)). All 84
cells are drawn and are **DRC clean and LVS clean** against the PDK's own
klayout decks, and clean under Magic's strict analog N-well rules as well (the
remaining DRC report lines are chip-level metal-density rules that only apply
to a filled die — see the DRC result section) — placed on a 17-track site with
LEF abstracts. 82 of the 84 are in the Liberty file; see [Liberty](#liberty)
and [What this library is not](#what-this-library-is-not) for what is still
missing.

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

**Views agree — 84 cells, 920 devices, PASS.** The schematics, the CDL
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

> **82 of the 84 cells are in the Liberty file, 72 of them with timing
> arcs.** The 9 flip-flops (scan variants included) carry clk→Q delay
> tables, setup/hold constraints and leakage; the 5 latches carry en→Q
> delays and closing-edge setup/hold; the 6 tri-states carry the data arc
> plus `three_state_enable` / `three_state_disable`. `sighold` ships
> `driver_type : bus_hold` with measured capacitance and leakage, the tie
> cells and the 7 physical cells area and leakage only. The 2 statetable
> clock gates are the only cells with no Liberty entry at all.
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

Twelve cells are excluded by the configuration, each for a stated reason, and
all but two are measured directly against the shipped netlists instead: the 4
`fill_*`, 2 `decap_*` and `antennanp` cells have no output pin and no timing
arcs (area-only stubs, measured leakage, measured diode pin capacitance);
`tiehi` / `tielo` have no timing tables in the thin-oxide library either
(measured leakage); `sighold` is a bus holder whose only signal pin is an
`inout` (measured `bus_hold` capacitance and leakage — see
`work/char_sighold/`). `lgcp_1` and `slgcp_1` are statetable-based integrated
clock gates and CharLib has no input form for a statetable; their direct
characterization is still in progress, so they ship with layout but no
Liberty, and the SCL excludes them exactly as the thin-oxide SCL excludes its
own clock gates.

`work/finalize_lib.py` post-processes the characterized file into the
shipped one, all three steps idempotent and derived or measured rather
than borrowed from the thin-oxide library:

* **Drive limits.** CharLib emits no `max_capacitance` / `max_transition`
  at all. OpenSTA then answers "no limit" everywhere — LibreLane's
  max-cap/max-slew checks pass vacuously and OpenROAD's TritonCTS
  dereferences the empty buffer-selection result and crashes. The limits
  come from the characterization itself: per output pin, the top of its
  load axis (0.66–10.56 pF by drive class); per pin, the top of the slew
  axis it was characterized against (6.67 ns combinational, 3.36 ns
  sequential); library defaults `default_max_capacitance : 0.66` /
  `default_max_transition : 6.66968` follow the thin-oxide convention of
  weakest-drive / slowest-edge. These bound the characterized range —
  actual slew targets belong in the flow constraints.
* **Physical-cell stubs.** Area-only entries for `fill_*`, `decap_*` and
  `antennanp` (`is_filler_cell` / `is_decap_cell` / `dont_use`), so
  filler, decap and antenna-diode insertion produce no cells STA has
  never heard of. Decap and diode leakage are measured on the shipped
  netlists like the tie cells (thick oxide: the decaps leak ~nothing,
  unlike their 396 nW thin-oxide counterparts); the diode's 1.6 fF pin
  capacitance is a 1 MHz small-signal measurement averaged over bias —
  the charge-integration method is unusable here because the antenna
  diodes' breakdown model forces picosecond transient steps.
* **Corner-suffixed library name** (`sg13g2_stdcell_hv_typ_3p30V_25C`),
  matching the upstream per-corner naming.

Historically, **20 cells were configured but produced nothing** — all 14
flip-flops and latches (`dfrbp_*`, `dfrbpq_*`, `dlh*`, `dll*`, `sdf*`) and all 6
tri-state cells (`ebufn_*`, `einvn_*`). CharLib emits an empty library for
them without running a single simulation and without reporting an error, so
with `omit_on_failure` they vanish silently; the run log does not mention them
at all. The custom procedures above recovered the 14 flip-flops and latches.
The 6 tri-states are not recoverable that way — CharLib has no high-impedance
concept anywhere in its schema, and lctime pins the enable and skips exactly
the enable arcs — so they are measured directly against the shipped netlists
by `work/char_tristate/char_tristate.py`, which is where their
`three_state_enable` / `three_state_disable` tables come from.

### What CharLib gets wrong in the emitted Liberty

CharLib's output is not directly usable and is post-processed by
`work/fix_lib.py` (header and combinational defects) and
`work/fix_lib_seq.py` (sequential ones). All of these were found by feeding
the library to real tools, not by reading the file:

| defect | what CharLib writes | correct | why it matters |
|---|---|---|---|
| function LHS | `function : "Y = !(A)"` | `"!(A)"` | `function` is the expression alone; the `Y = ` prefix makes the attribute invalid |
| sequential output function | `function : "Q = D"` | `"IQ"` / `"IQN"` | the output of a flip-flop is the state variable of its `ff` group, not the next-state expression |
| state groups | `ff (IQ, IQinv)` **and** `ff (IQN, IQNinv)` | one `ff (IQ,IQN)` | a state group already declares both the variable and its complement |
| both clear and preset | neither `clear_preset_var*` | `H` / `L` | required once a group carries both, to define Q/QN when both assert |
| logic thresholds | `0.20` / `0.80` / `0.50` | `20` / `80` / `50` | `*_threshold_pct_*` is a percentage; the fraction says the transition was measured over a 0.6 % window instead of 60 % |
| `pulling_resistance_unit` | `1uA` | `1ohm` | a current unit for a resistance |
| `bus_naming_style` | `%s-%d` | `%s[%d]` | not a form OpenSTA accepts |

The two sequential defects are the ones that stop a flow outright. With the
next-state expression on the output pin, every flip-flop looks combinational:
Yosys' `dfflibmap` finds no async-reset flip-flop in the library at all and
aborts with *"dffs with async set or reset are not supported"*, and a timing
tool sees a D→Q combinational arc instead of a clock boundary. The threshold
defect surfaces later and less obviously, in OpenROAD's resizer as
*"[RSZ-0101] RC slew modeling shape factor is out of range"*.

The measurements themselves are sound in every case -- CharLib was configured
with the usual 20/80/50 thresholds and the tables reflect that. Only the
header and the sequential bookkeeping are wrong.

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

> **`area` in the Liberty file is the measured footprint for every cell.**
> All 84 cells are drawn, so each value is the real LEF width × the
> 7.14 µm row height (`work/update_lib_area.py` keeps the two views in
> step and reports any drift); no pre-layout estimates remain.

## Layout

`gds/sg13g2_stdcell_hv.gds` holds all **84 cells**: 66 produced by
`work/layout_retarget.py`, the other 18 by the per-cell generators described
under [Verified](#verified).

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

#### The shared-rail blind spot

The harness above has a blind spot, found only when a placed block went
through signoff: it never actually shares a rail between *different* cells.
`make_drc_top.py` stacks each cell in its own column (the vertical neighbour
is always the same cell) and, despite its docstring, places the mirrored row
at the padded bbox pitch (2 × 7.98 µm), 0.84 µm clear of the first — so the
rail centreline, which every cell taps with contacts straddling y = 0 and
y = 7.14, was never merged between two different cells at all.

A placed block merges it everywhere. The retarget mapped each cell's rail
contacts through that cell's own x-map, leaving them at cell-specific x
positions, and wherever two different cells met across a rail their tap
contacts overlapped partially into 0.19–0.32 µm bars — not a legal 0.16 µm
contact (`Cnt.a`/`Cnt.b`) and shorter than a legal 0.34 µm `ContBar`
(`CntB.a1`/`CntB.b2`). On a ~700-cell `spi_slave` block this was ~19 000
markers, all on rails.

`work/fix_rail_contacts.py` re-tiles every rail-straddling contact onto the
site-centred grid x = 0.24 + 0.48k in the cell frame. Site centres are
preserved by the FS row flip and by the x-mirroring detailed placement
applies (cell widths are site multiples), so any two cells sharing a rail
now land their taps either exactly on top of each other — a merged legal
square — or a full site apart (0.32 µm edge-to-edge ≥ `Cnt.b` 0.18). Each
new contact is guarded in code: correct implant (p+ tap inside `pSD` at VSS,
n+ tap inside NWell at VDD — a contact on the wrong implant would short a
butted diffusion to the supply), 0.07 µm Activ enclosure, 0.09 µm Metal1
enclosure, 0.11 µm to any gate, 0.18 µm to any untouched contact, and every
tap strip that had a contact keeps at least one. Rail contact count went
from 1134 to 1810 (the 0.48 µm pitch tiles the full strip).

The regression harness that would have caught this from the start is
`work/make_shared_rail_rows.py`: four rows at the true 7.14 µm pitch
(orientations N, S, FS — so rails are shared both mirrored and unmirrored),
each row the full cell list in a rotated order so vertical neighbours
differ, cells advanced by LEF width so the drawn margins overlap exactly as
placed. After the fix it reports **zero cell-rule violations** — only the
chip-level density markers discussed above — and the per-cell LVS was re-run
afterwards, as it was again once every cell was drawn: 84/84 match.

Getting to zero in the original harness took three fixes beyond the retarget
itself, each reached by replicating the failing rule flat with the
`klayout.db` API rather than reading marker text (lyrdb coordinates are in per-variant cell frames in deep
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

**All 84 cells match.** The 80 cells that contain devices pass with the
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

* **DRC clean and LVS clean, all 84 cells** — 66 retargeted, the 2 tie
  cells, and 16 cells the 1-D retarget could not produce (flops, latches,
  tri-state drives, clock gate, sighold) that were later generated with
  per-cell recipes (`work/flop_pilot/gen_seq.py`,
  `work/cell_dev/*/gen_*.py`): the common blocker was a p+ source finger
  butting into the VDD rail tap, removed before the y-map and redrawn
  after it at the slgcp_1 butted-junction convention, plus per-cell
  y-map insert splits that land every template band on the shipped
  positions. Each generated cell passed `work/cell_verify.py` (LVS,
  KLayout modular+maximal DRC in abutted context, Magic, structure and
  pin checks) before joining the library — see [DRC result](#drc-result)
  and [LVS result](#lvs-result).
* Uniform row height, **7.140 µm = 17 horizontal routing tracks**
  (0.42 µm pitch), across all 84 cells; every cell width is a multiple of
  the 0.48 µm `CoreSiteHV` site, so the cells place on the same grids as
  the thin-oxide 9-track library. `lef/sg13g2_stdcell_hv.lef` carries the
  site and the 84 macros, generated from the GDS by `work/gen_lef.py` with
  pin sets verified against the CDL and antenna values recomputed from the
  netlist.
* Every gate length and width matches the scaled thin-oxide layout to within
  the 5 nm grid, with one exception: `dlygate4sd2_1`, whose NMOS (0.18 µm) and
  PMOS (0.25 µm) gates overlap in x with *different* lengths. A single 1-D map
  cannot scale two overlapping intervals independently, so its PMOS lands at
  0.625 µm — legal, and carried consistently in the SPICE, CDL *and*
  schematic views (`verify_sch.py` checks all three).
* All 5758 contacts are exactly 0.16 × 0.16 µm, and every rail-tap contact
  sits on the site-centred 0.48 µm grid, so cells sharing a rail in a placed
  block merge their taps legally — verified on the shared-rail mixed-row
  array (`work/make_shared_rail_rows.py`), which is DRC-clean of all cell
  rules.
* **The N-wells satisfy the strict analog HV rules, not just the DigiBnd
  digital ones.** The retarget originally placed the well bottom for
  NW.c1.dig (0.31 µm); Magic's tech has no DigiBnd concept and applies the
  analog NW.c1/NW.d1 (0.62 µm) unconditionally, flagging every cell by
  25 nm (mux4_1/slgcp_1 by ~210 nm). `work/fix_well_nwc1.py` rebuilds the
  well layer only — bottom edge 2.625 → 2.570 µm, deeper jogs over the two
  deep P-active bands, lateral overhang 0.24 → 0.62 µm so the outermost
  cell of a row is enclosure-clean without a neighbour — leaving a
  0.62 µm-clean library with **zero device changes and no
  re-characterization** (wells are not device terminals; the HV PSP models
  carry no well-proximity parameters). Verified: Magic reports 0 NW.*
  errors on the abutted array, and both KLayout decks (modular + maximal,
  including NW.c1.dig) stay clean. Magic's remaining array flags — Cnt.c
  (0.07 µm contact-overlap interpretation) and wide-metal M1.e — are
  Magic-vs-KLayout interpretation differences on geometry both KLayout
  decks accept; NW.e1 can still appear at the outermost block rows where
  the VDD tap has only its own 0.24 µm top overhang (legal under
  NW.e1.dig, merged away wherever rows abut).

### Not done

* `layout_retarget.py` still prints 18 skips: tiehi/tielo were drawn from
  scratch by `gen_tie_cells.py` (see [Tie cells](#tie-cells)) and the
  other 16 by the per-cell generators listed under
  [Verified](#verified) — the library-wide 1-D map itself remains unable
  to scale a band that butts the rail.
* Not silicon-proven, and not reviewed by anyone who was not also its author.
  DRC/LVS-clean means the checks pass, not that the cells are known good in
  fabrication.

Cells checked in an abutted context, not standalone: the rails and
ThickGateOx are only legal because cells abut. `work/make_drc_top.py` builds
the original padded array; `work/make_shared_rail_rows.py` builds the
stricter one — true 7.14 µm row pitch with shared rails, mixed vertical
neighbours, mirrored placements and overlapping margins — which is what a
placed block actually looks like (see
[the shared-rail blind spot](#the-shared-rail-blind-spot)).

### Pins are not on the routing track grid

The x-map widens every gate 0.13 → 0.45 µm and `pad_to_site` then pads the
cell to a whole number of sites. Both move the internal geometry sideways,
and nothing puts it back on the 0.48 µm Metal1 track grid. The result, from
`work/grid_align_pins.py`:

| | signal pins with no vertical track through them |
|---|---|
| `sg13g2_stdcell` (thin oxide) | 2 (both scan pins of `sdfbbp_1`, unused by the reference flow) |
| `sg13g2_stdcell_hv` before widening | 25 (of the 68 cells drawn at that point) |
| `sg13g2_stdcell_hv` shipped, all 84 cells | **11** of 282 signal pins (`grid_align_pins.py --apply` widened the 12 that had room) |

Metal1 sits below the usual `RT_MIN_LAYER` of Metal2, so such a pin can only
be reached by dropping a via from Metal2 — and a via wants a track. The
router copes with most of them, but not all: the first place-and-route of
this library left four `nand4_1` B pins with no metal on them at all, and
Netgen reported the two nets they belonged to as split (devices matched,
nets did not).

Two ways round it, and the design flow that ships with the SPI slave uses
the second:

* widen the pin sideways to the nearest track — `grid_align_pins.py --apply`
  did this for the 12 pins that have room, and the shipped GDS/LEF carry the
  result (DRC and LVS re-run clean). The remaining 11 (including that
  `nand4_1` B pin) cannot be widened without breaking `M1.b`;
* let the router onto Metal1 (`RT_MIN_LAYER: Metal1`), which lets it jog to
  an off-grid pin. The LEF's OBS block already covers every non-pin Metal1
  strap, so Metal1 routing cannot short a cell's internals.

The real fix is to place the pins on the grid during the retarget, which
means teaching `layout_retarget.py` a snap step. That is not done here.

## Tie cells

`sg13g2_hv_tiehi` and `sg13g2_hv_tielo` are not retargets -- the thin-oxide
tie cells are among the cells the 1-D map has to skip. They are built by
`work/gen_tie_cells.py` from `sg13g2_hv_inv_1`, which did retarget, by tying
its input off inside the cell:

| cell | input tied to | on device | output |
|---|---|---|---|
| `sg13g2_hv_tielo` | VDD | NMOS | VSS (`L_LO`) |
| `sg13g2_hv_tiehi` | VSS | PMOS | VDD (`L_HI`) |

The tie is one Metal1 rectangle. In the retargeted inverter the A pin
(x 0.310-0.625, y 1.950-2.725 um) sits between the two source straps, which
occupy the same x range (0.330-0.590) and stop at y 1.640 below and y 3.645
above. Filling either gap at the strap width merges the gate metal into that
rail and touches nothing else: the only other Metal1 in the band is the
output strap at x >= 1.175, which keeps 0.585 um of clearance. The cells keep
the inverter's footprint, 1.92 x 7.14 um.

This is topologically **not** what the thin-oxide library does. Its tie cells
use a four-transistor chain and never put a gate on a supply rail, which is
the classical way to keep the gate off a large charge-collecting net. Here
the gate is on the rail -- and the rail carries the cells' own well and
substrate taps, so it is diffusion-clamped and the gate is diode-protected.
That is a claim the deck can check rather than an argument to be believed:
the antenna rule set (`run_drc.py --antenna_only`) passes on the library
array with these cells in it.

Both cells are DRC clean and LVS clean under the same harness as the rest of
the library. They carry no timing arcs (a constant output has none). Their
leakage is measured directly on the tie netlists — one deck per cell, the
same settled-tail average the sequential cells use (`work/tie_leakage.py`:
0.011 / 0.013 nW) — not borrowed from `inv_1`, so `cell_leakage_power` is a
measurement like every other leakage number in the file.

Without them the library cannot be used by a digital flow at all: LibreLane
calls Yosys' `hilomap` and OpenROAD's `insert_tiecells` unconditionally, and
a constant reaching a cell input has nowhere else to go.

### Simulating the Verilog models

The models are vendor-style: each sequential cell feeds its UDP from
`delayed_*` wires and drives a `notifier` reg, and both are produced by the
timing checks **inside** the specify block. Icarus Verilog cannot compile
those blocks -- it rejects `ifnone` on an edge-sensitive path -- and deleting
them is not enough on its own, because `delayed_*` is then undriven and
`notifier` sits at X, so every flip-flop output stays X for the whole run and
the simulation looks broken rather than unsupported.

`work/make_functional_models.py` writes a zero-delay copy for exactly this
case: it drops the specify blocks, adds `assign delayed_<PORT> = <PORT>;`
for each delayed wire, and initialises the notifiers.

```sh
python3 work/make_functional_models.py verilog/sg13g2_stdcell_hv.v hv_func.v
iverilog -g2012 $PDK/libs.ref/sg13g2_stdcell/verilog/sg13g2_udp.v \
    hv_func.v <netlist>.v <testbench>.v
```

The UDP primitives are not shipped here (see the note under
[Directory layout](#directory-layout)); use the PDK's `sg13g2_udp.v`.

## What this library is not

- **All 84 cells have GDS** (see [Layout](#layout)), DRC clean and LVS
  clean, with LEF abstracts on a 17-track site. 66 came from the library
  retarget, 18 from per-cell generators.
- **Two cells have no Liberty entry.** The statetable clock gates
  `lgcp_1` / `slgcp_1` are drawn but not yet characterized, so a digital
  flow cannot pick them.
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
├── lef/sg13g2_stdcell_hv.lef         84 macros + CoreSiteHV (0.48 x 7.14)
├── lib/                              Liberty, 3.3 V typical
├── gds/sg13g2_stdcell_hv.gds         84 cells: 66 retargeted + 18 generated
├── doc/sg13g2_stdcell_hv.celllist
├── klayout/pymacros/*.lym            KLayout cell-library registration
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

### klayout

`klayout/pymacros/sg13g2_stdcell_hv.lym` registers the GDS as a KLayout
**cell library**: all 84 cells appear in the Instance dialog under
the library name `sg13g2_stdcell_hv`, next to the PDK's own libraries, and
place like any library cell. Enable it by adding the repository's
`klayout/` directory to the KLayout search path,

```sh
export KLAYOUT_PATH=/foss/designs/sg13g2_stdcell_hv/klayout:$KLAYOUT_PATH
```

or by symlinking the macro into `~/.klayout/pymacros/` (it finds the GDS
relative to its own location; `SG13G2_HV_HOME` overrides that if the macro
is copied elsewhere). Layer display comes from the PDK's sg13g2 technology
as usual — open or create layouts with that technology selected.

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

### librelane

`librelane/` is a complete LibreLane SCL — the files `work/make_pdk_pr.py`
installs as `libs.tech/librelane/sg13g2_stdcell_hv/` in a PDK checkout:
the SCL `config.tcl` (site `CoreSiteHV`, 0.48 × 7.14; HV driving, tie,
fill, decap, diode and CTS cells), `tracks.info`, the latch and mux
techmaps, both exclude lists, and `sdfbbp_map.v`. The installer also
patches the PDK-level `libs.tech/librelane/config.tcl` with the HV corner
block (the LIB dict there hardcodes the thin-oxide liberty filenames and
LibreLane validates every LIB path eagerly) and copies the thin-oxide
`sg13g2_tech.lef` into `libs.ref/sg13g2_stdcell_hv/lef/` (the PDK config
globs it per-SCL). A design then needs only:

```yaml
STD_CELL_LIBRARY: sg13g2_stdcell_hv
```

Flip-flops and latches map through Yosys `dfflibmap` / the latch techmap
exactly as in the thin-oxide flow: all 9 flops and 5 latches carry
liberty **and** layout views. The exclude lists mirror the thin-oxide
ones (`sdfbbp_1`, `dfrbp_2`). `sdfbbp_map.v` remains available as an
opt-in for DFT flows that want every flop on the scan cell — its header
explains how (it needs `sdfbbp_1` removed from `synth_exclude.cells` and
a design-level `SYNTH_EXTRA_MAPPING_FILE`, which is not PDK-scoped); all
of its clocked mappings are proven against the Yosys cell semantics with
`equiv_induct`. Tri-states map through `SYNTH_TRISTATE_MAP`
(`tribuff_map.v`, Yosys' `$_TBUF_` onto `sg13g2_hv_ebufn_2`) with
`TRISTATE_CELLS` listing both footprints, mirroring the thin-oxide SCL.
The 2 clock gates have no mapping — they are drawn but not yet
characterized, and the thin-oxide SCL excludes its own clock gates too.

At install time `finalize_lib.strip_layoutless` still guards the
liberty ⊆ LEF invariant; with all 84 cells drawn it strips nothing.

```sh
cd work
python3 vm_sweep.py             # re-derive the PMOS width factor
python3 ratio_check.py          # sizing-criterion and width-independence checks
python3 gen_hv_lib.py           # regenerate the library
python3 verify_logic.py         # combinational equivalence
python3 verify_seq.py           # sequential equivalence
python3 verify_sch.py           # schematics and CDL vs SPICE netlist
# Characterization is per PVT corner. One command runs a whole corner --
# CharLib for what it can express, then the project's own procedures for
# the sequential cells, then direct ngspice measurement for the cells no
# characterizer models (tri-states, clock gates, bus holder, tie cells),
# then drive limits, areas and the data gate. corners.py defines the
# corners; work/run_corner.sh documents why the order is what it is.
./run_corner.sh typ             # or: fast | slow
./run_corner.sh fast direct     # resume a failed run from a given stage

# The individual steps, if you need them one at a time:
python3 gen_charlib_config.py --corner typ   # CharLib configuration
./run_charlib.sh typ                          # corner picks config + output
python3 merge_lib.py <lib> seq_typ.lib        # sequential run merged in
python3 seq_leakage.py  --corner typ          # single-state sequential leakage
python3 tie_leakage.py  --corner typ          # measured tie-cell leakage
python3 char_sighold.py --corner typ          # bus holder: no timing arcs
python3 char_tristate/char_tristate.py --corner typ   # + enable/disable arcs
python3 char_clockgate/char_clockgate.py --corner typ all
python3 finalize_lib.py --corner typ  # drive limits from the table axes,
                                      # physical-cell stubs (measured
                                      # leakage/cap), corner-suffixed name
python3 update_lib_area.py      # Liberty area from the LEF, every corner
python3 verify_lib.py --corner typ    # gates the shipped Liberty as data
python3 lctime_compare.py       # independent characterizer cross-check
python3 view_matrix.py          # per-cell view coverage matrix

python3 layout_retarget.py      # gds/ (66 cells, prints the 18 skips)
python3 fix_rail_contacts.py    # rail taps onto the site-centred 0.48 um grid
python3 grid_align_pins.py --apply  # widen off-track pins that have room
python3 sync_netlist_widths.py  # SPICE + CDL follow the drawn geometry
python3 flop_pilot/gen_seq.py   # the 8 flops (per-cell y-map recipe)
# latches, ebufn drives, lgcp_1, sighold: work/cell_dev/*/gen_*.py,
# each gated by work/cell_verify.py before merging into gds/
python3 fix_well_nwc1.py        # wells to the strict analog HV rules
python3 gen_lef.py              # lef/ (site + 84 macros)
python3 make_drc_top.py         # abutted 2-row DRC context (padded pitch)
python3 make_shared_rail_rows.py  # shared-rail mixed-row DRC context
./run_lvs.sh                    # per-cell LVS
# DRC: PDK run_drc.py on work/drc/drc_top.gds and work/drc/shared_rail.gds,
# default flags
```

`gen_hv_lib.py` refuses to generate if its parasitic formulas stop reproducing
the thin-oxide library, so a PDK update that changes the device geometry
constants fails loudly instead of silently producing wrong parasitics.

## Licence

Derived from `sg13g2_stdcell`, Copyright 2023 IHP PDK Authors, Apache License
2.0. This derived work is distributed under the same terms.

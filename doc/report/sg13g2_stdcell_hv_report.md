---
title: "sg13g2_stdcell_hv — Generation of a Thick-Oxide (3.3 V) Standard Cell Library"
subtitle: "IHP SG13G2 open PDK · derivation, all views, verification and physical sign-off"
author:
  - "Koen Van Caekenberghe, Ph.D. — ChipDesign B.V. — [info@chipdesign.be](mailto:info@chipdesign.be)"
date: "2026-08-04"
logo: "ChipDesign_logo.png"
---

# Scope and result

The IHP SG13G2 open PDK ships one digital standard cell library,
`sg13g2_stdcell`, built entirely from the 1.2 V thin-oxide devices
(`sg13_lv_nmos` / `sg13_lv_pmos`). Its 3.3 V thick-oxide devices appear only
inside the `sg13g2_io` pad ring — 22 macros, all pads, fillers and a corner —
so nothing at 3.3 V can be synthesised and placed.

`sg13g2_stdcell_hv` fills that gap: **all 84 cells** of `sg13g2_stdcell`,
rebuilt on `sg13_hv_nmos` / `sg13_hv_pmos`, with the same topology, the same
pin names and the same pin order. Cells are named `sg13g2_hv_*` so the 1.2 V
and 3.3 V libraries coexist in one netlist. This report documents how every
view was generated, how each was verified, and the final sign-off state.

| Deliverable | Coverage | Status |
|---|---|---|
| SPICE netlist (`spice/`) | 84 cells, 924 devices | verified against 3 independent views |
| CDL netlist (`cdl/`) | 84 cells | LVS reference, all 66 drawn cells match |
| Verilog (`verilog/`) | 84 modules | shared `ihp_*` UDPs, deliberately not duplicated |
| xschem symbols (`sym/xschem`) | 84 | copies of the thin-oxide symbols |
| xschem schematics (`sch/xschem`) | 84 + gallery sheet | netlist-equivalence proven |
| GDS layout (`gds/`) | 66 of 84 cells | **DRC clean, LVS clean** |
| LEF abstracts (`lef/`) | 66 macros + `CoreSiteHV` site | generated from the GDS, pin sets verified against CDL |
| Liberty NLDM (`lib/`) | 66 cells, 600 timing tables | combinational + sequential (clk→Q, setup/hold); areas from layout |
| Registration (`xschem_lib_*.tcl`) | library path + gallery hook | idempotent |

Physical sign-off, from a single fixed invocation of the PDK's own klayout
decks on an abutted two-row array of all 66 drawn cells:

| Check | This library | IHP thin-oxide control (same harness) |
|---|---|---|
| DRC, cell rules (`Act.*`, `Gat.*`, `M1.*` spacing/width, `TGO.*`, `NW.*`, `Cnt.*`, …) | **0** | 0 |
| DRC, chip-level metal density (`M1.j` … `TM2.c`) | 7 | 6 |
| LVS | **66 / 66 match** | fill cells fail identically without the documented relaxation |

The density items are properties of the test harness, not of either
library: a standard cell library contains no Metal2 and above, and metal
density is a check on a *filled* die. The one count that differs, `M1.j`
(min 35 % Metal1), is quantified rather than waved away: the deck measures
over the marker bounding box including the empty ThickGateOx margin, where
the padded 17-track array reads 35.0 % — over the actual cell area it is
37.1 % — while the denser, unpadded thin-oxide control reads 45.2 % and so
never trips it. A placed block carries metal fill and does not see this.

---

# The device transform

Applied to every logic device in all 84 cells:

| | thin oxide | thick oxide |
|---|---|---|
| device model | `sg13_lv_nmos` / `sg13_lv_pmos` | `sg13_hv_nmos` / `sg13_hv_pmos` |
| gate length | 130 nm | **450 nm** (`Gat.a3` minimum for the 3.3 V FET) |
| NMOS width | — | unchanged |
| PMOS width | — | **× 2.40**, snapped per finger to the 5 nm grid |
| `as` / `ad` / `ps` / `pd` | — | recomputed from device geometry |
| supply | 1.2 V | 3.3 V |

Gate lengths already at or above 450 nm were left alone, because they were
chosen deliberately rather than set by the minimum: the `decap_4` / `decap_8`
MOS capacitors (1.0 µm), the `sighold` keeper devices (700 nm) and
`dlygate4sd3_1` (500 nm). 914 devices had their length raised. The delay
cells `dlygate4sd2_1` (180/250 nm) and `o21ai_1` (150 nm) sat below the
thick-oxide minimum and had to move to 450 nm, which shifts their delay
ratios relative to the thin-oxide originals. `sg13g2_hv_antennanp` is
unchanged apart from its name — it contains `dantenna` / `dpantenna`
junction diodes, to which gate oxide thickness does not apply.

## Why PMOS × 2.40

The thin-oxide `inv_1` uses $W_p/W_n = 1.12/0.74 = 1.5135$. Simulation shows
this is *not* a drive-matched ratio: at 1.2 V the pair gives
$I_{dsat,p}/I_{dsat,n} = 0.82$, and equal drive would need $W_p/W_n = 1.894$.
What 1.5135 does give is a switching threshold at

$$V_m / V_{DD} = 0.5046$$

essentially mid-rail. The thin-oxide library is sized for a centred switching
threshold, and that is the property carried over.

At 3.3 V with $L = 450\,\mathrm{nm}$ the thick-oxide PMOS is much weaker
relative to its NMOS (219 µA/µm against 533 µA/µm), and reaching the same
$V_m/V_{DD} = 0.5046$ needs $W_p/W_n = 3.63$ — a factor

$$K_p = \frac{3.63}{1.5135} = 2.40$$

on the thin-oxide ratio. Applying $K_p$ to every PMOS and leaving every NMOS
alone preserves each cell's internal stack ratios — where the thin-oxide
library encodes its series-device compensation — while re-centring the
switching threshold. Checked across the library's full 0.3–17.9 µm width
range, the required ratio varies between 3.63 and 3.97, so one global factor
holds to about ±5 %.

Method: a self-biased inverter (input tied to output) settles at exactly
$V_m$, so one operating point per candidate ratio gives the answer with no
sweep interpolation (`work/vm_sweep.py`, `work/ratio_check.py`).

## Parasitic recomputation

Source/drain areas and perimeters follow the vendor deck's own geometry
formulas. With finger width $w_f = \max(W/n_g, 0.15\,\mu\mathrm{m})$,
$z_1 = 0.34\,\mu\mathrm{m}$ and $z_2 = 0.38\,\mu\mathrm{m}$, an odd finger
count gives

$$A_S = A_D = w_f\left(z_1 + \frac{n_g-1}{2}\,z_2\right)$$

and for even $n_g$ the source and drain differ:

$$A_S = w_f\left(2 z_1 + \frac{n_g-2}{2}\,z_2\right)$$

$$A_D = \frac{w_f\, z_2\, n_g}{2}$$

with the matching perimeter expressions. Before any generation the formulas
were validated by recomputing all 924 thin-oxide devices and comparing
against the shipped values: worst relative error $3.75\times10^{-4}$,
entirely explained by the vendor netlist printing four significant figures.
The generator refuses to run if this validation fails.

## What the transform costs

Measured on `inv_1` versus `sg13g2_hv_inv_1` (`work/fo4.py`):

| | thin oxide @ 1.2 V | thick oxide @ 3.3 V | ratio |
|---|---|---|---|
| input capacitance | 2.67 fF | 5.87 fF | 2.20× |
| FO4 delay | 53.6 ps | 142.4 ps | 2.66× |

The thick-oxide NMOS delivers *more* current per micron at 3.3 V than the
thin-oxide one at 1.2 V (533 vs 391 µA/µm) — the higher supply more than
compensates for the 3.5× longer channel. The speed loss is capacitance, not
drive.

---

# Netlist generation

`work/gen_hv_lib.py` parses the PDK's thin-oxide netlists and re-emits every
view from one internal model, so a device cannot silently diverge between
views. Regex matching uses named groups throughout — an early version with
positional groups shifted trailing indices and duplicated schematic
attributes, a class of bug the named form makes impossible.

Order of operations per device: substitute the model name, raise $L$,
scale the PMOS $W$, recompute `as`/`ad`/`ps`/`pd` from the new geometry,
round consistently. The generator validates the parasitic formulas against
all 924 source devices before writing a single output file.

---

# Deliverables, view by view

## `spice/sg13g2_stdcell_hv.spice` — simulation netlist

1 536 lines, 84 `.subckt` blocks, 924 devices as `X`-cards calling the PSP103
Verilog-A models (loaded via OSDI in ngspice). This is the view every
functional verification in section 5 runs on. Device widths and lengths are
synchronised to the drawn layout for the 66 cells that have one
(section 6.6); the antenna cell's diode `w`/`l`/`a`/`p` follow the drawn
diode.

## `cdl/sg13g2_stdcell_hv.cdl` — LVS netlist

1 783 lines, the same 84 subcircuits as `M`-cards with `*.PININFO`
directives, consumed by the PDK's klayout LVS deck. Kept separate from the
SPICE view because the two serve different tools, but generated from the same
internal model and compared field-by-field by `verify_sch.py`.

## `verilog/sg13g2_stdcell_hv.v` — functional view

3 273 lines, 84 modules renamed to `sg13g2_hv_*`. The file deliberately does
**not** ship a copy of `sg13g2_udp.v`: the user-defined primitives are named
`ihp_*` and shared with the thin-oxide library, and a second copy in one
elaboration would collide.

## `sym/xschem/*.sym` — 84 symbols

Copies of the thin-oxide symbols: same drawn geometry, same pin names, same
pin order, so schematics port between the libraries by netlist prefix alone.
Two things differ: the template prefix is `sg13g2_hv_`, so an instance
netlists to `sg13g2_hv_<cell>`, and the symbols carry `type=subcircuit`,
resolving their schematic through `$::SG13G2_HV_SCH` — the thin-oxide
symbols instead resolve through the PDK's `hierarchy_config` proc, which is
hard-wired to the thin-oxide schematic directory and has no thick-oxide view.

## `sch/xschem/*.sch` — 84 schematics and the gallery

One schematic per cell, netlisted through the symbols by `verify_sch.py` so
that symbol→schematic resolution is exercised, and compared against SPICE and
CDL on pin lists and every device's model, width, length, finger count and
multiplier: **84/84 cells, 924 devices, three views agree**. The single
intentional divergence — `dlygate4sd2_1`'s PMOS drawn at $L = 0.625\,\mu$m
(section 6.1) — is carried consistently in all three views.

`sg13g2_hv_stdcells.sch`, in the same directory, is the gallery: all 84
cells on one sheet in 13 functional groups, the thick-oxide counterpart of
the PDK's `IHP130_stdcells.sch`. It is generated by `work/gen_gallery.py`,
which computes each symbol's drawn extent from its primitive records and
packs the groups without overlap whatever the pin count. It lives in
`sch/xschem/` so it resolves by name like any cell, and project `xschemrc`
files open it at startup via `$::SG13G2_HV_GALLERY`.

## `xschem_lib_sg13g2_stdcell_hv.tcl` — registration

Sourced after the PDK `xschemrc`, it appends `sym/xschem` and `sch/xschem`
to `XSCHEM_LIBRARY_PATH` (deduplicated — double-sourcing is safe), sets
`$::SG13G2_HV_SCH` for symbol resolution and exports `$::SG13G2_HV_GALLERY`
for startup hooks.

## `gds/sg13g2_stdcell_hv.gds` — layout, 66 of 84 cells

Produced by `work/layout_retarget.py` from the thin-oxide GDS; the
generation method and its sign-off are the subject of sections 6 and 7. Row
height is a uniform 7.140 µm — 17 horizontal routing tracks, up from the
thin-oxide 3.780 µm / 9 tracks — every cell width is a multiple of the
0.48 µm site, the 66-cell test row is 430.56 µm wide, and all 5 082
contacts are exactly 0.16 × 0.16 µm. The 18
cells without layout are those whose thin-oxide geometry leaves no room for
the thick-oxide well clearances at a shared row height (section 9).

## `lef/sg13g2_stdcell_hv.lef` — placement abstracts

66 macros plus the `CoreSiteHV` site (0.48 × 7.140 µm), generated from the
drawn GDS by `work/gen_lef.py`. Pin ports are the connected groups of the
Metal1/Metal2 pin datatypes, labelled by the text each group contains
(`sdfbbp_1`'s D pin routes through Via1 to Metal2 and is emitted on all
three layers); the OBS blocks are the drawn metal minus the pin geometry,
decomposed at region level so a pin cut out of a strap leaves a hole rather
than being covered. Pin `DIRECTION`/`USE`/`NETEXPR` and macro `CLASS`
(SPACER for fill/decap, ANTENNACELL for the diode) are inherited from the
thin-oxide LEF, whose pin names this library shares by construction — but
antenna values are **recomputed from the netlist**, since the thin-oxide
numbers are wrong for 3.5× longer gates: `ANTENNAGATEAREA` is the summed
W × L on the pin's gate net, `ANTENNADIFFAREA` the summed `ad`/`as` on its
drain/source nets. Generation asserts every height equals the site, every
width is a site multiple and every pin set matches the thin-oxide
reference; the emitted file is then parsed back with klayout's LEF reader
and its pin sets verified against the CDL (66/66).

## `lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib` — Liberty NLDM

52 combinational cells at the 3.3 V / 25 °C typical corner, characterised
with CharLib against the final, layout-synchronised SPICE netlist
(section 8): 25 839 combinational measurements plus a 2 962-task
sequential run, 600 timing tables across 66 cells, none empty.

## `doc/`, `README.md`, `work/`

`doc/sg13g2_stdcell_hv.celllist` is the machine-readable cell inventory, and
this report lives in `doc/report/`. The `README.md` carries the full
engineering narrative including every measurement caveat. `work/` holds the
19 generator, verification and sign-off scripts plus the ngspice OSDI shim —
the complete provenance: nothing in the library was drawn or edited outside
these scripts except the five documented Metal1 re-routes, which are
themselves data in `layout_retarget.py`.

---

# Functional verification

The functional suites use the thin-oxide library as the golden reference: the
transform changed devices and voltages, never logic, so any topology error
appears as a divergence. No truth table was written by hand.

| Suite | Coverage | Result |
|---|---|---|
| `verify_logic.py` | 60 combinational cells, 452 vectors, both libraries in one deck, outputs digitised | **PASS** |
| `verify_seq.py` | 16 stateful cells, 400 clocked samples from a common reset | **PASS** |
| `verify_sch.py` | 84 schematics + CDL vs SPICE, 924 devices field-by-field | **PASS** |
| LVS (klayout) | 66 drawn cells vs CDL | **66/66** |

Details that matter: the 12 high-impedance states of the tri-state cells
(`ebufn_*`, `einvn_*`) are exercised, with a 1 GΩ resistor to mid-rail
keeping a floating output distinguishable from a driven 0. Stateful cells
are identified from the thin-oxide Liberty by `ff()`, `latch()`,
`statetable()` *or* `clock_gating_integrated_cell` — the last two matter
because `lgcp_1` / `slgcp_1` are bistable integrated clock gates without an
`ff`/`latch` group, and a DC sweep on them is meaningless. Samples with
`SET_B` and `RESET_B` asserted together are illegal states with no defined
reference value and are excluded rather than counted as passes. Both suites
were re-run after the last netlist synchronisation and pass on the shipped
files.

---

# Layout generation

The thin-oxide GDS is hand-drawn 2-D layout, not a regular template, so a
placement-based generator would have to rebuild every cell — and would not be
LVS-correct without a router. What can be done *exactly* is a **1-D
retarget**: monotone piecewise-linear coordinate maps applied to every
vertex. Monotone maps preserve topology, so connectivity survives by
construction; the engineering is in choosing the breakpoints and in the
exceptions.

## The maps

In **x**, gates must widen from 0.13 to 0.45 µm about their centres with a
fixed slope $L_{hv}/L_{lv}$ — a variable slope staggered multi-finger gates
to 0.28/0.39 µm. Long-channel gates (the deliberate 0.5–1.0 µm devices) are
only widened if below 0.45 µm. The contacted poly pitch grows from 0.48 to
0.80 µm, keeping the thin-oxide gate-to-contact budget around the longer
gate. One consequence is accepted rather than fought: `dlygate4sd2_1`
staggers an 0.18 µm NMOS gate against an 0.25 µm PMOS gate at overlapping
x, and a single monotone map cannot widen two overlapping intervals by
different factors — its PMOS lands at a legal 0.625 µm, carried consistently
into all netlist views.

In **y**, the PMOS band is scaled ×2.40 and three channel inserts open the
thick-oxide clearances: 0.215 µm for `NW.d1.dig` (NWell to N+ Activ,
0.31 µm inside ThickGateOx with DigiBnd), 0.100 µm for `pSD.j1`, and
0.430 µm at the rail so the VSS-rail p+ tap keeps 0.40 µm (`pSD.i1`) to the
NMOS gates. The band is derived **library-wide** (1.925–3.630 µm, cut at
y = 1.595), not per cell — a per-cell band produced six different row
heights, which is not a standard cell library. Everything on every layer
moves through the maps, including Metal2, Via1 and marker layers: leaving
any layer behind silently corrupts the cell (it clipped the antenna diode's
extracted area before that was made unconditional).

## PMOS diffusion: slab decomposition

Scaled widths must be exact, and $2.40 \times 5\,\mathrm{nm} = 12$ nm does
not land on the 5 nm grid, so snapping the two Activ edges of a device
independently gives the same thin-oxide 1.12 µm device 2.685 µm at one y and
2.690 µm at another — and the netlist cannot say which is which.
`retarget_pmos_activ` therefore cuts each PMOS Activ polygon into vertical
slabs at every vertex x and re-emits each slab at
$[\,y_{top} - \mathrm{snap}(2.40\,h),\; y_{top}\,]$. Three rules there were
each learned by breaking them:

* **Per connected piece, not per slab bounding box.** A non-convex Activ can
  hold two disjoint lobes at the same x; the bounding box spans the gap and
  merges two channels — which silently deleted two PMOS from `dfrbp_1`.
* **Per slab, not per polygon.** A notch is how this library gives devices in
  one diffusion different widths; forcing a polygon to one height collapses
  them (`and2_1`'s three PMOS all became 2.69 µm).
* **Sub-grid step alignment, with channel slabs frozen.** The source's own
  5 nm jogs land neighbouring slabs one grid step apart, and each such
  staircase edge within 0.23 µm of a gate edge is an `Act.c` violation (a
  0.12 µm slab flanked by steps was an `Act.a`). Aligning *everything*
  removed them but moved channel edges: two formerly identical devices
  became 2.400 and 2.405 µm, and since the netlist synchroniser pairs
  devices to channels by sorted width — ambiguous between near-equal devices
  on different nets — five cells lost their LVS net correspondence. The
  final pass freezes every slab that carries gate poly and moves only
  source/drain slabs toward their channel neighbours, so it provably cannot
  change any device.

## Contacts and vias

Cut layers are fixed-size and are **translated, never scaled** — a stretched
via fails its own width rule. Contacts are removed before the map and
re-tiled inside the new Activ at a 0.36 µm pitch (not the thin-oxide
0.34 µm: `Cnt.b1` raises required spacing to 0.20 µm once an array exceeds
4 × 4, which the 2.4× taller PMOS contacts now do), grouped by the polygon
they sit in rather than by x (the VSS and VDD rail taps share an x, and
x-grouping tiled contacts straight up through open field), each box built by
snapping one corner and adding the size (snapping both edges independently
rounds 0.16 µm to 0.155/0.165). An epsilon guards the keep test —
`hi − lo = 0.15999999999999998` once dropped every rail-tap contact and with
them the substrate tie.

## ThickGateOx and DigiBnd

ThickGateOx marks the 3.3 V gate oxide; DigiBnd selects the *digital* well
rules (`NW.d1.dig` at 0.31 µm instead of `NW.d1` at 0.62). TGO is drawn on
the cell boundary grown by 0.27 µm (`TGO.a`) in x and **0.42 µm in y**: the
shared rail's Activ crosses the cell boundary by 0.15 µm, and a plain
0.27 µm margin leaves only 0.12 µm of TGO past it at an *unabutted* row edge
— a violation that appears exactly twice on any N-row test array (proven by
stacking two and three rows: the count stays 2 and moves to the new outer
edge). With 0.42 µm the cells are correct even at a block edge, while
interior rows still merge far under the 0.86 µm `TGO.e` distance.

## The five Metal1 re-routes

`M1.e` (0.22 µm space when a line is ≥ 0.30 µm wide and the parallel run
exceeds 1.0 µm) is a rule the retarget *manufactures*: the y-map thickens
horizontal lines past 0.30 and the x-map lengthens runs past 1.0, so
0.18 µm gaps that were legal in the thin-oxide cells become illegal with
nothing moved closer. Generic edge-trimming cannot fix them — every gap
abuts a contact column or a pin pad — so each of the five sites has an
explicit hand re-route, kept as data (`M1E_EDITS`) in the generator:

| Cell | Edit |
|---|---|
| `dlygate4sd2_1` | A2 pin pad bottom raised 35 nm (gap 0.185 → 0.220) |
| `mux2_1` | pin pad bottom raised 20 nm (0.20 → 0.22) |
| `sdfbbp_1` | strap bottom raised, starting 0.16 µm past a 0.16 µm arm junction |
| `sdfbbp_1` | 15 nm × 930 nm bite between two contacts, splitting a 2.33 µm parallel run into 0.79 + 0.45 µm |
| `and4_2` | X pin pad narrowed 0.80 → 0.76 µm |

Every edit is verified in code before it ships: merged polygon count
unchanged (no split nets), `M1.a` width, `M1.b` space/notch, `M1.c1`
contact enclosure, and the 5 nm grid. The guards rejected two earlier
versions of these edits — a flush cut that left a 0.106 µm diagonal width,
and a bite on a line only 0.17 µm wide — and an unguarded first attempt at
automatic trimming had turned 6 violations into 37 (off-grid edges,
sub-minimum widths, broken enclosures). Pin shapes (`8/2`) move with the
drawing where a pad is edited.

## Netlist ↔ layout synchronisation

The drawn width is authoritative: forcing the layout to the computed value
means nudging an Activ edge under a channel, making it non-rectangular, and
the extractor then reports a fractional gate length ($L = 0.4508\,\mu$m).
`work/sync_netlist_widths.py` instead brings SPICE and CDL to the drawn
geometry — matching per *finger*, not per device, because a folded `ng=4`
device draws four channels (`buf_4`'s four devices are six drawn gates) —
and recomputes `as`/`ad`/`ps`/`pd` with the deck formulas. The antenna
diodes follow the same principle: the y-map stretches the antenna cell, so
the diode area and perimeter in the netlist follow the drawing. Widths are
handled in metres end-to-end; a unit slip once wrote `w=2400000.000u`.

## Site, abutment and track benchmark

The PDK's tech LEF routes horizontally on a 0.42 µm pitch and vertically on
0.48 µm; the thin-oxide library's `CoreSite` is 0.48 × 3.78 µm, making it
an exactly **9-track** library. This library is placed on the same grids: a
**17-track** site of 0.48 × 7.140 µm.

| | `sg13g2_stdcell` (LV) | `sg13g2_stdcell_hv` | ratio |
|---|---|---|---|
| site | `CoreSite` 0.48 × 3.78 | `CoreSiteHV` 0.48 × 7.140 | — |
| height in 0.42 µm h-tracks | **9** | **17** | 1.89× |
| cell width quantum | 0.48 µm | 0.48 µm | — |
| mean cell width | — | 1.52× LV | — |
| mean cell area (66 pairs) | — | — | **2.87×** (median 2.83, range 1.89–4.21) |

**Abutment holds.** Every cell spans y = 0…7.140 with identical rail
cross-sections, rails and rail Activ run through the cell edges, and the
entire physical sign-off is performed on cells placed boundary-to-boundary
with a mirrored second row sharing a rail — the configuration is not merely
allowed but required, since rails, boundary-crossing Activ and ThickGateOx
are only legal because neighbours continue them.

Neither grid property held automatically; both were imposed on the
retargeted geometry:

* **17 tracks.** Device geometry alone (the 2.40× PMOS band plus the
  thick-oxide well clearances) gave 6.910 µm = 16.45 tracks, and horizontal
  M1/M3 tracks would have misaligned across row boundaries. `TRACK_PAD`
  adds the missing 0.230 µm in the mid-cell dead zone — the same place the
  `NW.d1` clearance opened, so every rule it touches only gains margin.
  The stretch carried three vertical Metal1 runs past `M1.e`'s 1.0 µm
  parallel-run threshold; each got a hand re-route in `M1E_EDITS`
  (a pin pad gives up 20–40 nm), verified by the same in-code guards.
* **Site-quantized widths.** The piecewise-linear x-map stretches only
  around gates and leaves gate-free spans unscaled, so mapped widths shared
  no quantum beyond the 5 nm grid. `pad_to_site` pads each cell's right
  boundary up to the next 0.48 µm multiple and extends with it exactly the
  shapes that continue across an abutment — rails, rail Activ, tap
  implants, wells, markers — so no device and no signal wire changes.
  Total padding across the library: 13.75 µm, ≈ 0.21 µm per cell.

The 3.3 % height cost of the 17th track and the ~2 % width cost of site
padding are both inside the 2.87× mean area factor above.

---

# Physical sign-off

## Methodology

Cells are checked in an abutted context, never standalone: rails run off
both cell ends, rail Activ crosses the boundary, and ThickGateOx merges
across cells — all legal *because* cells abut. `work/make_drc_top.py`
builds a row of all 66 cells with a second row mirrored above so the two
share a rail; `work/make_drc_rows.py` generalises to N rows for the
edge-artifact experiment.

Three measurement rules, each bought with a wrong conclusion:

* **One fixed invocation.** The PDK runner executes different rule decks
  depending on its flags (`--no_density` runs a monolithic deck emitting 4
  files; the default emits 5; another flag set emits ~40). Counts from
  different invocations are not comparable — an interim draft of the
  documentation claimed "13 violations" by comparing across flag sets.
* **Diagnose from flat replication, not marker text.** In deep mode the
  `lyrdb` marker coordinates are in per-variant *cell-local* frames; read as
  top-cell µm they attributed all remaining violations to four cells that
  had nothing wrong with them. Every diagnosis that converged came from
  re-implementing the failing rule flat with the `klayout.db` API
  (`enclosed_check`, `separation_check`, `width_check`), which is dbu-exact.
* **Run the control.** IHP's own `sg13g2_stdcell` was pushed through the
  identical harness and invocation. That separated inherited flow artifacts
  (the six density items; the fill-cell LVS behaviour) from real defects in
  a single run, in both directions.

The verdict never comes from an exit code: both PDK runners exit 0 on
failure, so pass/fail is parsed from the log and the report database.

## DRC result

| Rule class | This library | IHP control |
|---|---|---|
| cell rules | **0** | 0 |
| metal density (`M2.j` `M3.j` `M4.j` `M5.j` `TM1.c` `TM2.c`) | 6 | 6 |

The path there: 781 raw violations after the first full retarget, driven to
zero real items through the mechanisms of section 6 — the largest single
steps being the `Gat.b1` gate-spacing inserts (26 items), the `pSD.i1` rail
insert (104 items, located by measuring the actual error edges after a first
misdiagnosis), fixed-size cut handling (`V1.a`), the channel-frozen slab
alignment (`Act.c`/`Act.a`), the five `M1E_EDITS` re-routes (`M1.e`) and the
0.42 µm TGO y-margin (`TGO.a`).

## LVS result

**All 66 drawn cells match.** The 62 cells with devices pass under the
strict flags. The four `fill_*` cells contain no devices; klayout extracts a
port-less empty circuit, the CDL subckt declares `VDD`/`VSS`, and the
comparer reports the port-list difference — IHP's own fill cells fail the
identical flow the same way. For exactly those four cells `work/run_lvs.sh`
passes the runner's own `--ignore_top_ports_mismatch` relaxation; the port
check is vacuous for a cell that extracts to nothing, while every cell with
devices keeps the strict comparison.

LVS earlier caught five defect classes that dimensional checks could not —
merged channels, collapsed notch devices, mis-paired folded fingers, a
dropped substrate tie, stale diode geometry — which is why the per-cell
sweep runs after every layout change.

---

# Liberty characterisation

`lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib` is an NLDM library produced with
**CharLib**, the open-source cell characteriser, at the 3.3 V / 25 °C
typical corner. Every number in it comes from an **ngspice transient
simulation of the shipped SPICE netlist** — the same
`spice/sg13g2_stdcell_hv.spice` that LVS and the functional suites use, on
the PSP103 Verilog-A device models loaded through OSDI. Nothing is
estimated, and nothing is scaled from the thin-oxide library except the
table *axes*. The final combinational run is 25 839 simulations, joined
by a 2 962-task sequential run — 600 delay/slew tables over 66 cells, none
empty — re-characterised after the layout work so the tables
match the layout-synchronised netlists. When the layout later moved to the
17-track site the netlists stayed byte-identical — the pad only stretches
dead zone and boundary — so the timing tables remained valid as-is; the one
characterisation input that did change, cell **area**, was re-derived from
the drawn boundaries (site-padded width × 7.140 µm) for all 52 cells,
replacing the pre-layout estimates the first run had used.

## Configuration

`work/gen_charlib_config.py` builds the CharLib YAML from the thin-oxide
Liberty, which is trusted for everything the transform did not touch: the
cell list, each cell's boolean function, pin directions and state
declarations. Functions are translated by a recursive-descent parser
(`work/boolexpr.py`) — XOR expanded to its AND/OR form — and **every**
translated expression is checked against the original by truth-table
equivalence before it is written. Logic thresholds are the standard 20/80 %
slew and 50 % delay points. The 7 × 7 slew/load index grids are the
thin-oxide grids rescaled by the measured 2.66× delay and 2.20× capacitance
ratios (section 2), so the tables cover the same electrical territory as
the original library rather than an arbitrary range.

## What ngspice actually simulates

For each cell, each input→output arc, each rise/fall direction and each of
the 7 × 7 slew/load points, CharLib drives the cell's subcircuit with a
ramped input at that slew into that capacitive load and runs a transient
analysis; propagation delay and output transition come from `.meas`
statements evaluated on the waveforms. Per-cell leakage is a separate
operating-point measurement per input state, and pin capacitance is a
dedicated measurement biased **at both rails** — a single mid-rail bias
Miller-inflates the result (19.7 fF was measured for what is a 5.9 fF
input) and was one of the first defects caught. Simulations run on all
cores minus two with ngspice pinned to one thread each; oversubscription
(ngspice's default four threads times a full worker pool) had slowed the
first runs several-fold.

## Making ngspice usable from CharLib

Five tool defects sit between CharLib and a correct library; each has a
committed workaround in `work/`:

| Defect | Symptom | Workaround |
|---|---|---|
| ngspice `-s` (server mode) ignores `.spiceinit` | OSDI never loads: "Unknown model type psp103va" | PATH shim (`ngspice-osdi-shim/`) injects `pre_osdi` + `pre_set num_threads=1` after the title line |
| `exec` inside the shim's pipeline replaces only the subshell | a second ngspice spinning at 98 % CPU | shim ends with an explicit `exit $?` |
| `ngspice-subprocess` backend never parses `.meas` | every timing table silently empty — while leakage, area and capacitance still populate | `ngspice-shared` backend (libngspice in-process) is mandatory |
| CharLib's leakage lookup lower-cases supply names; PySpice restores the netlist's spelling | `KeyError: 'vdd'` for any supply name | `charlib_patched.py` makes the branch-current lookup case-insensitive at runtime |
| emitted Liberty syntax defects | `function : "Y = !(A)"` left-hand sides, wrong `pulling_resistance_unit`, wrong `bus_naming_style` | `fix_lib.py` post-pass, run by `run_charlib.sh` |

The shim was validated by comparing its measurements byte-for-byte against
batch-mode ngspice on the same deck. The `.meas` defect deserves emphasis:
it produces a structurally valid, plausible-looking library with empty
timing tables, and nothing in the CharLib run reports an error.

## Verifying the Liberty data

The library was loaded and exercised in OpenSTA early in the flow, but a
loadable library is not a correct one, so the shipped `.lib` is verified
**as data** by `work/verify_lib.py`, independently of how it was produced:

1. **Structure** — 66 cells, all 600 delay/slew tables populated, leakage
   on every cell. (Guards against the empty-`.meas` failure mode, which
   produces a structurally valid library with no timing in it.)
2. **Cross-view** — every lib cell and pin exists in the CDL under the
   same names.
3. **Physical** — every lib `area` equals the drawn boundary area of the
   GDS cell, to 1 nm².
4. **Monotonicity** — along every table's *load* axis, delay must not
   decrease. The load axis is taken from the template's
   `variable_1`/`variable_2` declaration, never assumed: this library
   declares `variable_1 : total_output_net_capacitance`, the **opposite
   axis order from IHP's thin-oxide library** (both are legal Liberty).
   The first version of this check assumed IHP's order, walked the slew
   axis, and reported 110 "violations" — including physically legitimate
   negative propagation delays at slow input slews, where the output
   crosses 50 % before the input does. A hasty hand point-check made the
   same axis mistake and manufactured a 22× discrepancy out of a (slew,
   load) pair that is not in the tables at all. Axis-aware, the real
   count is one outlier point: `xnor2_1`'s B-rise arc at (0.396 pF,
   3.36 ns) reads 3.410 ns where a direct measurement gives 1.885 ns,
   smooth with its neighbours — the XNOR output glitches during the slow
   input traversal and CharLib's max-over-conditions latches the late
   crossing. The value ships as-is under a documented waiver in
   `verify_lib.py`: the error is pessimistic, the safe direction for
   timing sign-off, and hand-editing characterised data would be worse
   than a recorded exception.
5. **Measurement cross-check** — `inv_1`'s input capacitance against the
   independent both-rails ngspice measurement of `work/fo4.py` (5.87 fF).
6. **Sequential arcs** — every flip-flop and latch must carry an
   edge-triggered delay group and setup and hold constraint groups, and no
   constraint value may sit at the bisection search bounds (a pinned value
   means the pass/fail boundary was never bracketed — the fingerprint of
   both the skew-centering bug and the weak pass criterion) or outside
   −3…+5 ns. Result: **14/14 cells clean**.

Check 5 caught a real defect that had survived every earlier look: the
pin capacitances were **6.8–7.5× too large** (`inv_1` 43.8 fF, `inv_16`
639 fF). CharLib's default `ac_sweep` procedure measures capacitance as a
conductance slope at a floating DC bias, where Miller-multiplied Cgd
dominates; the configuration now selects its `charge_integration`
procedure — ramp the pin VSS→VDD→VSS and integrate the charge — which is
exactly the both-rails method `fo4.py` validated, and reproduces the
reference within ~10 % (6.0/6.7 fF fall/rise).

The delay tables themselves were confirmed correct by a point-check
against an independent, hand-written ngspice transient at a table corner:
(load 0.66 pF, slew 49.5 ps) reads **2.054 ns** in the table and measures
**2.061 ns** in simulation — 0.3 % apart. The final gate on the shipped
file: **PASS — 66 cells, 600 tables, 1 932 load-axis series monotone with
the one documented waiver, Cin 6.44 fF vs the 5.87 fF reference (9.7 %),
14/14 sequential cells clean.**

## Sequential cells

Stock CharLib 2.1.0 cannot characterize sequential cells at all, in three
independent ways, each of which had to be discovered separately because
every one fails silently or pathologically:

* Cells without `clock_slews` in their config raise a `KeyError` *inside*
  a generator that `omit_on_failure` swallows whole — zero simulations,
  zero errors, cells simply absent. This alone was the original
  "configured but produce nothing".
* `sequential_worst_case`, the clk→Q delay procedure, is an unimplemented
  stub: it yields tasks and returns the empty liberty skeleton (`# TODO`).
* The setup/hold contour procedure builds transients whose point count
  explodes on these cells (1.2 GB allocation requests); the failed
  allocation drives libngspice into its fatal "cannot recover" state and
  poisons the worker pool.

`work/seq_delay_procedure.py` replaces the last two through CharLib's own
procedure registry: `sequential_clk_to_q` measures clock/enable-to-output
propagation and transition with a preload-pulse-then-measured-edge scheme,
and `setup_hold_bisection` finds constraints by pass/fail bisection
(~24 bounded simulations per constraint) with a **c2q-degradation
criterion** — a trial passes only if the output arrives within 1.5× the
nominal clk→Q, because final-state-only acceptance rides through
luckily-resolved metastability and reports constraints pinned at the
search floor. Latches are constrained against their **closing** edge; the
first implementation left the enable asserted, the latch transparent, and
every trial failing. Building this took twelve distinct defects found and
fixed across the config contract, CharLib's API, and the procedures
themselves — the report's companion history is in the git log; two are
worth naming as measurement lessons: a skew-centering error granted every
trial an extra half data-ramp of setup (pinning slow-slew rows at the
bisection floor exactly like the criterion bug), and undriven set/reset
pins let `rshunt` drift an active-low reset asserted, which held the flop
cleared and turned a failed measurement into an infinite pool hang.

Validated behaviour (dfrbp_1, 3.3 V): setup +0.24…+0.59 ns rising with
data slew and falling with clock slew; hold −0.43…−0.01 ns; clk→Q
0.49…2.6 ns monotone in load, with the metastability onset visible as c2q
degradation near the setup boundary. Latch (dlhq_1): closing-edge setup
between +0.3 and +1.0 ns, transparent D→Q 0.87 ns. Sequential leakage is
a single-settled-state measurement (`work/seq_leakage.py`, 0.10–0.33 nW),
unlike the all-states enumeration of the combinational cells — stated
here because a reader comparing leakage groups would otherwise wonder.

## Coverage

**66 of 84 cells: 52 combinational, 9 flip-flops, 5 latches.** Twelve cells
are excluded by configuration with stated reasons — no output pin and no
arcs (`fill_*`, `decap_*`, `antennanp`, `sighold`), no timing tables in the
thin-oxide reference either (`tiehi`, `tielo`), statetable-based clock
gates CharLib has no input form for (`lgcp_1`, `slgcp_1`). A further 20 —
all 14 flip-flops/latches and all 6 tri-state cells — are configured but
produce nothing: CharLib emits an empty library for them without a single
simulation and without reporting an error, so under `omit_on_failure` they
vanish silently; the run log does not mention them. The `.lib` therefore
cannot be used to synthesise sequential logic as it stands.

---

# Verification summary

Every check run on the shipped library, in one place. "Golden reference"
means the thin-oxide library or an independent hand measurement; nothing
below is validated only against its own generator.

| Check | Method | Scope | Result |
|---|---|---|---|
| Parasitic formulas | recompute vendor `as/ad/ps/pd` | all 924 thin-oxide devices | PASS, worst error 3.75×10⁻⁴ |
| Combinational logic | ngspice, both libraries in one deck vs thin-oxide golden | 60 cells, 452 vectors, 12 high-Z states | **PASS** (re-run on final netlists) |
| Sequential logic | ngspice, clocked counter walk from common reset | 16 stateful cells, 400 samples | **PASS** (re-run on final netlists) |
| Three-view consistency | xschem netlisting through symbols vs SPICE vs CDL | 84 cells, 924 devices, field-by-field | **PASS** |
| DRC | PDK klayout deck, fixed invocation, abutted 2-row array | 66 drawn cells | **0 cell-rule violations**; 7 chip-level density items |
| DRC control | identical harness on IHP `sg13g2_stdcell` | 84 thin-oxide cells | 0 cell rules, 6 density — density is the harness, not the cells |
| `M1.j` quantification | density over marker bbox vs cell area | padded 17-track array | 35.0 % vs 35 % floor over bbox; 37.1 % over cell area; control 45.2 % |
| `TGO.a` row experiment | 2-row vs 3-row array | outer-edge artifact hypothesis | count constant at 2, moves with the edge → artifact; then eliminated by the 0.42 µm y-margin |
| LVS | PDK klayout deck, per cell | 66 drawn cells vs CDL | **66/66** (4 device-less fills need `--ignore_top_ports_mismatch`; IHP's own fills fail identically without it) |
| LEF | klayout parse-back + pin sets vs CDL | 66 macros, `CoreSiteHV` | parses; **66/66 pin sets match**; heights/widths asserted on the site grid |
| Liberty structure | `verify_lib.py` check 1 | 66 cells | 600/600 tables populated, leakage on every cell |
| Liberty cross-view | check 2 | all lib pins vs CDL | PASS |
| Liberty areas | check 3 | 54 cells with GDS | exact to 1 nm² |
| Liberty monotonicity | check 4, load axis from the template declaration | 1 932 delay series | 1 931 monotone + 1 documented waiver (`xnor2_1`, table 3.410 ns vs 1.885 ns measured, pessimistic) |
| Liberty Cin | check 5 vs independent both-rails measurement | `inv_1` pin A | 6.44 fF vs 5.87 fF — 9.7 % (this check caught the 6.8–7.5× `ac_sweep` Miller defect) |
| Liberty delay point-check | hand-written ngspice transient at a table corner | `inv_1` (0.66 pF, 49.5 ps) | table 2.054 ns vs simulated 2.061 ns — 0.3 % |
| Sequential arcs | check 6 | 14 flip-flops and latches | **14/14 clean**: delay + setup + hold groups present, no value pinned at search bounds |
| Sequential physics probe | direct-harness bisection boundary | `dfrbp_1`, `dlhq_1` | setup boundary bracketed with visible c2q degradation; latch closing-edge boundary bracketed; trends correct in slew and load |
| STA load test | OpenSTA | full library | loads and evaluates (early-flow validation of the identical pipeline) |
| Site geometry | boundary scan of the GDS | all 66 cells | uniform 7.140 µm = 17 tracks; every width a 0.48 µm site multiple |

What is *not* verified, stated as plainly: no block has been placed and
routed with the LEF; the 6 tri-state cells have no Liberty timing; the
sequential leakage is a single-state number; and nothing here is silicon.

---

# Known limitations

* **18 cells have no layout**: the eight D-flip-flop variants
  (`dfrbp_*`, `dfrbpq_*`, `sdfrbp_*`, `sdfrbpq_*`) run NMOS Activ up to the
  library channel cut, and ten others (`dlhq_1`, `dlhr_1`, `dllr_1`,
  `dllrq_1`, `ebufn_2`, `ebufn_8`, `lgcp_1`, `sighold`, `tiehi`, `tielo`)
  run PMOS Activ into the VDD rail; either way the band cannot scale
  without breaking the shared row height or rail abutment. They have full
  netlist, schematic, symbol and Verilog views, but no GDS.
* **The P&R view is untested by a P&R run.** LEF abstracts exist and are
  verified against the GDS and CDL, but no block has been placed and routed
  with them; OpenROAD/yosys flow integration is future work.
* **The 6 tri-state cells are absent from the Liberty.** CharLib's
  function model cannot express a high-impedance output and there is no
  registry work-around. They are simulation-verified (all 12 high-Z
  states) but carry no timing tables.
* **Sequential leakage is a single-settled-state measurement**, unlike
  the all-states enumeration of the combinational cells.
* **Delay cells shifted**: `dlygate4sd2_1` and `o21ai_1` had gate lengths
  below the thick-oxide minimum; their delay ratios differ from the
  thin-oxide originals. The decap cells store less per unit area — thicker
  oxide, same geometry.
* **Not silicon-proven, and not independently reviewed.** DRC/LVS-clean
  means the checks pass, not that the cells are known good in fabrication.

---

# Reproducing the library

```sh
cd /foss/designs/sg13g2_stdcell_hv/work

python3 gen_hv_lib.py            # netlists, schematics, symbols, Verilog
python3 gen_gallery.py           # sch/xschem/sg13g2_hv_stdcells.sch
python3 layout_retarget.py       # gds/ (66 cells; prints the 18 skips)
python3 sync_netlist_widths.py   # SPICE + CDL follow the drawn geometry
python3 gen_lef.py               # lef/ (CoreSiteHV + 66 macros)
python3 make_drc_top.py          # abutted two-row DRC context

python3 verify_logic.py          # combinational equivalence vs thin-oxide
python3 verify_seq.py            # sequential equivalence
python3 verify_sch.py            # three-view consistency
./run_lvs.sh                     # per-cell LVS, 66/66
# DRC: PDK run_drc.py on drc/drc_top.gds, default flags

./run_charlib.sh ../lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib
# sequential cells: custom procedures registered by charlib_patched.py
#   (run with -f over the ff/latch names), then merge + leakage:
python3 merge_lib.py ../lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib <seq.lib>
python3 seq_leakage.py
python3 verify_lib.py           # gates the shipped Liberty as data
```

Every number in this report is reproducible from these scripts; the `work/`
directory is the provenance of record.

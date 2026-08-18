# sg13g2_hv_ebufn_2 / sg13g2_hv_ebufn_8 — tri-state buffer drive variants

Both cells PASS `work/cell_verify.py` (LVS match vs `cdl/sg13g2_stdcell_hv.cdl`,
KLayout PDK DRC clean in the abutted two-row context, magic DRC clean —
zero flags, not even the tolerated Cnt.c/M1.e classes — strict N-well
structure ok, all pins labelled and on-track). Verification JSONs:
`sg13g2_hv_ebufn_2.verify.json`, `sg13g2_hv_ebufn_8.verify.json`.

## Method: per-cell retarget from the LV drawn cells, not finger surgery

Instead of adding/removing fingers in the drawn `sg13g2_hv_ebufn_4`, each
cell is produced by `gen_ebufn.py` as a 1-D retarget of the corresponding
hand-drawn thin-oxide cell (`sg13g2_ebufn_2/8` in the PDK LV GDS), the same
recipe that produced the passing `sg13g2_hv_dfrbpq_1` pilot
(`work/flop_pilot/gen_dfrbpq.py`). The library retarget
(`work/layout_retarget.py`) had skipped both cells for exactly one reason:
the output PMOS source ties to VDD by butting its p+ Activ into the n+ VDD
rail tap through one neck (ebufn_2: x 1.870–2.170, ebufn_8: x 7.825–8.125),
so the PMOS Activ top reached the rail band. Handling:

* the neck is removed before the map (asserted to be exactly the drawn
  box), leaving a flat-topped PMOS body the map accepts;
* the **standard library maps** are used unmodified (unlike dfrbpq no
  custom y-map is needed: NMOS Activ tops are 1.28/1.36 um, below the
  library channel cut 1.595). Asserted: rails at −0.22/0.22 and
  6.825/7.36, tap Activ 6.99/7.29, pSD top 6.92, NWell top 7.53 — the
  exact template of the shipped library;
* the neck is re-drawn in the HV frame from the 2.4× taller PMOS body top
  to y = 6.99, merging with the tap strip (slgcp_1 convention: p+ under
  the pSD cover to 6.92, n+ for the last 70 nm; LVS connects through
  `psd_ntap_abutt`). The neck's VDD-strap contact and rail M1 stub map
  with the cell; asserted to keep 0.07 Activ / 0.05 M1 enclosure;
* upper pSD rebuilt to the template band y 2.635–6.92 (±0.07 edge
  overhang); N-well rebuilt to the strict `fix_well_nwc1.py` convention
  (bottom 2.570, top 7.53, lateral overhang ±0.62, 0.62 halos around PMOS
  active / NMOS active / p-tap, square-corner asserts, 5 nm grid);
* rail tap contacts re-tiled on the site-centred 0.48 um grid with the
  `fix_rail_contacts.py` guards (18 per rail in ebufn_2, 40 in ebufn_8);
* ThickGateOx boundary +0.27/+0.42 and DigiBnd = prBoundary, per
  `layout_retarget.add_tgo`.

## Finger plan (all L = 0.45 um; LVS runs `--combine_devices`)

Widths are exact by construction: the map multiplies each PMOS finger
width by 2.40 (1.12 → 2.690, 1.00 → 2.400, 5 nm snap) and leaves NMOS
fingers untouched — identical to how the shipped HV CDL widths were
derived from the LV layout.

**sg13g2_hv_ebufn_2 — 18 sites (8.64 × 7.14 um)**

| CDL device | W (um) | ng | drawn fingers |
|---|---|---|---|
| MN2/MN3 (output nmos) | 1.480 | 2 | 2 × 0.740 each (4 total) |
| MP2/MP3 (output pmos) | 5.380 | 2 | 2 × 2.690 each (4 total) |
| MN0/MN1 (pre-driver nmos) | 0.640 | 1 | 1 × 0.640 each |
| MP0/MP1 (pre-driver pmos) | 2.400 | 1 | 1 × 2.400 each |

**sg13g2_hv_ebufn_8 — 40 sites (19.20 × 7.14 um)**

| CDL device | W (um) | ng | drawn fingers |
|---|---|---|---|
| MN2/MN3 (output nmos) | 5.920 | 8 | 8 × 0.740 each (16 total) |
| MP2/MP3 (output pmos) | 21.520 | 8 | 8 × 2.690 each (16 total) |
| MN0 (A pre-driver nmos) | 1.480 | 2 | 2 × 0.740 |
| MP0 (A pre-driver pmos) | 5.380 | 2 | 2 × 2.690 |
| MN1 (TE_B pre-driver nmos) | 0.740 | 1 | 1 × 0.740 |
| MP1 (TE_B pre-driver pmos) | 2.690 | 1 | 1 × 2.690 |

Note the ebufn_8 CDL keeps the TE_B pre-driver at ebufn_4 size (0.740 /
2.690) and doubles only the A pre-driver — read from the `.SUBCKT`, and
reproduced exactly.

## What moved vs ebufn_4 (23 sites)

These are not edits of the ebufn_4 polygons: each cell inherits the LV
hand placement of its own drive (output stage as one folded finger array,
pre-drivers at the opposite end). All template bands are identical to
ebufn_4: prBoundary 7.140 tall, M1 rails, tap Activ, pSD bands, strict
N-well (±0.62 overhang, bottom 2.570), TGO/DigiBnd. Differences: cell
widths (18/40 vs 23 sites), NMOS device band y-extent (ebufn_2
0.970–1.710, ebufn_8 1.050–1.790, vs ebufn_4 1.000–1.740 — internal only;
edge-shared layers are unchanged so abutment is unaffected), and pin
locations follow the LV cells (all signal pins on the 0.48 vertical
tracks per the verifier's check).

## Not certified by this signoff

* Metal density (chip-level; the deck is run with `--no_density` as for
  the whole library) and antenna (chip-level).
* PEX / post-layout timing; the Liberty/LEF views of the library have not
  been regenerated for these two cells.
* Device sizing is taken as-given from the shipped CDL golden netlist.

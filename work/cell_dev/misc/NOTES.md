# cell_dev/misc — sg13g2_hv_lgcp_1 and sg13g2_hv_sighold

Two previously undrawn cells of `sg13g2_stdcell_hv`, produced entirely by the
generator scripts in this directory (no library file was modified; the GDS
here are single-top-cell candidates, not yet merged into the library).

Signoff gate (both PASS, see `cell_verify.json`, fresh run of
`python3 work/cell_verify.py` on both GDS):

| cell               | sites | LVS   | KLayout DRC (abutted ctx) | Magic (full, euclidean) | structure | pins |
|--------------------|-------|-------|---------------------------|-------------------------|-----------|------|
| sg13g2_hv_lgcp_1   | 31    | match | clean                     | No errors found         | ok        | on-track |
| sg13g2_hv_sighold  | 6     | match | clean                     | No errors found         | ok        | on-track |

## sg13g2_hv_lgcp_1 (`gen_lgcp.py`)

Derived by surgery from the drawn `sg13g2_hv_slgcp_1` (32 sites, 22 devices).
Exact CDL diff (slgcp -> lgcp, done net-by-net; slgcp names):

* net mapping: slgcp `net6/net4/net5/net2` -> lgcp `net1/net6/net3/net5`;
  slgcp `net1` (the shared PMOS/NMOS series mid node) **splits** into lgcp
  `net4` (PMOS side) and `net2` (NMOS side) — the two nets are joined by a
  Metal1 column in slgcp and are separate nets in lgcp, so the column
  (x[2.545,2.830] y[2.555,4.425], original coords) is cut.
* removed: MP2 (net3 SCE VDD, w=2.015) and MN2 (net1 SCE VSS, w=0.550), the
  SCE gate poly / pin metal / label / contacts, and the active under them
  (both device actives trimmed to x>=1.000).
* rewired: slgcp MP3 (net1 GATE net3) source diffusion (old series node
  net3, x[1.00,1.38]) tied to VDD with a new rail finger + 2 contacts.
* resized (multiset diff -3 pmos 2.015u / -3 nmos 0.550u, +2 pmos 2.400u /
  +2 nmos 0.640u): GATE pmos and CLKBB pmos 2.015 -> 2.400, GATE nmos and
  CLKB nmos 0.550 -> 0.640. All W growth is away from the fixed N-well
  bottom (up for PMOS, MN3; down for MN4, whose top is blocked by the CLKb
  poly bridge), with Act.c = 0.23 lateral cover on the raised/lowered bands
  and Gat.c = 0.18 endcap extensions on the three affected polys.
* shrink: the freed SCE column allows exactly one 0.48 site; all content
  shifts x-0.48 and the frame is redrawn at W = 14.880 (31 sites). More
  than one site is not available: the GATE leg active now starts 0.52 from
  the edge; a second site would put it 0.04 from the boundary.

Generator self-checks: gate multiset (10 NMOS 0.42x2/0.64x4/0.74x4, 10 PMOS
1.01x2/2.015x4/2.4x2/2.69x2, all L=0.45) and the strict N-well asserts.

## sg13g2_hv_sighold (`gen_sighold.py`)

Built from scratch (no drawn relative) following the frame conventions the
way `work/gen_tie_cells.py` / `work/fix_well_nwc1.py` document them,
dimensions read off the drawn `sg13g2_hv_inv_1`. 6 sites (2.88 um). One
shared active per row, device order

    net1 | gate A (SH, L=0.45) | VSS/VDD | gate B (net1, L=0.70) | SH

PMOS W steps 1.08 -> 0.72 at x=1.20 between the gates (honours Act.c=0.23
on both sides); the L=0.70 feedback devices are per the CDL. Single
bidirectional pin SH labelled on the SH Metal1 column, on the 0.48 grid.
N-well is the plain strict-convention box (no jogs needed: PMOS active
bottom 3.90 >= 2.570+0.62+margin).

## Conventions honoured (checked mechanically by cell_verify)

prBoundary (0,0)-(W,7.140), W = k x 0.48; M1 rails VSS y[-0.22,0.22] /
VDD y[6.825,7.360] with 8/2 pin twins and 8/25 labels; rail tap contacts
0.16 wide at x = 0.16 + 0.48k; p-tap / n-tap strips y[-0.15,0.15] /
y[6.99,7.29]; pSD bands (+-0.07 sighold as inv_1, -0.30/-0.16 lgcp as
slgcp); ThickGateOx (-0.27,-0.42)-(W+0.27,7.56); DigiBnd = boundary;
N-well bottom 2.570, top 7.530, lateral overhang exactly 0.62, >=0.62
enclosure of PMOS active / spacing to NMOS active and p-tap.

## What the signoff does NOT certify

* Density (chip-level, skipped by the deck runner as in the library flow).
* PEX / post-layout simulation; the cells are uncharacterised (no Liberty
  timing/power data was produced; lgcp_1's library .lib entry, LEF, SPICE,
  Verilog and gallery views are all still to be generated if/when the cells
  are merged into the library, e.g. via gen_lef.py and the charlib flow).
* Device sizing is taken verbatim from the shipped CDL, not re-verified
  electrically.
* Abutment coverage is what cell_verify builds: inv_1 | cell | nand2_1,
  second row mirrored about the VDD rail — not every possible neighbour.

# Tri-state cell characterization, sg13g2_stdcell_hv

Six cells: `sg13g2_hv_ebufn_2/_4/_8` (tri-state buffers, `Z = A`) and
`sg13g2_hv_einvn_2/_4/_8` (tri-state inverters, `Z = !A`).  Pins `Z`, `A`,
`TE_B` (active-low enable), `VDD`, `VSS`.

## Why these were characterized by hand

CharLib built every other cell in this library, but it has no concept of a
high-impedance output: there is no `three_state` schema key, no
`three_state_enable`/`three_state_disable` timing type, and no code path in
`charlib/characterizer/procedures/` that would ever emit one.  These six cells
were listed in `work/charlib_sg13g2_stdcell_hv.yml` and silently produced
nothing usable.  lctime can carry a `three_state` attribute on the output pin,
but it deliberately pins the enable input to its active level and skips the
enable/disable arcs, so it cannot fill them either.

So they were measured directly, with `work/char_tristate/char_tristate.py`,
using the same simulator, models, thresholds and grids as the rest of the
library.

## Common measurement setup

| item | value |
| --- | --- |
| simulator | ngspice via `work/ngspice-osdi-shim` (PSP103 OSDI preload), `env -u PYTHONPATH` |
| models | `/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib mos_tt` |
| netlist | `spice/sg13g2_stdcell_hv.spice` |
| VDD | 3.3 V, 25 C |
| propagation thresholds | input 50 %, output 50 % |
| slew thresholds | 20 % / 80 % |
| input ramp | linear, full rail-to-rail time = slew / 0.6 (CharLib `utils.slew_pwl`, i.e. the ramp every other table in this library was measured with) |

`.option trtol=1` (which CharLib sets through PySpice) is **not** used: on
these decks it drives ngspice into a state where a 10 ns transient does not
finish in two minutes.  Left at the default, the same deck runs in under a
second and the smoke-test delay agrees with the shipped `sg13g2_hv_buf_4`
numbers.

### Grids

Library convention, from `work/gen_charlib_config.py`: the thin-oxide axes
scaled by the factors measured in `work/fo4.py`.

* slew axis (all cells, `index_2`):
  `0.049480, 0.256960, 0.462840, 0.876200, 1.704530, 3.359580, 6.669680` ns
  (thin-oxide axis x 2.66)
* load axis (`index_1`): `max_capacitance` x
  `{1/300, 0.078, 0.13, 0.216, 0.36, 0.6, 1.0}`, with `max_capacitance` =
  thin-oxide value x 2.20 -> 1.32 / 2.64 / 5.28 pF for `_2` / `_4` / `_8`

Every emitted axis string is checked byte-for-byte against the axes already
present in the shipped `lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib`
(`verify_fragment.py` check 5); all six cells reuse axes that shipped cells
of the same drive already use.

**One asymmetry worth knowing when comparing against the thin-oxide tables.**
The thin-oxide tri-state cells (only these; not `a21o_1`, `buf_4`, ...) offset
their load axis by the Z pin's own capacitance -- `sg13g2_ebufn_4`'s load axis
starts at 0.00984 pF (= 0.001 + its `rise_capacitance` of 0.00884) and ends at
1.20884, and the `cell_fall` tables use a *different* axis again, offset by
`fall_capacitance`.  The HV grid does not do this, because no other HV cell
does and the brief required the axes to match shipped HV cells exactly.  The
consequence is that at load index 0 the HV cell carries 0.0022 pF against a
scaled thin-oxide 0.0217 pF -- ten times lighter -- so the HV/LV ratio at that
one column is meaningless.  `verify_fragment.py` reports the median over load
points 2-7 for that reason, and the full-grid spread alongside it.

**Axis order.** The HV templates declare

```
lu_table_template (delay_template_7x7) {
  variable_1 : total_output_net_capacitance ;
  variable_2 : input_net_transition ;
```

so in every emitted table `index_1` is the LOAD axis and `index_2` the SLEW
axis -- the opposite of the thin-oxide library, whose tables are transposed
relative to these.  All tables here are row-major over the load axis.

### Templates

No new `lu_table_template` is needed.  Every table uses the existing
`delay_template_7x7`.  Nothing has to be added to the library header.

## Arc definitions

### 1. `A -> Z`, `timing_type : combinational`

Enable asserted (`TE_B` = 0).  Ordinary delay and transition:

* `cell_rise` / `cell_fall`: A's 50 % crossing to Z's 50 % crossing
* `rise_transition` / `fall_transition`: Z 20 % -> 80 % (and 80 % -> 20 %)

`timing_sense` is `positive_unate` for ebufn, `negative_unate` for einvn.

Deck: one ideal PWL source on A drives seven independent copies of the cell,
one per load point, so all seven load points see a bit-identical stimulus and
one simulation covers a whole table row-set.  A goes low->high->low in one
transient with a settling interval of `max(10 x slew, 60 ns)` between edges,
so rise and fall arcs come from the same run.

### 2. `TE_B -> Z`, `three_state_enable` (ebufn) / `three_state_enable_rise` (einvn)

`timing_sense : negative_unate`, `sdf_edges : start_edge`.

The output starts floating at the rail **opposite** the one it will be driven
to, held there by a 1 Gohm keeper resistor (the trick `work/verify_logic.py`
uses for its high-Z checks) and started there with `.ic`, so the measured edge
is a full swing.  `TE_B` then falls with the grid slew and the cell takes the
node over.

* `cell_rise` / `cell_fall`: `TE_B` 50 % to Z 50 %
* `rise_transition` / `fall_transition`: Z 20 % -> 80 % into the grid load

Every enable simulation additionally measures `v(Z)` at the instant before the
`TE_B` edge and the script **rejects the run** if the keeper let the node drift
more than 5 % of VDD off its rail.  It never did: thick-oxide off-current is
about 1e-4 of the thin-oxide equivalent, so 1 Gohm holds even the smallest
0.0022 pF grid load.  Repeating the whole sweep with a 1 Mohm keeper changes
the answers by less than 0.3 %, which is the check that the keeper is not
part of the answer.

At the slowest slews and the lightest loads this arc produces **negative**
delays (the output reaches 50 % before `TE_B` does).  That is real and is kept
as measured; `work/verify_lib.py`'s own docstring notes the same effect for
combinational arcs at slow input slews.  The thin-oxide library clamps these
entries to a floor instead (`sg13g2_ebufn_4` repeats `0.074755, 0.074756,
0.074757, 0.074758` down its slowest-slew rows -- a clamp, not a measurement).
The tables here are still monotone along the load axis, which is what
`work/verify_lib.py` check 4 enforces.

### 3. `TE_B -> Z`, `three_state_disable` (ebufn) / `three_state_disable_rise` (einvn)

`timing_sense : positive_unate`, `sdf_edges : start_edge`.

**This is the one arc that could not be measured the way the task described,
and the deviation is deliberate.  Read this section before using the numbers.**

The brief was: load Z with the grid capacitance and a 1 Gohm keeper, switch
`TE_B` to disable, and time from `TE_B`'s 50 % crossing to the output leaving
its driven level through the slew threshold.  That measurement is not
physically meaningful here.  Once the driver lets go, *nothing but the keeper
moves the node*, so the answer is

```
t = 0.2 x R_keeper x C_load  =  0.2 x 1e9 x 2.64e-12  ~  0.5 ms
```

-- five to six orders of magnitude larger than any cell delay, and exactly
proportional to the load.  There is no keeper value that fixes this: to make
the decay fast enough to be comparable with the turn-off it would have to be
of the order of the cell's own on-resistance (~1 kohm), at which point the
enabled cell can no longer hold its own output at the rail and the measurement
has no starting point.  Any voltage-threshold criterion on a capacitively
loaded Hi-Z node is load-dominated by construction.

The thin-oxide library's disable tables are *exactly* load-independent -- its
seven entries along the load axis differ only by a 1e-9 ns increment, which is
a synthetic monotonicity epsilon, not seven measurements -- which confirms
that its disable numbers are not voltage-threshold measurements either.  They
are turn-off times, measured once per slew.  How they were obtained is not
documented in the shipped library and has not been reverse-engineered here.

**What is measured instead.**  The output node is held by an ideal source at
exactly the slew threshold it would have to cross on its way out of the driven
level: 20 % of VDD (0.66 V) when the cell is driving low, 80 % (2.64 V) when
it is driving high.  While enabled, the cell pushes a large current `I_on`
through that source (0.56 mA and 0.60 mA respectively for `ebufn_4`).  When
`TE_B` disables the cell, that current collapses.  The disable delay is

> the time from `TE_B`'s 50 % crossing to the **last** time `|I_Z|` falls
> through `I_on / 2`

i.e. the same 50 % convention every other propagation number in this library
uses, applied to the quantity that actually goes away.  `fall = last` matters:
the crowbar current during the `TE_B` traversal can cross the level more than
once.

This is load-independent by construction, which reproduces the reference
library's load-independence for the right reason rather than by copying a
synthetic epsilon.  The seven rows of each disable table are therefore
identical, and no epsilon is added -- `verify_lib.py` check 4 accepts a
constant series.

Both polarities ride in one deck sharing the `TE_B` source; the waveforms are
written out with `wrdata` and the crossings interpolated in Python, which also
yields the 10 % criterion for the log (`data/dis_*.txt`, `measured.json` ->
`cells.*.disable.raw`) at no extra simulation cost.  A `B`-source computing
`abs(i(vhr))` inside the deck was tried first and makes ngspice hang, hence
the waveform dump.

`rise_transition` / `fall_transition` repeat the delay table.  After the
driver lets go the output does not traverse a slew at all, so there is no
transition to measure; the thin-oxide library does exactly the same (its
disable `cell_rise` and `rise_transition` tables are identical, value for
value).

**Consequence for the sanity gate.**  Because the criterion differs from
whatever the thin-oxide library used, the HV/LV ratio for the disable arc is
*not* expected to land near 2.66 and does not.  It is reported honestly in the
ratio table rather than tuned.  The combinational and enable arcs, which use
the standard voltage-threshold definitions, are the ones the 2.2-3.2 band
applies to.

### 4. Leakage

Settled-tail average of `i(Vdd)` over a quiet 40-60 ns window of a 60 ns
transient -- `work/tie_leakage.py`'s deck style.  One measurement per `when`
condition of the thin-oxide counterpart, mirrored exactly:

* `ebufn_*`: four states, `A&TE_B`, `!A&TE_B`, `A&!TE_B`, `!A&!TE_B`
* `einvn_4`, `einvn_8`: two states, `!A&!TE_B`, `A&!TE_B`
* `einvn_2`: two states, but its thin-oxide counterpart spells the output node
  out in a third term, so the `when` strings are `!A&!TE_B&Z` and `A&!TE_B&!Z`
  (same two input states, same measurement)

`cell_leakage_power` is the arithmetic mean of the state values, which is what
the thin-oxide library does (`ebufn_4`: (244.761 + 180.477 + 481.934 +
598.545)/4 = 376.429).

In the two `TE_B = 1` states of the ebufn cells the output has no DC path of
its own, so it is tied to mid-rail through 1 Gohm -- `work/verify_logic.py`'s
convention for making a floating tri-state node well defined.  In that state
the keeper carries exactly the cell's own net leakage into Z, which is part of
what is being measured.  The settled output voltage is recorded in
`measured.json` (`leakage[].v_out`) as evidence the node really was at
mid-rail.

**The keeper is deliberately absent in the driven states, and that is not a
detail.**  The first version of this measurement left it attached
unconditionally, and `sg13g2_hv_ebufn_2` came back with `A&!TE_B` at 5.48 nW
against 0.03-0.04 nW for its other three states.  That 150x outlier was the
keeper: a cell driving Z high pushes (3.3 - 1.65)/1 Gohm = 1.65 nA out through
it and back to ground, and that current flows through `Vdd`, so it lands in
`i(Vdd)` as 5.4 nW of fictitious leakage.  The same resistor is negligible in
the thin-oxide library, where real leakage is hundreds of nW; at thick-oxide
leakage levels a 1 Gohm resistor is a significant load.  With the keeper
attached only where the node actually floats, the four states come back at
0.043 / 0.030 / 0.035 / 0.037 nW.

HV leakage is ~1e4 below the thin-oxide equivalent (thick oxide, 0.45 um
channels), so these numbers are tens of pW to a few nW against the thin-oxide
library's hundreds of nW.  That is correct for this library and consistent
with its tie cells.

### 5. Pin capacitance

Charge integration: a VSS -> VDD -> VSS ramp on the target pin, `C = |Q| / VDD`
computed separately for each edge, `t_slew` = the fastest grid slew.  This is a
reimplementation of CharLib's `charge_integration` procedure -- the one that
produced every other input capacitance in this library, selected in the config
precisely because the default `ac_sweep` Miller-multiplies Cgd.

CharLib's defaults are used unchanged -- `t_wait` = 1000 x `t_slew`, every
non-target pin isolated with 10 Gohm + 1 pF to ground -- and `ties` is used
only for pin Z, which has to be measured with the cell disabled.

**Calibration.**  The harness is required to reproduce a number already in the
shipped library before its results are trusted; `char_tristate.py` aborts the
run if it does not (5 % tolerance).  `sg13g2_hv_buf_4` pin A: rise 0.009208 pF,
fall 0.008236 pF, against the shipped 0.009166 / 0.008236 -- 0.5 % apart on the
worse of the two.  The calibration deck is launched into the job pool rather
than ahead of the cells: buf_4's deck happens to be by far the most expensive
one here (a few hundred ngspice CPU-seconds against single digits for the
tri-state decks) and running it first put one slow simulation in front of the
other ~180.

## A note on run time, in case this is ever re-run

This machine was shared with a second characterization job for the whole of
this work, and its run queue sat between 30 and 95 against 8 cores.  That
produced one genuinely misleading effect worth recording:

**ngspice must be pinned to one OpenMP thread here.**  It defaults to four
(`set num_threads=4` in `~/.spiceinit`), and its OpenMP barriers *spin* rather
than sleep.  On an oversubscribed machine the worker threads burn their entire
scheduled slice spinning at barriers instead of solving, so the process
accumulates CPU time without making progress.  Measured directly on identical
decks: 130+ CPU-seconds accumulated *without finishing* at four threads,
against roughly 4 CPU-seconds *to completion* at one.  `char_tristate.py` sets
`OMP_NUM_THREADS=1` and `OMP_WAIT_POLICY=PASSIVE` for exactly this reason and
takes its parallelism at the job level instead (`CT_JOBS`, default 4).

Two apparent optimisations were chased and abandoned before that was
understood -- shortening `t_wait` to 100 x `t_slew`, and tying non-target
inputs instead of isolating them.  Both looked like enormous wins or losses
depending purely on when they happened to be launched.  Neither is in the
final script.  If you are timing anything on this machine, pin the threads
first and only then compare.

The second thing that mattered was **scheduling**: all ~165 simulations are
submitted to the pool up front.  Submitting them phase by phase per cell
(leakage, then capacitance, then the seven combinational slews, then enable,
then disable) capped useful concurrency at seven regardless of `CT_JOBS`, and
every phase boundary drained the pool down to a single straggler.  Submitting
everything at once keeps `CT_JOBS` simulations in flight from start to finish.

`pin (Z)` carries a capacitance too, matching the thin-oxide cells.  It is the
load a *disabled* tri-state cell presents to whoever else is driving the net,
so it is measured with `TE_B` tied inactive; both `A` states are measured and
the worse taken, the same way CharLib takes the worse of rise and fall.

## Emitted structure

Per cell: `area`, `cell_footprint`, `cell_leakage_power`, the `leakage_power`
groups, `pin (Z)`, `pin (A)`, `pin (TE_B)`, `pg_pin (VDD)`, `pg_pin (VSS)`.

`area` is the drawn cell boundary from `lef/sg13g2_stdcell_hv.lef`
(`SIZE` width x 7.14 um row height); the values agree exactly with the GDS
boundary areas `work/verify_lib.py` check 3 compares against.

Deviations from the thin-oxide cell groups, all of them to match the *shipped
HV* library rather than the thin-oxide one:

* **HV syntax**, not thin-oxide syntax: unquoted attribute values with a space
  before the semicolon (`direction : output ;`), groups closed with
  `} /* end pin */` etc.  This is not cosmetic -- `work/verify_lib.py` check 7
  greps for the literal string `direction : output`, which the thin-oxide
  quoted form would not match.
* **no `internal_power`** and **no `min_capacitance`**: the shipped HV library
  contains zero of either, for any cell.  Emitting them would have required a
  new `passive_power_template_7x1` template in the header, since no HV cell has
  a 1-D passive power table to reuse.
* **`max_transition` added to `pin (Z)`**: the thin-oxide cells do not carry
  it, but `work/verify_lib.py` check 7 requires both `max_capacitance` and
  `max_transition` on every output pin with timing tables, and every shipped HV
  output pin has both.
* **`pg_pin` groups added**: every shipped HV cell has them; the thin-oxide
  tri-state cells do not.
* **no capacitance `_range` lines**: only a single value is measured per edge,
  so there is no range to report.
* **no `dont_use` / `dont_touch`**: these cells are meant to be usable.

## Reproducing

```
cd /foss/designs/sg13g2_stdcell_hv/work/char_tristate
./char_tristate.py            # ~220 ngspice runs, about 15 min on 8 threads
./char_tristate.py --reuse    # re-emit tristate.lib from measured.json
./verify_fragment.py          # sanity gate + HV/LV ratio table
```

Artifacts: `measured.json` (every raw number), `decks/` (every deck),
`logs/` (every ngspice output), `data/` (disable-arc waveform dumps),
`ref/` (the thin-oxide cell groups this was mirrored from).

## Results

`RESULTS.md` carries the per-cell PASS/FAIL, the HV/LV ratio table and the
list of caveats.  Headline: all six cells PASS the sanity gate (60 tables, 0
malformed, 210 load-axis series with 0 monotonicity violations, harness
calibration 0.46 % against the shipped `sg13g2_hv_buf_4` value); combinational
and enable ratios sit in or beside the 2.2-3.2 band; the disable ratios
(1.46-1.53) are out of band for the documented reason that the arc is measured
with a different criterion from the reference library's.

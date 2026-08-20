# Notes on the iic-osic-tools container: ngspice threading and Qucs-S setup

Findings from characterizing `sg13g2_stdcell_hv` across three PVT corners in
the iic-osic-tools container. Both items below cost real time, and both are
environment issues rather than PDK or library bugs, so they are recorded
separately from the library documentation.

Container as measured: 8 cores, ngspice-46 (KLU, linked against `libgomp`),
Qucs-S under `/foss/tools/qucs-s`, PDK at `/foss/pdks/ihp-sg13g2`.

---

## 1. ngspice threading: the environment variable does nothing

### What is shipped

The image ships `~/.spiceinit` (root-owned, dated 7 Apr):

```
set num_threads=4
set ngbehavior=hsa
set ng_nomodcheck
set enable_noisy_r
```

So **every ngspice invocation that does not find a local `.spiceinit` runs
four OpenMP threads**, silently. ngspice's own default, with no `.spiceinit`
anywhere, is one thread per core.

### `OMP_NUM_THREADS` is ignored

This is the part worth knowing. ngspice reads its own `num_threads` variable
and calls `omp_set_num_threads()` itself, which **overrides** the environment.
Setting `OMP_NUM_THREADS` — the obvious thing to reach for, and what most
job-parallel harnesses do — has no effect at all.

Measured on a six-inverter chain of `sg13g2_hv_inv_8` with a 4 µs transient,
sampling `/proc/<pid>/task`:

| `.spiceinit`            | environment          | threads | CPU % |
|-------------------------|----------------------|--------:|------:|
| `set num_threads=1`     | —                    |       1 |  99.9 |
| `set num_threads=4`     | —                    |       4 |   397 |
| absent                  | —                    |       8 |   738 |
| `set num_threads=1`     | `OMP_NUM_THREADS=1`  |       1 |  99.9 |
| absent                  | `OMP_NUM_THREADS=1`  |   **8** |   738 |

Only the `.spiceinit` variable controls it.

### Why it matters

A characterization run is job-parallel: J ngspice processes at once. With the
shipped default each takes 4 threads, so J=8 on an 8-core machine asks for 32
runnable threads. ngspice's OpenMP barriers spin rather than sleep, so the
workers burn CPU contending instead of finishing.

The failure is not a clean slowdown. Decks that complete in seconds run into
a per-deck timeout, and **a timed-out trial inside a bisection reads as
"failed"** — so the search never brackets and returns its own search bound as
though it were a measurement. In this project that produced a clock-gate
`min_pulse_width` of 48.3 ns against a true value near 1 ns: a plausible
number, 30–50× wrong, with nothing in the log to indicate it. 17 of 98 delay
grid points and 7 of 16 bisections were destroyed this way before the run was
re-done with fewer concurrent jobs.

### Two traps around `.spiceinit` itself

* **A local `.spiceinit` replaces `~/.spiceinit`; it does not merge with it.**
  Writing a one-line local file to pin threads therefore also drops
  `ngbehavior=hsa` and `ng_nomodcheck`, and — unless the PDK's `osdi` lines
  are copied into it — the PSP103 OSDI modules never load, so every SG13G2
  MOSFET fails to bind. A local `.spiceinit` has to restate everything it
  displaces.
* **Server mode does not read `.spiceinit` at all.** `ngspice -s`, which is
  how PySpice and therefore CharLib drive the simulator, ignores the file
  entirely, so both the thread count and the OSDI loads have to be injected
  into the deck as `pre_set num_threads=…` and `pre_osdi …` inside a
  `.control` block placed after the title line.

### Suggested change

Ship `num_threads=1` in the image's `~/.spiceinit`, or drop the line and let
ngspice's own default apply. A shared container in which several users each
run job-parallel flows is the worst place for a default of 4: the
oversubscription is multiplicative and invisible. If the default stays, it
deserves a prominent note, because `OMP_NUM_THREADS` looks like it should fix
it and does not.

### One observation that did not reproduce

During the live characterization runs, `ngspice` processes started with
`cwd` set to a directory containing a `.spiceinit` with `num_threads=1` were
measured at 8 threads and ~385 % CPU. Re-running the same decks from the same
directory afterwards, through the same wrapper and environment, gives 1
thread and 100 % every time. The original reading was not noise — 385 % CPU
is real parallelism — but it is unexplained and is recorded here only so it
is not lost. **The reproducible behaviour is the table above**, and the
mitigation (size job count against actual threads) does not depend on the
explanation.

---

## 2. Qucs-S: not on `PATH`, and the standard-cell symbol library is broken

### `qucs-s` is not on `PATH`

The binary is at `/foss/tools/qucs-s/bin/qucs-s`, but that directory is not on
`PATH`, unlike the other `/foss/tools` entries. `which qucs-s` fails.

### The thin-oxide symbol library is a dangling symlink

```
$ ls -l /foss/pdks/ihp-sg13g2/libs.tech/qucs-s/
symbols_stdcell -> /home/rahman/temp/IHP-Open-PDK/ihp-sg13g2/libs.ref/sg13g2_stdcell/sym/qucs-s
```

That target does not exist in the image. It is an absolute path on the
machine of whoever built it, captured at image build time.

**This was upstream content, and upstream has already fixed it.** The
absolute link was committed to `IHP-GmbH/IHP-Open-PDK` and corrected by
PR #1097, "HOTFIX: absolute symbolic link for qucs-s stdcell symbols: make it
relative", merged to the `dev` branch on 2026-08-11. `dev` now carries

```
symbols_stdcell -> ../../libs.ref/sg13g2_stdcell/sym/qucs-s
```

which is relative and survives relocation. (`main` has no Qucs-S standard-cell
views at all; that work lives on `dev`.)

The `rahman` in the path is the upstream author of the original commit, not an
image builder: `install.py` composes absolute paths from `$PDK_ROOT` and
`$HOME`, so a link created on a developer's machine records that machine's
layout.

**So this is a stale-snapshot problem, not a defect to report.** The PDK tree
in this image is dated 27 Jul 2026, roughly two weeks before the fix landed,
so it still carries the pre-#1097 absolute link. Any image built from a PDK
checkout after 11 Aug 2026 will not have it.

The consequence is that none of the 84 thin-oxide standard cells are
available as Qucs-S schematic components out of the box, even though the PDK
ships all their component definitions and gate shapes.

The real fix is to refresh the bundled PDK. Failing that, repair the link in
place (below), or run the installer with the environment set for this
machine:

```sh
PDK_ROOT=/foss/pdks python3 /foss/pdks/ihp-sg13g2/libs.tech/qucs-s/install.py
```

which populates the user's Qucs workspace (`$HOME/.qucs/user_lib`). To repair
the in-tree link directly, make it relative so it survives relocation:

```sh
ln -sfn ../../libs.ref/sg13g2_stdcell/sym/qucs-s \
        /foss/pdks/ihp-sg13g2/libs.tech/qucs-s/symbols_stdcell
```

### Thick-oxide needs the same link

`sg13g2_stdcell_hv` now ships `sym/qucs-s` (84 component XML plus the 45
shared `.sym` gate shapes) and `sch/qucs-s` (84 schematics), mirroring the
thin-oxide layout. It needs the analogous link:

```sh
ln -sfn "$PDK_ROOT/$PDK/libs.ref/sg13g2_stdcell_hv/sym/qucs-s" \
        "$PDK_ROOT/$PDK/libs.tech/qucs-s/symbols_stdcell_hv"
```

Since the component XML references its geometry as
`{QUCS_S_COMPONENTS_LIBRARY}/<SHAPE>.sym`, each library directory must carry
its own copy of the shared shapes, which is why the thick-oxide library
duplicates the 45 files rather than pointing at the thin-oxide ones.

There is no generic mechanism that picks up per-library Qucs-S symbol
directories; each one needs an explicit link. A loop in `install.py` over
`libs.ref/*/sym/qucs-s` would make this self-maintaining as libraries are
added.

### Not verified here

Whether these schematics open and netlist correctly in the Qucs-S GUI has
**not** been confirmed, because the binary is off `PATH` and the component
library symlink is broken in this image. They are structurally correct and
gated against the shipped SPICE netlist (`work/verify_qucs.py`: geometry
untouched relative to the thin-oxide originals, all 920 device sizes matching
the netlist, and the two hand-composed tie cells matching terminal by
terminal), but that is a different claim from "opens in the tool".

### Not a problem for PR #1103

An earlier version of this note claimed our PR branch carried a stray
`symbols_stdcell`. That was an artifact of comparing against `main`. PR #1103
targets `dev`, `dev` already contains the symlink from #1097, and our branch
carries the identical relative target — so it does not appear in the PR diff
and there is nothing to remove.

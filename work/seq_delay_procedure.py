"""Clock-to-Q delay procedure for CharLib.

CharLib 2.1.0 ships `sequential_worst_case` as a stub: it registers, yields
tasks, and returns the cell's liberty skeleton unchanged (`# TODO`), so a
sequential cell characterised with stock CharLib gets setup/hold constraint
tables but NO propagation arcs -- and a Liberty file without clk->Q delays
cannot drive synthesis. This module provides the missing procedure through
CharLib's own extension point: it @registers under the name
`sequential_clk_to_q`, and the library configuration selects it with

    settings:
      simulation:
        sequential_delay_procedure: sequential_clk_to_q

Method, per (slew, load) grid point and per output transition:

  * Solve the output's state function for an input assignment that produces
    the target state, and one that produces the opposite (preload) state,
    with the async set/reset pins held inactive in both. Assignments come
    from the function's own truth table, so scan muxes and reset terms are
    honoured without any cell-specific code.
  * Drive the clock (or latch enable) with two pulses: the first loads the
    preload state, then the data inputs switch to the target assignment
    mid-period, and the second -- the measured edge, with the grid slew --
    launches the target state.
  * Measure propagation from the measured edge's 50 % crossing to the
    output's 50 % crossing, and the output's 20-80 % transition, exactly as
    the combinational procedure defines them.

The emitted timing groups use `timing_type: rising_edge` / `falling_edge`
(per the clock/enable polarity) with `related_pin` set to the clock or
enable pin, which is the NLDM form synthesis tools expect for registers.
"""
import PySpice

from charlib.characterizer import utils
from charlib.characterizer.procedures import register, ProcedureFailedException
from charlib.characterizer.logic.evaluators import BooleanEvaluator, OPERAND_REGEX
from charlib.liberty import liberty
from charlib.liberty.library import LookupTable


def _assignments(expr, operands, inactive):
    """Yield {pin: '0'/'1'} maps over `operands` consistent with `inactive`."""
    free = [p for p in operands if p not in inactive]
    for n in range(2 ** len(free)):
        bits = {p: str((n >> i) & 1) for i, p in enumerate(free)}
        bits.update(inactive)
        yield bits


def _solve(expr, operands, inactive, target):
    """Find an input assignment for which `expr` evaluates to `target`.

    Only the expression's own operands are passed to the evaluator; the
    role-tied set/reset pins in `inactive` ride along in the returned map
    for waveform generation but are not expression inputs."""
    ev = BooleanEvaluator(expr)
    for bits in _assignments(expr, operands, inactive):
        args = {k: bool(int(v)) for k, v in bits.items() if k in operands}
        if bool(ev(**args)) == bool(target):
            return bits
    return None


@register('clock_slews', 'loads')
def sequential_clk_to_q(cell, config, settings):
    """Measure clock/enable-to-output propagation and transition delays."""
    for variation in config.variations('clock_slews', 'loads'):
        for out_pin in cell.outputs:
            for out_transition in ('01', '10'):
                yield (measure_c2q, cell, config, settings, variation,
                       out_pin, out_transition)


def measure_c2q(cell, config, settings, variation, out_pin, out_transition):
    data_slew = variation['clock_slews'] * settings.units.time
    load = variation['loads'] * settings.units.capacitance
    vdd = settings.primary_power.voltage * settings.units.voltage
    vss = settings.primary_ground.voltage * settings.units.voltage
    th_low = settings.logic_thresholds.low
    th_high = settings.logic_thresholds.high

    # the trigger pin: clock for flops, enable for latches
    trigger = next((p for p in cell.pins.values()
                    if p.role in ('clock', 'enable')), None)
    if trigger is None:
        raise ProcedureFailedException(
            f'{cell.name}: no clock or enable pin for sequential delay')

    fn = cell.functions[out_pin]
    if fn.state is None:
        return cell.liberty          # combinational output of a mixed cell
    state_expr = fn.expression       # already read through to the state fn
    operands = sorted(set(OPERAND_REGEX.findall(state_expr)))

    # async set/reset held inactive throughout ('not X' -> inactive at VDD).
    # These pins carry roles, not operands -- the state expression is the
    # pure data function -- so they are tied by role, unconditionally.
    inactive = {p.name: ('1' if p.is_inverted() else '0')
                for p in cell.pins.values()
                if p.role in ('set', 'reset')}

    target = 1 if out_transition == '01' else 0
    bits_t = _solve(state_expr, operands, inactive, target)
    bits_p = _solve(state_expr, operands, inactive, 1 - target)
    if bits_t is None or bits_p is None:
        return cell.liberty          # transition unreachable (e.g. tie cell)

    # ---- waveforms ---------------------------------------------------------
    # timeline: settle, preload pulse, data switch, measured edge
    t_pre = float(4 * data_slew.convert(settings.units.time.prefixed_unit).value) + 2.0
    t_switch = t_pre + 6.0
    t_edge = t_switch + 6.0
    t_end = t_edge + 40.0
    ns = PySpice.Unit.u_ns

    (v_idle, v_active) = (vss, vdd) if not trigger.is_inverted() else (vdd, vss)
    full = float(data_slew.convert(settings.units.time.prefixed_unit).value) / (th_high - th_low)
    clk_pwl = [(0 @ ns, v_idle)]

    def edge(t0, v0, v1, tr):
        return [(t0 @ ns, v0), ((t0 + tr) @ ns, v1)]

    # preload pulse with a fast fixed edge (0.1 ns full swing)
    clk_pwl += edge(t_pre, v_idle, v_active, 0.1)
    clk_pwl += edge(t_pre + 2.0, v_active, v_idle, 0.1)
    # measured edge with the grid slew
    clk_pwl += edge(t_edge, v_idle, v_active, full)
    clk_pwl += [((t_end + 5) @ ns, v_active)]

    circuit = utils.init_circuit(f'c2q_{cell.name}_{out_pin}_{out_transition}',
                                 cell.netlist, config.models,
                                 settings.named_nodes, settings.units)
    circuit.PieceWiseLinearVoltageSource('clk', 'vclk', circuit.gnd,
                                         values=clk_pwl)
    circuit.C('load', 'vout', circuit.gnd, load)

    # role-tied set/reset pins: driven at their inactive level for the
    # whole simulation. These are NOT operands of the state expression, so
    # they must be driven here explicitly -- leaving them out wires the DUT
    # pin to an undriven node, rshunt drifts it to ground, and an
    # active-low reset then holds the flop cleared forever (Q never
    # transitions and every measurement comes back 'out of interval').
    for pin_name, lvl_bit in inactive.items():
        lvl = vdd if lvl_bit == '1' else vss
        circuit.V(pin_name, f'v{pin_name}', circuit.gnd, lvl)

    # data pins: preload value until t_switch, then target value
    for pin_name in operands:
        if pin_name in inactive:
            continue
        v0 = vdd if bits_p[pin_name] == '1' else vss
        v1 = vdd if bits_t[pin_name] == '1' else vss
        if float(v0) == float(v1):
            circuit.V(pin_name, f'v{pin_name}', circuit.gnd, v0)
        else:
            circuit.PieceWiseLinearVoltageSource(
                pin_name, f'v{pin_name}', circuit.gnd,
                values=[(0 @ ns, v0), (t_switch @ ns, v0),
                        ((t_switch + 0.1) @ ns, v1), ((t_end + 5) @ ns, v1)])

    connections = []
    for pin in cell.pins_in_netlist_order():
        if pin.name == trigger.name:
            connections.append('vclk')
        elif pin.name == out_pin:
            connections.append('vout')
        elif pin.role == 'primary_power':
            connections.append('vdd')
        elif pin.role == 'primary_ground':
            connections.append('vss')
        elif pin.name in operands or pin.name in inactive:
            connections.append(f'v{pin.name}')
        else:
            connections.append('wfloat0')
    circuit.X('dut', cell.name, *connections)

    simulator = PySpice.Simulator.factory(simulator=settings.simulation.backend)
    simulation = simulator.simulation(circuit,
                                      temperature=settings.temperature,
                                      nominal_temperature=settings.temperature)
    simulation.options('nopage', 'nomod', rshunt=1e9, trtol=1)

    clk_dir = 'rise' if not trigger.is_inverted() else 'fall'
    out_dir = 'rise' if out_transition == '01' else 'fall'
    half = float(vdd) / 2
    (tr0, tr1) = ((th_low, th_high) if out_dir == 'rise'
                  else (th_high, th_low))
    prop = f'cell_{out_dir}'
    tran = f'{out_dir}_transition'
    simulation.measure('tran', prop,
                       f'trig v(vclk) val={half} {clk_dir}=2'
                       if not trigger.is_inverted() else
                       f'trig v(vclk) val={half} {clk_dir}=1',
                       f'targ v(vout) val={half} {out_dir}=1 td={t_switch}n',
                       run=False)
    simulation.measure('tran', tran,
                       f'trig v(vout) val={float(vdd) * tr0} {out_dir}=1 '
                       f'td={t_switch}n',
                       f'targ v(vout) val={float(vdd) * tr1} {out_dir}=1 '
                       f'td={t_switch}n',
                       run=False)
    simulation.transient(step_time=(min(full, 0.2) / 8) @ ns,
                         end_time=t_end @ ns, run=False)

    if settings.debug:
        debug_path = settings.debug_dir / cell.name / 'c2q'
        debug_path.mkdir(parents=True, exist_ok=True)
        with open(debug_path / f'{out_pin}_{out_transition}_s{data_slew}'
                               f'_l{load}.sp', 'w') as f:
            f.write(str(simulation))

    try:
        analysis = simulator.run(simulation)
    except Exception as e:
        raise ProcedureFailedException(
            f'c2q failed for {cell.name} {out_pin} {out_transition} '
            f'at {variation}') from e

    result = cell.liberty
    timing_group = liberty.Group('timing')
    timing_group.add_attribute('related_pin', trigger.name)
    timing_group.add_attribute(
        'timing_type',
        'rising_edge' if not trigger.is_inverted() else 'falling_edge')
    n_loads = len(config.parameters['loads'])
    n_slews = len(config.parameters['clock_slews'])
    for name in (prop, tran):
        if name not in analysis.measurements:
            raise ProcedureFailedException(
                f'c2q measurement {name} missing for {cell.name} {out_pin} '
                f'{out_transition} at {variation}')
        value = (analysis.measurements[name] @ PySpice.Unit.u_s)
        lut = LookupTable(
            name, f'delay_template_{n_loads}x{n_slews}',
            total_output_net_capacitance=[
                load.convert(settings.units.capacitance.prefixed_unit).value],
            input_net_transition=[
                data_slew.convert(settings.units.time.prefixed_unit).value])
        lut.values[0, 0] = value.convert(
            settings.units.time.prefixed_unit).value
        timing_group.add_group(lut)
    result.group('pin', out_pin).add_group(timing_group)
    return result


# ---------------------------------------------------------------------------
# Setup/hold by bisection on the same two-pulse harness.
#
# CharLib 2.1.0's default contour procedure builds transients whose point
# count explodes on these cells (observed 1.2 GB allocation requests); the
# failed allocation drives libngspice into its fatal "cannot recover" state
# and poisons the worker process. This procedure replaces it with a bounded
# search: ~2 x log2(range/tolerance) simulations per constraint, each the
# same well-behaved circuit the clk->Q measurement uses.
#
#   setup: preload the opposite state, switch the data inputs at
#          t_edge - t_su, clock the measured edge; PASS if the output
#          reaches its target half-rail crossing. Bisect t_su.
#   hold:  data inputs at target from long before the edge, revert to the
#          preload value at t_edge + t_h; PASS if the output still reaches
#          and keeps the target. Bisect t_h.
#
# Tables are indexed (data slew, clock slew), the CONSTRAINT template
# convention of the thin-oxide library.
# ---------------------------------------------------------------------------

def _c2q_passes(cell, config, settings, out_pin, out_transition,
                data_slew, clock_slew, t_su, t_h):
    """One pass/fail trial: does the output reach its target state?"""
    vdd = settings.primary_power.voltage * settings.units.voltage
    vss = settings.primary_ground.voltage * settings.units.voltage
    th_low = settings.logic_thresholds.low
    th_high = settings.logic_thresholds.high

    trigger = next(p for p in cell.pins.values()
                   if p.role in ('clock', 'enable'))
    fn = cell.functions[out_pin]
    state_expr = fn.expression
    operands = sorted(set(OPERAND_REGEX.findall(state_expr)))
    inactive = {p.name: ('1' if p.is_inverted() else '0')
                for p in cell.pins.values() if p.role in ('set', 'reset')}
    target = 1 if out_transition == '01' else 0
    bits_t = _solve(state_expr, operands, inactive, target)
    bits_p = _solve(state_expr, operands, inactive, 1 - target)
    if bits_t is None or bits_p is None:
        return None

    ns = PySpice.Unit.u_ns
    d_full = float(data_slew) / (th_high - th_low)
    c_full = float(clock_slew) / (th_high - th_low)
    is_latch = trigger.role == 'enable'
    t_pre = 4.0 * float(data_slew) + 2.0
    t_edge = t_pre + 8.0 + max(0.0, -t_su) + d_full
    # slew_pwl-style ramps below are centred on these instants: the ramp
    # spans [t - d_full/2, t + d_full/2], so its 50% crossing IS t. The
    # first version subtracted another d_full/2 here, silently granting
    # every trial that much extra setup -- enough to push the entire
    # bisection range onto the passing side for slow data slews, which is
    # exactly what pinned those rows at the search floor.
    #
    # Flops constrain against the capturing (asserting) edge. Latches are
    # transparent while enabled, so their constraints reference the CLOSING
    # edge instead -- the first latch version left the enable asserted,
    # the latch stayed transparent, Q followed the hold-revert back to the
    # preload value, and every trial failed even at maximum margins.
    if is_latch:
        t_close = t_edge + 6.0 + d_full + max(0.0, -t_su)
        t_ref = t_close
    else:
        t_ref = t_edge
    t_sw = t_ref - t_su                        # data 50% at t_ref - t_su
    t_rev = t_ref + t_h                        # revert 50% at t_ref + t_h
    t_end = t_ref + 25.0

    (v_idle, v_active) = (vss, vdd) if not trigger.is_inverted() else (vdd, vss)
    clk_pwl = [(0 @ ns, v_idle)]
    clk_pwl += [(t_pre @ ns, v_idle), ((t_pre + 0.1) @ ns, v_active)]
    clk_pwl += [((t_pre + 2.0) @ ns, v_active), ((t_pre + 2.1) @ ns, v_idle)]
    if is_latch:
        # open with a fast edge, close with the measured slew
        clk_pwl += [((t_edge - 0.05) @ ns, v_idle),
                    ((t_edge + 0.05) @ ns, v_active),
                    ((t_close - c_full / 2) @ ns, v_active),
                    ((t_close + c_full / 2) @ ns, v_idle),
                    ((t_end + 5) @ ns, v_idle)]
    else:
        clk_pwl += [((t_edge - c_full / 2) @ ns, v_idle),
                    ((t_edge + c_full / 2) @ ns, v_active),
                    ((t_end + 5) @ ns, v_active)]

    circuit = utils.init_circuit(f'su_{cell.name}_{out_pin}', cell.netlist,
                                 config.models, settings.named_nodes,
                                 settings.units)
    circuit.PieceWiseLinearVoltageSource('clk', 'vclk', circuit.gnd,
                                         values=clk_pwl)
    load = config.parameters.get('metastability_constraint_load', 0.05)
    circuit.C('load', 'vout', circuit.gnd,
              load * settings.units.capacitance)

    for pin_name, lvl_bit in inactive.items():
        lvl = vdd if lvl_bit == '1' else vss
        circuit.V(pin_name, f'v{pin_name}', circuit.gnd, lvl)
    for pin_name in operands:
        if pin_name in inactive:
            continue
        v0 = vdd if bits_p[pin_name] == '1' else vss
        v1 = vdd if bits_t[pin_name] == '1' else vss
        if float(v0) == float(v1):
            circuit.V(pin_name, f'v{pin_name}', circuit.gnd, v0)
            continue
        pts = [(0 @ ns, v0),
               ((t_sw - d_full / 2) @ ns, v0),
               ((t_sw + d_full / 2) @ ns, v1)]
        # hold trial: revert after the edge
        pts += [((t_rev - d_full / 2) @ ns, v1),
                ((t_rev + d_full / 2) @ ns, v0),
                ((t_end + 5) @ ns, v0)]
        circuit.PieceWiseLinearVoltageSource(pin_name, f'v{pin_name}',
                                             circuit.gnd, values=pts)

    connections = []
    for pin in cell.pins_in_netlist_order():
        if pin.name == trigger.name:
            connections.append('vclk')
        elif pin.name == out_pin:
            connections.append('vout')
        elif pin.role == 'primary_power':
            connections.append('vdd')
        elif pin.role == 'primary_ground':
            connections.append('vss')
        elif pin.name in operands or pin.name in inactive:
            connections.append(f'v{pin.name}')
        else:
            connections.append('wfloat0')
    circuit.X('dut', cell.name, *connections)

    simulator = PySpice.Simulator.factory(
        simulator=settings.simulation.backend)
    simulation = simulator.simulation(circuit,
                                      temperature=settings.temperature,
                                      nominal_temperature=settings.temperature)
    simulation.options('nopage', 'nomod', rshunt=1e9, trtol=1)
    step = max(min(d_full, c_full, 0.2) / 8, 0.002)
    simulation.transient(step_time=step @ ns, end_time=t_end @ ns, run=False)
    if settings.debug:
        dbg = settings.debug_dir / cell.name / 'suh'
        dbg.mkdir(parents=True, exist_ok=True)
        with open(dbg / f'{out_pin}_{out_transition}_su{t_su}_h{t_h}.sp',
                  'w') as f:
            f.write(str(simulation))
    try:
        analysis = simulator.run(simulation)
    except Exception:
        return (False, None)                  # non-convergence = fail side
    import numpy as np
    vout = np.array(analysis['vout'])
    time = np.array(analysis.time) * 1e9
    tail = vout[time > (t_ref + 20.0)]
    if tail.size == 0:
        return (False, None)
    v_final = float(tail[-1])
    half = float(vdd) / 2
    ok = (v_final > half) == (target == 1)
    # first half-rail crossing toward the target after the measured edge
    after = time > (t_edge if not is_latch else t_sw)
    sgn = (vout > half) if target == 1 else (vout < half)
    idx = np.where(after & sgn)[0]
    ref0 = t_edge if not is_latch else t_sw
    t_cross = float(time[idx[0]] - ref0) if idx.size else None
    return (ok, t_cross)


@register('data_slews', 'clock_slews', 'metastability_constraint_load')
def setup_hold_bisection(cell, config, settings):
    """Find setup and hold times by pass/fail bisection."""
    for variation in config.variations('data_slews', 'clock_slews'):
        for out_pin in cell.outputs:
            if cell.functions[out_pin].state is None:
                continue
            for out_transition in ('01', '10'):
                yield (measure_setup_hold, cell, config, settings, variation,
                       out_pin, out_transition)


def measure_setup_hold(cell, config, settings, variation, out_pin,
                       out_transition):
    data_slew = variation['data_slews']
    clock_slew = variation['clock_slews']
    TOL = 0.01                                 # ns
    SU_MAX, SU_MIN = 8.0, -2.0
    H_MAX = 8.0

    def trial(t_su, t_h):
        return _c2q_passes(cell, config, settings, out_pin, out_transition,
                           data_slew, clock_slew, t_su, t_h)

    first = trial(SU_MAX, H_MAX)
    if first is None:
        return cell.liberty                    # transition unreachable
    ok0, t_nom = first
    if not ok0 or t_nom is None:
        raise ProcedureFailedException(
            f'{cell.name} {out_pin} {out_transition}: fails even at maximum '
            f'setup/hold -- harness or cell problem')

    # Degradation criterion: a trial passes only if the output reaches the
    # target state AND its clk->q has not degraded past 1.5x the nominal
    # measured at generous margins. Final-state-only acceptance rides
    # through luckily-resolved metastability and reports absurdly negative
    # constraints (values pinned at the search floor).
    def passes(t_su, t_h):
        r = trial(t_su, t_h)
        if r is None:
            return False
        ok, t_c = r
        return bool(ok and t_c is not None and t_c <= 1.5 * t_nom)

    # setup: bisect with generous hold
    lo, hi = SU_MIN, SU_MAX
    while hi - lo > TOL:
        mid = (lo + hi) / 2
        if passes(mid, H_MAX):
            hi = mid
        else:
            lo = mid
    t_setup = hi

    # hold: bisect with generous setup
    lo, hi = -2.0, H_MAX
    while hi - lo > TOL:
        mid = (lo + hi) / 2
        if passes(SU_MAX, mid):
            hi = mid
        else:
            lo = mid
    t_hold = hi

    result = cell.liberty
    trigger = next(p for p in cell.pins.values()
                   if p.role in ('clock', 'enable'))
    if trigger.role == 'enable':
        # latch: constraints reference the closing (de-asserting) edge
        edge = 'falling' if not trigger.is_inverted() else 'rising'
    else:
        edge = 'rising' if not trigger.is_inverted() else 'falling'
    n_ds = len(config.parameters['data_slews'])
    n_cs = len(config.parameters['clock_slews'])
    data_pins = [p for p in sorted(set(
        OPERAND_REGEX.findall(cell.functions[out_pin].expression)))
        if p in cell.pins]
    for pin_name in data_pins:
        for kind, value in (('setup', t_setup), ('hold', t_hold)):
            tg = liberty.Group('timing')
            tg.add_attribute('related_pin', trigger.name)
            tg.add_attribute('timing_type', f'{kind}_{edge}')
            lut_name = ('rise_constraint' if out_transition == '01'
                        else 'fall_constraint')
            lut = LookupTable(
                lut_name, f'constraint_template_{n_ds}x{n_cs}',
                constrained_pin_transition=[data_slew],
                related_pin_transition=[clock_slew])
            lut.values[0, 0] = round(value, 4)
            tg.add_group(lut)
            result.group('pin', pin_name).add_group(tg)
    return result

# Copyright (C) 2026 Eric Nelson
# SPDX-License-Identifier: GPL-3.0-only
import math
import chelper


COMPLETE_MARGIN = 0.200
HEAT_POLL = 0.250
MAX_DWELL = 30.0
ABSOLUTE_MIN_TEMP = 170.0


class _QueueState:
    def __init__(self, trapq):
        self.trapq = trapq
        self.end_time = 0.0
        self.position = 0.0
        self.pending = False
        self.faulted = False


class SidecarBackground:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.max_profile_distance = config.getfloat(
            'max_profile_distance', 200.0, above=0.0)
        self.states = {}
        self.ffi_main, self.ffi_lib = chelper.get_ffi()
        self.gcode.register_command('SC_BG_BUSY', self.cmd_SC_BG_BUSY,
                                    desc='Report pending parked extruder motion')
        self.gcode.register_command('SC_BG_LOAD', self.cmd_SC_BG_LOAD,
                                    desc='Heat and queue a parked load profile')
        self.gcode.register_command('SC_BG_UNLOAD', self.cmd_SC_BG_UNLOAD,
                                    desc='Heat and queue a parked unload profile')

    def _resolve(self, gcmd):
        name = gcmd.get('EXTRUDER')
        if name not in ('extruder', 'extruder1', 'extruder2', 'extruder3'):
            raise gcmd.error('SC_BG: invalid extruder %s' % name)
        extr = self.printer.lookup_object(name, None)
        if extr is None or extr.extruder_stepper is None:
            raise gcmd.error('SC_BG: unavailable extruder %s' % name)
        return name, extr

    def _state(self, name):
        state = self.states.get(name)
        if state is None:
            trapq = self.ffi_main.gc(self.ffi_lib.trapq_alloc(),
                                     self.ffi_lib.trapq_free)
            state = self.states[name] = _QueueState(trapq)
        return state

    def _remaining(self, state, toolhead):
        if not state.pending:
            return 0.0
        eventtime = self.reactor.monotonic()
        estimated = toolhead.mcu.estimated_print_time(eventtime)
        return max(0.0, state.end_time + COMPLETE_MARGIN - estimated)

    def _finish_if_idle(self, name, extr, toolhead):
        state = self.states.get(name)
        if state is None or not state.pending or self._remaining(state, toolhead):
            return False
        # The MCU has passed the scheduled end. Put the normal queue at the
        # resulting E position before this toolhead can be activated.
        es = extr.extruder_stepper
        if es.stepper.get_trapq() is not extr.get_trapq():
            state.faulted = True
            raise self.printer.command_error('SC_BG: queue ownership changed')
        es.stepper.set_position([state.position, 0., 0.])
        state.pending = False
        return True

    def require_idle(self, name):
        """Called by the stock hooks before selection or queue reassignment."""
        state = self.states.get(name)
        if state is None:
            return
        if state.faulted:
            raise self.printer.command_error('SC_BG: queue fault; restart required')
        extr = self.printer.lookup_object(name, None)
        if extr is None:
            raise self.printer.command_error('SC_BG: missing extruder %s' % name)
        toolhead = self.printer.lookup_object('toolhead')
        self._finish_if_idle(name, extr, toolhead)
        if state.pending:
            raise self.printer.command_error('SC_BG: %s still moving' % name)

    def _check_target(self, gcmd, name, extr, toolhead):
        self.require_idle(name)
        for other_name, state in self.states.items():
            if other_name != name:
                self.require_idle(other_name)
        if toolhead.get_extruder() is extr:
            raise gcmd.error('SC_BG: target extruder is active')
        status = extr.get_park_detector_status()
        if not isinstance(status, dict) or status.get('state') != 'PARKED':
            raise gcmd.error('SC_BG: target extruder is not confirmed parked')
        if extr.activating_move:
            raise gcmd.error('SC_BG: tool change in progress')
        es = extr.extruder_stepper
        if es.stepper.get_trapq() is not extr.get_trapq():
            raise gcmd.error('SC_BG: target stepper is assigned elsewhere')
        if es.motion_queue not in (None, name):
            raise gcmd.error('SC_BG: target stepper motion queue differs')

    def _segment(self, gcmd, extr, distance, velocity, accel, line, gap=0.0):
        values = (distance, velocity, accel, gap)
        if not all(math.isfinite(x) for x in values):
            raise gcmd.error('SC_BG: nonfinite motion value')
        if abs(distance) <= 1.0e-9:
            return None
        if velocity <= 0.0 or velocity > extr.max_e_velocity:
            raise gcmd.error('SC_BG: velocity outside extruder limit')
        if accel < 0.0 or accel > extr.max_e_accel:
            raise gcmd.error('SC_BG: acceleration outside extruder limit')
        if abs(distance) > extr.max_e_dist:
            raise gcmd.error('SC_BG: segment exceeds extrude-only distance')
        if gap < 0.0 or gap > MAX_DWELL:
            raise gcmd.error('SC_BG: inter-segment dwell outside limit')
        return distance, velocity, accel, line, gap

    def _check_profile(self, gcmd, segments):
        segments = [seg for seg in segments if seg is not None]
        if not segments:
            raise gcmd.error('SC_BG: empty motion profile')
        if sum(abs(s[0]) for s in segments) > self.max_profile_distance:
            raise gcmd.error('SC_BG: profile exceeds total distance limit')
        return segments

    def _heat(self, gcmd, extr, target, minimum, timeout):
        heater = extr.get_heater()
        if not all(math.isfinite(x) for x in (target, minimum, timeout)):
            raise gcmd.error('SC_BG: nonfinite heater value')
        if (target <= 0.0 or minimum < max(heater.min_extrude_temp,
                                           ABSOLUTE_MIN_TEMP)
                or minimum > target or timeout <= 0.0):
            raise gcmd.error('SC_BG: unsafe temperature or timeout')
        heaters = self.printer.lookup_object('heaters')
        if (heater.get_name() not in heaters.active_heating_extruders
                and len(heaters.active_heating_extruders)
                >= heaters.max_heating_extruders):
            raise gcmd.error('SC_BG: stock heater slots busy')
        original_target = heater.get_status(self.reactor.monotonic())['target']
        heaters.set_temperature(heater, target, False)
        deadline = self.reactor.monotonic() + timeout
        try:
            while True:
                if self.printer.is_shutdown():
                    raise gcmd.error('SC_BG: printer shut down during heater wait')
                eventtime = self.reactor.monotonic()
                status = heater.get_status(eventtime)
                actual = float(status.get('temperature', 0.0))
                setpoint = float(status.get('target', 0.0))
                if setpoint < target - 0.5:
                    raise gcmd.error('SC_BG: heater target changed during wait')
                if actual >= minimum and heater.can_extrude:
                    return
                if eventtime >= deadline:
                    raise gcmd.error('SC_BG: heater wait timed out')
                self.reactor.pause(eventtime + HEAT_POLL)
        except Exception:
            # Restore the prior setpoint only if this command still owns it.
            if heater.get_status(self.reactor.monotonic())['target'] == target:
                heaters.set_temperature(heater, original_target, False)
            raise

    def _queue(self, gcmd, name, extr, segments, sync, target, minimum):
        toolhead = self.printer.lookup_object('toolhead')
        self._check_target(gcmd, name, extr, toolhead)
        if self.printer.is_shutdown():
            raise gcmd.error('SC_BG: printer shut down')
        heater = extr.get_heater()
        status = heater.get_status(self.reactor.monotonic())
        if (not heater.can_extrude or status['temperature'] < minimum
                or status['target'] < target - 0.5):
            raise gcmd.error('SC_BG: heater no longer ready for motion')
        state = self._state(name)
        es = extr.extruder_stepper
        toolhead.flush_step_generation()
        start = toolhead.get_last_move_time()
        now = toolhead.mcu.estimated_print_time(self.reactor.monotonic())
        start = max(start, now + COMPLETE_MARGIN)
        pos = float(extr.last_position)
        end = start
        es.stepper.set_position([pos, 0., 0.])
        previous = es.stepper.set_trapq(state.trapq)
        try:
            for dist, vel, accel, line, gap in segments:
                end += gap
                magnitude = abs(dist)
                direction = 1.0 if dist > 0.0 else -1.0
                if accel:
                    cruise = min(vel, math.sqrt(magnitude * accel))
                    accel_t = cruise / accel
                    cruise_t = max(0.0, (magnitude - accel_t * cruise) / cruise)
                else:
                    cruise = vel
                    accel_t = 0.0
                    cruise_t = magnitude / vel
                self.ffi_lib.trapq_append(state.trapq, end,
                                          accel_t, cruise_t, accel_t,
                                          pos, 0., 0., direction, 0., 0.,
                                          0., cruise, accel, line)
                pos += dist
                end += 2.0 * accel_t + cruise_t
            es.stepper.generate_steps(end)
            self.ffi_lib.trapq_finalize_moves(
                state.trapq, end + 99999.9, end + 99999.9)
        except Exception:
            # A partial low-level queue cannot be safely unwound by G-code.
            state.faulted = True
            raise
        finally:
            es.stepper.set_trapq(previous)
        extr.last_position = pos
        state.position = pos
        state.end_time = end
        state.pending = True
        toolhead.note_mcu_movequeue_activity(end)
        if sync:
            while self._remaining(state, toolhead):
                self.reactor.pause(self.reactor.monotonic() + HEAT_POLL)
            self._finish_if_idle(name, extr, toolhead)

    def cmd_SC_BG_BUSY(self, gcmd):
        name, extr = self._resolve(gcmd)
        toolhead = self.printer.lookup_object('toolhead')
        state = self.states.get(name)
        if state is not None and state.faulted:
            raise gcmd.error('SC_BG: queue fault; restart required')
        self._finish_if_idle(name, extr, toolhead)
        remaining = 0.0 if state is None else self._remaining(state, toolhead)
        gcmd.respond_info('SC_BG_BUSY busy=%d remaining=%.3f' %
                          (1 if remaining else 0, remaining))

    def cmd_SC_BG_LOAD(self, gcmd):
        name, extr = self._resolve(gcmd)
        fast_dist = gcmd.get_float('FAST_DIST', 0.0, minval=0.0)
        slow_dist = gcmd.get_float('SLOW_DIST', 0.0, minval=0.0)
        if not math.isfinite(fast_dist + slow_dist):
            raise gcmd.error('SC_BG: nonfinite load distance')
        segments = self._check_profile(gcmd, [
            self._segment(gcmd, extr, fast_dist,
                          gcmd.get_float('FAST_V', 0.0, minval=0.0),
                          gcmd.get_float('FAST_A', 0.0, minval=0.0),
                          gcmd.get_int('FAST_LINE', 2001)),
            self._segment(gcmd, extr, slow_dist,
                          gcmd.get_float('SLOW_V', 0.0, minval=0.0),
                          gcmd.get_float('SLOW_A', 0.0, minval=0.0),
                          gcmd.get_int('SLOW_LINE', 2002)),
        ])
        sync = gcmd.get_int('SYNC', 0, minval=0, maxval=1)
        toolhead = self.printer.lookup_object('toolhead')
        self._check_target(gcmd, name, extr, toolhead)
        target = gcmd.get_float('TEMP', above=0.0)
        minimum = gcmd.get_float('MIN_TEMP', above=0.0)
        self._heat(gcmd, extr, target, minimum,
                   gcmd.get_float('HEAT_TIMEOUT', above=0.0))
        self._queue(gcmd, name, extr, segments, sync, target, minimum)
        gcmd.respond_info('SC_BG_LOAD queued %s' % name)

    def cmd_SC_BG_UNLOAD(self, gcmd):
        name, extr = self._resolve(gcmd)
        pre = gcmd.get_float('PRE_DIST', 0.0, minval=0.0)
        r1 = gcmd.get_float('R1_DIST', 0.0, maxval=0.0)
        r2 = gcmd.get_float('R2_DIST', 0.0, maxval=0.0)
        r3 = gcmd.get_float('R3_DIST', 0.0, maxval=0.0)
        if not all(math.isfinite(x) for x in (pre, r1, r2, r3)):
            raise gcmd.error('SC_BG: nonfinite unload distance')
        accel = gcmd.get_float('ACCEL', 0.0, minval=0.0)
        gap = gcmd.get_float('DWELL_S', 0.0, minval=0.0, maxval=MAX_DWELL)
        segments = self._check_profile(gcmd, [
            self._segment(gcmd, extr, pre, gcmd.get_float('PRE_V', 0.0, minval=0.0), accel, 5101),
            self._segment(gcmd, extr, r1, gcmd.get_float('R1_V', 0.0, minval=0.0), accel, 5102),
            self._segment(gcmd, extr, r2, gcmd.get_float('R2_V', 0.0, minval=0.0), accel, 5103),
            self._segment(gcmd, extr, r3, gcmd.get_float('R3_V', 0.0, minval=0.0), accel, 5104,
                          gap if r3 else 0.0),
        ])
        sync = gcmd.get_int('SYNC', 0, minval=0, maxval=1)
        toolhead = self.printer.lookup_object('toolhead')
        self._check_target(gcmd, name, extr, toolhead)
        target = gcmd.get_float('TEMP', above=0.0)
        minimum = gcmd.get_float('MIN_TEMP', above=0.0)
        self._heat(gcmd, extr, target, minimum,
                   gcmd.get_float('HEAT_TIMEOUT', above=0.0))
        self._queue(gcmd, name, extr, segments, sync, target, minimum)
        gcmd.respond_info('SC_BG_UNLOAD queued %s' % name)


def load_config(config):
    return SidecarBackground(config)

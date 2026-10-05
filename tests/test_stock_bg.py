"""Offline command and queue safety checks for the stock U1 Sidecar extra."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (pathlib.Path(__file__).resolve().parents[1] / 'firmware' / 'u1'
          / 'stock-port' / 'klippy' / 'extras' / 'sc_bg.py')


class Lib:
    def __init__(self):
        self.moves = []
        self.finish = []

    def trapq_alloc(self):
        return object()

    def trapq_free(self, trapq):
        pass

    def trapq_append(self, *args):
        self.moves.append(args)

    def trapq_finalize_moves(self, *args):
        self.finish.append(args)


class Reactor:
    def __init__(self):
        self.time = 0.0
        self.on_pause = None

    def monotonic(self):
        return self.time

    def pause(self, when):
        self.time = when
        if self.on_pause is not None:
            self.on_pause()


class Heater:
    def __init__(self):
        self.min_extrude_temp = 170.0
        self.temperature = 220.0
        self.target = 0.0
        self.can_extrude = True

    def get_status(self, eventtime):
        return {'temperature': self.temperature, 'target': self.target}

    def get_name(self):
        return 'extruder1'


class Stepper:
    def __init__(self, trapq):
        self.trapq = trapq
        self.position = None
        self.generated = []
        self.raise_on_generate = False

    def get_trapq(self):
        return self.trapq

    def set_trapq(self, trapq):
        previous = self.trapq
        self.trapq = trapq
        return previous

    def set_position(self, pos):
        self.position = pos

    def generate_steps(self, time):
        if self.raise_on_generate:
            raise RuntimeError('fake step generation failure')
        self.generated.append(time)


class Extruder:
    def __init__(self, name):
        self.name = name
        self.trapq = object()
        self.extruder_stepper = types.SimpleNamespace(
            stepper=Stepper(self.trapq), motion_queue=None)
        self.heater = Heater()
        self.last_position = 0.0
        self.max_e_velocity = 100.0
        self.max_e_accel = 5000.0
        self.max_e_dist = 200.0
        self.activating_move = False
        self.park = 'PARKED'

    def get_trapq(self):
        return self.trapq

    def get_heater(self):
        return self.heater

    def get_park_detector_status(self):
        return {'state': self.park}


class Toolhead:
    def __init__(self, reactor, active):
        self.active = active
        self.time = 2.0
        self.mcu = types.SimpleNamespace(estimated_print_time=lambda t: t)
        self.notes = []

    def get_extruder(self):
        return self.active

    def flush_step_generation(self):
        pass

    def get_last_move_time(self):
        return self.time

    def note_mcu_movequeue_activity(self, end):
        self.notes.append(end)


class Gcode:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler


_MISSING = object()


class Command:
    def __init__(self, **values):
        self.values = values
        self.responses = []

    def get(self, key, default=_MISSING):
        if key in self.values:
            return self.values[key]
        if default is _MISSING:
            raise ValueError('missing ' + key)
        return default

    def get_float(self, key, default=_MISSING, minval=None, maxval=None,
                  above=None, below=None):
        val = float(self.get(key, default))
        if ((minval is not None and val < minval)
                or (maxval is not None and val > maxval)
                or (above is not None and val <= above)
                or (below is not None and val >= below)):
            raise ValueError('invalid ' + key)
        return val

    def get_int(self, key, default=_MISSING, minval=None, maxval=None):
        val = int(self.get(key, default))
        if ((minval is not None and val < minval)
                or (maxval is not None and val > maxval)):
            raise ValueError('invalid ' + key)
        return val

    def error(self, message):
        return ValueError(message)

    def respond_info(self, message):
        self.responses.append(message)


class Fixture:
    def __init__(self, module):
        self.reactor = Reactor()
        self.extr = Extruder('extruder1')
        self.active = Extruder('extruder')
        self.toolhead = Toolhead(self.reactor, self.active)
        self.gcode = Gcode()
        self.heaters = types.SimpleNamespace(
            active_heating_extruders=[], max_heating_extruders=2,
            set_temperature=lambda heater, temp, wait: setattr(heater, 'target', temp))
        self.objects = {'toolhead': self.toolhead, 'gcode': self.gcode,
                        'heaters': self.heaters, 'extruder1': self.extr}
        self.config = types.SimpleNamespace(
            get_printer=lambda: self,
            getfloat=lambda key, default, above=None: default)
        self.bg = module.load_config(self.config)
        self.objects['sc_bg'] = self.bg

    def get_reactor(self):
        return self.reactor

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    command_error = RuntimeError

    def is_shutdown(self):
        return False


def load_command(**params):
    values = dict(EXTRUDER='extruder1', TEMP=220, MIN_TEMP=210,
                  HEAT_TIMEOUT=20, FAST_DIST=45, FAST_V=10,
                  SLOW_DIST=35, SLOW_V=4)
    values.update(params)
    return Command(**values)


def unload_command(**params):
    values = dict(EXTRUDER='extruder1', TEMP=220, MIN_TEMP=220,
                  HEAT_TIMEOUT=20, PRE_DIST=5, PRE_V=10,
                  R1_DIST=-27, R1_V=45, R2_DIST=-5.5, R2_V=1,
                  DWELL_S=3.5, R3_DIST=-37.5, R3_V=25,
                  ACCEL=0)
    values.update(params)
    return Command(**values)


class StockBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.lib = Lib()
        ffi = types.SimpleNamespace(gc=lambda obj, free: obj)
        fake = types.SimpleNamespace(get_ffi=lambda: (ffi, self.lib))
        self.fake_chelper = patch.dict(sys.modules, {'chelper': fake})
        self.fake_chelper.start()
        self.addCleanup(self.fake_chelper.stop)
        spec = importlib.util.spec_from_file_location('test_sc_bg_stock', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.f = Fixture(module)

    def test_load_busy_and_activation_handoff(self):
        f = self.f
        f.bg.cmd_SC_BG_LOAD(load_command())
        self.assertEqual(len(self.lib.moves), 2)
        self.assertEqual(f.extr.last_position, 80.0)
        self.assertIs(f.extr.extruder_stepper.stepper.get_trapq(), f.extr.trapq)
        self.assertEqual(f.extr.extruder_stepper.stepper.generated,
                         [f.bg.states['extruder1'].end_time])
        query = Command(EXTRUDER='extruder1')
        f.bg.cmd_SC_BG_BUSY(query)
        self.assertIn('busy=1', query.responses[-1])
        with self.assertRaisesRegex(RuntimeError, 'still moving'):
            f.bg.require_idle('extruder1')
        f.reactor.time = f.bg.states['extruder1'].end_time + 0.3
        f.bg.cmd_SC_BG_BUSY(query)
        self.assertIn('busy=0', query.responses[-1])
        self.assertEqual(f.extr.extruder_stepper.stepper.position[0], 80.0)
        f.bg.require_idle('extruder1')

    def test_unload_signs_dwell_and_final_position(self):
        f = self.f
        f.bg.cmd_SC_BG_UNLOAD(unload_command())
        self.assertEqual([x[5] for x in self.lib.moves], [0., 5., -22., -27.5])
        self.assertEqual(len(self.lib.moves), 4)
        self.assertAlmostEqual(f.extr.last_position, -65.0)
        self.assertGreater(self.lib.moves[3][1] - self.lib.moves[2][1], 3.5)

    def test_guards_reject_active_unparked_and_low_temp(self):
        f = self.f
        f.toolhead.active = f.extr
        with self.assertRaisesRegex(ValueError, 'active'):
            f.bg.cmd_SC_BG_LOAD(load_command())
        f.toolhead.active = f.active
        f.extr.park = 'UNKNOWN'
        with self.assertRaisesRegex(ValueError, 'confirmed parked'):
            f.bg.cmd_SC_BG_LOAD(load_command())
        f.extr.park = 'PARKED'
        f.extr.heater.can_extrude = False
        with self.assertRaisesRegex(ValueError, 'timed out'):
            f.bg.cmd_SC_BG_LOAD(load_command())
        self.assertEqual(f.extr.heater.target, 0.0)
        self.assertFalse(self.lib.moves)

    def test_guard_rejects_invalid_segments_and_heater_contract(self):
        f = self.f
        with self.assertRaisesRegex(ValueError, 'total distance limit'):
            f.bg.cmd_SC_BG_LOAD(load_command(FAST_DIST=190, SLOW_DIST=35))
        with self.assertRaisesRegex(ValueError, 'unsafe temperature'):
            f.bg.cmd_SC_BG_LOAD(load_command(MIN_TEMP=100))
        with self.assertRaisesRegex(ValueError, 'velocity outside'):
            f.bg.cmd_SC_BG_LOAD(load_command(FAST_V=150))
        self.assertFalse(self.lib.moves)

    def test_generation_failure_sticks_until_restart(self):
        f = self.f
        f.extr.extruder_stepper.stepper.raise_on_generate = True
        with self.assertRaisesRegex(RuntimeError, 'fake step'):
            f.bg.cmd_SC_BG_LOAD(load_command())
        self.assertIs(f.extr.extruder_stepper.stepper.get_trapq(), f.extr.trapq)
        with self.assertRaisesRegex(RuntimeError, 'queue fault'):
            f.bg.require_idle('extruder1')
        with self.assertRaisesRegex(ValueError, 'queue fault'):
            f.bg.cmd_SC_BG_BUSY(Command(EXTRUDER='extruder1'))

    def test_busy_queue_blocks_another_target(self):
        f = self.f
        other = Extruder('extruder2')
        f.objects['extruder2'] = other
        f.bg.cmd_SC_BG_LOAD(load_command())
        with self.assertRaisesRegex(RuntimeError, 'still moving'):
            f.bg.cmd_SC_BG_LOAD(load_command(EXTRUDER='extruder2'))
        self.assertEqual(len(self.lib.moves), 2)
        f.reactor.time = f.bg.states['extruder1'].end_time + 0.3
        f.bg.cmd_SC_BG_LOAD(load_command(EXTRUDER='extruder2'))
        self.assertEqual(len(self.lib.moves), 4)

    def test_heater_wait_rejects_external_change_and_slot_limit(self):
        f = self.f
        f.heaters.active_heating_extruders[:] = ['extruder', 'extruder2']
        with self.assertRaisesRegex(ValueError, 'heater slots busy'):
            f.bg.cmd_SC_BG_LOAD(load_command())
        self.assertEqual(f.extr.heater.target, 0.0)
        f.heaters.active_heating_extruders.clear()
        f.extr.heater.temperature = 100.0
        f.extr.heater.can_extrude = False
        f.reactor.on_pause = lambda: setattr(f.extr.heater, 'target', 0.0)
        with self.assertRaisesRegex(ValueError, 'heater target changed'):
            f.bg.cmd_SC_BG_LOAD(load_command())
        self.assertFalse(self.lib.moves)


if __name__ == '__main__':
    unittest.main()

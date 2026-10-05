import { useEffect, useMemo, useRef, useState } from 'react';
import { FilamentSpools } from './components/FilamentSpools';
import { ControlPanel } from './components/ControlPanel';
import { StatusBar } from './components/StatusBar';
import { MenuScreen } from './components/MenuScreen';
import { OverviewScreen } from './components/OverviewScreen';
import { OptimizationMaximumScreen } from './components/OptimizationMaximumScreen';
import { CalibrationScreen } from './components/CalibrationScreen';
import { LoadCellCalibrationScreen } from './components/LoadCellCalibrationScreen';
import { ServoMappingScreen } from './components/ServoMappingScreen';
import { ServoTestScreen } from './components/ServoTestScreen';
import { ServoAdjustmentScreen } from './components/ServoAdjustmentScreen';
import { SettingsScreen } from './components/SettingsScreen';
import {
  getLaneMeta,
  getServoMapping,
  getServoMappingStorageKey,
  moveServoToolhead,
  moonrakerGcode,
  postLoad,
  postRemove,
  postUnload,
  resetServoMapping,
  setLaneMeta,
  setServoMapping,
  startServoIdentify,
  stopServoIdentify,
} from './lib/sidecarApi';
import { useSidecarState } from './src/hooks/useSidecarState';

export interface Spool {
  id: number;
  material: string;
  color: string;
  temperature: number;
  humidity: number;
  remaining: number;
  isActive: boolean;
  isLoaded: boolean;
  weight: number;
  uiStatus?: string;
}

type Screen =
  | 'main'
  | 'menu'
  | 'overview'
  | 'optimizationMaximum'
  | 'calibration'
  | 'loadCellCalibration'
  | 'servoMapping'
  | 'servoTest'
  | 'servoAdjustment'
  | 'settings';

type ServoPortMapping = { 1: number | null; 2: number | null; 3: number | null; 4: number | null };

function emptyServoMapping(): ServoPortMapping {
  return { 1: null, 2: null, 3: null, 4: null };
}

function parseServoMapping(raw: string | null): ServoPortMapping {
  if (!raw) return emptyServoMapping();
  try {
    const parsed = JSON.parse(raw);
    const mapping = emptyServoMapping();
    for (const port of [1, 2, 3, 4] as const) {
      const value = parsed?.[port];
      mapping[port] = value === 1 || value === 2 || value === 3 || value === 4 ? value : null;
    }
    return mapping;
  } catch {
    return emptyServoMapping();
  }
}

function defaultToolheadSpools(): Record<number, Spool[]> {
  return {
    1: [
      { id: 1, material: 'PLA', color: '#ef4444', temperature: 22, humidity: 45, remaining: 85, isActive: true, isLoaded: true, weight: 850 },
      { id: 2, material: 'PLA', color: '#3b82f6', temperature: 23, humidity: 42, remaining: 60, isActive: false, isLoaded: true, weight: 600 },
      { id: 3, material: 'PLA', color: '#22c55e', temperature: 22, humidity: 38, remaining: 15, isActive: false, isLoaded: true, weight: 150 },
      { id: 4, material: 'PLA', color: '#a855f7', temperature: 24, humidity: 50, remaining: 0, isActive: false, isLoaded: true, weight: 0 },
    ],
    2: [
      { id: 1, material: 'PLA', color: '#06b6d4', temperature: 21, humidity: 48, remaining: 70, isActive: true, isLoaded: true, weight: 700 },
      { id: 2, material: 'PLA', color: '#f97316', temperature: 22, humidity: 40, remaining: 55, isActive: false, isLoaded: true, weight: 550 },
      { id: 3, material: 'PLA', color: '#eab308', temperature: 23, humidity: 35, remaining: 80, isActive: false, isLoaded: true, weight: 800 },
      { id: 4, material: 'PLA', color: '#ec4899', temperature: 22, humidity: 47, remaining: 3, isActive: false, isLoaded: true, weight: 30 },
    ],
    3: [
      { id: 1, material: 'PLA', color: '#8b5cf6', temperature: 24, humidity: 52, remaining: 45, isActive: true, isLoaded: true, weight: 450 },
      { id: 2, material: 'PLA', color: '#10b981', temperature: 22, humidity: 44, remaining: 20, isActive: false, isLoaded: true, weight: 200 },
      { id: 3, material: 'PLA', color: '#f59e0b', temperature: 23, humidity: 41, remaining: 30, isActive: false, isLoaded: true, weight: 300 },
      { id: 4, material: 'PLA', color: '#6366f1', temperature: 22, humidity: 39, remaining: 65, isActive: false, isLoaded: true, weight: 650 },
    ],
    4: [
      { id: 1, material: 'PLA', color: '#ef4444', temperature: 22, humidity: 45, remaining: 85, isActive: true, isLoaded: true, weight: 850 },
      { id: 2, material: 'PLA', color: '#3b82f6', temperature: 23, humidity: 42, remaining: 4, isActive: false, isLoaded: true, weight: 40 },
      { id: 3, material: 'PLA', color: '#22c55e', temperature: 22, humidity: 38, remaining: 40, isActive: false, isLoaded: true, weight: 400 },
      { id: 4, material: 'PLA', color: '#a855f7', temperature: 24, humidity: 50, remaining: 95, isActive: false, isLoaded: true, weight: 950 },
    ],
  };
}

export default function App() {
  const [selectedToolhead, setSelectedToolhead] = useState(1);
  const [demoMode, setDemoMode] = useState(false);
  const [toolheadSpools, setToolheadSpools] = useState<Record<number, Spool[]>>(defaultToolheadSpools());
  const [systemStatus, setSystemStatus] = useState<'idle' | 'loading' | 'unloading' | 'feeding' | 'removing'>('idle');
  const [warningMessage, setWarningMessage] = useState('');
  const [selectedSpoolId, setSelectedSpoolId] = useState<number | undefined>(undefined);
  const [currentScreen, setCurrentScreen] = useState<Screen>('main');
  const [servoMappingError, setServoMappingError] = useState('');
  const [servoMappings, setServoMappings] = useState<ServoPortMapping>(() => parseServoMapping(localStorage.getItem(getServoMappingStorageKey())));
  const servoMappingsRef = useRef<ServoPortMapping>(servoMappings);

  const sidecarState = useSidecarState(selectedToolhead, 500);

  useEffect(() => {
    setSelectedSpoolId(undefined);
    setWarningMessage('');
  }, [selectedToolhead]);

  useEffect(() => {
    let alive = true;

    async function loadServoMappings() {
      try {
        const data = await getServoMapping(2000);
        if (!alive) return;
        if (data?.ok && data?.mapping?.toolhead_to_port) {
          const mapping = emptyServoMapping();
          for (const [toolheadStr, portVal] of Object.entries(data.mapping.toolhead_to_port as Record<string, any>)) {
            const toolhead = Number(toolheadStr);
            const port = Number(portVal);
            if ((toolhead === 1 || toolhead === 2 || toolhead === 3 || toolhead === 4) && port >= 1 && port <= 4) {
              mapping[port as 1 | 2 | 3 | 4] = toolhead;
            }
          }
          servoMappingsRef.current = mapping;
          setServoMappings(mapping);
          localStorage.setItem(getServoMappingStorageKey(), JSON.stringify(mapping));
        }
      } catch {
      }
    }

    loadServoMappings();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;

    async function hydrateLaneMeta() {
      try {
        const data = await getLaneMeta(null, null, 2500);
        if (!alive || !data?.ok || !data?.cfg?.toolheads) return;
        const toolheads = data.cfg.toolheads as Record<string, any>;
        setToolheadSpools((prev) => {
          const next: Record<number, Spool[]> = { ...prev };
          for (const toolhead of [1, 2, 3, 4] as const) {
            const lanes = toolheads?.[String(toolhead)]?.lanes || {};
            next[toolhead] = prev[toolhead].map((spool) => {
              const laneMeta = lanes?.[String(spool.id)] || {};
              return {
                ...spool,
                color: typeof laneMeta.color === 'string' && laneMeta.color ? laneMeta.color : spool.color,
                material: typeof laneMeta.material === 'string' && laneMeta.material ? laneMeta.material : spool.material,
              };
            });
          }
          return next;
        });
      } catch {
      }
    }

    hydrateLaneMeta();
    return () => {
      alive = false;
    };
  }, []);

  const selectedToolheadBaseSpools = toolheadSpools[selectedToolhead];

  const spools = useMemo(() => {
    const derived = selectedToolheadBaseSpools.map((spool) => ({ ...spool }));
    if (!sidecarState || !sidecarState.ok) return derived;

    const atGears = Number(sidecarState.at_gears || 0);
    const needLth = sidecarState.need_lth || {};
    const endstops = sidecarState.endstops || {};
    const gsw = sidecarState.gsw || {};

    const rswByLane: Record<number, number> = {
      1: Number(endstops.RSW || 0),
      2: Number(endstops.L2RSW || 0),
      3: Number(endstops.L3RSW || 0),
      4: Number(endstops.L4RSW || 0),
    };

    const gswByLane: Record<number, number> = {
      1: Number(gsw[1] || 0),
      2: Number(gsw[2] || 0),
      3: Number(gsw[3] || 0),
      4: Number(gsw[4] || 0),
    };

    const needLthByLane: Record<number, number> = {
      1: Number(needLth.need_lth1 || 0),
      2: Number(needLth.need_lth2 || 0),
      3: Number(needLth.need_lth3 || 0),
      4: Number(needLth.need_lth4 || 0),
    };

    for (const spool of derived) {
      const lane = spool.id;
      const rsw = rswByLane[lane] || 0;
      const laneGsw = gswByLane[lane] || 0;
      const laneNeedLth = needLthByLane[lane] || 0;

      spool.isActive = atGears === lane;
      spool.isLoaded = laneGsw === 1;

      let uiStatus: string;
      if (spool.isActive) uiStatus = 'In Use';
      else if (laneGsw === 0) uiStatus = 'Empty';
      else if (rsw === 0) uiStatus = 'Remove spool';
      else if (laneNeedLth === 0) uiStatus = 'Ready';
      else uiStatus = 'Staged';

      spool.uiStatus = uiStatus;
    }

    return derived;
  }, [selectedToolheadBaseSpools, sidecarState]);

  const activeSpool = spools.find((spool) => spool.uiStatus === 'In Use');

  const handleSpoolSelect = (id: number) => {
    setSelectedSpoolId(id);
  };

  const handleLoad = async (id: number) => {
    if (demoMode) return;

    const head = selectedToolhead - 1;
    const currentInUseSpool = spools.find((spool) => spool.uiStatus === 'In Use');
    if (currentInUseSpool && currentInUseSpool.id !== id) {
      setWarningMessage(`Unload Lane ${currentInUseSpool.id} before loading Lane ${id}`);
      window.setTimeout(() => setWarningMessage(''), 3000);
      return;
    }

    setWarningMessage('');
    setSystemStatus('loading');
    try {
      const res = await postLoad(head, id);
      if (!res.ok) {
        setWarningMessage(res.error ? `Load blocked: ${res.error}` : 'Load failed');
        window.setTimeout(() => setWarningMessage(''), 4000);
      }
    } catch (err: any) {
      setWarningMessage(`Load error: ${err?.message || err}`);
      window.setTimeout(() => setWarningMessage(''), 4000);
    } finally {
      setSystemStatus('idle');
    }
  };

  const handleUnload = async (id: number) => {
    if (demoMode) return;

    const head = selectedToolhead - 1;
    setWarningMessage('');
    setSystemStatus('unloading');
    try {
      const res = await postUnload(head, id);
      if (!res.ok) {
        setWarningMessage(res.error ? `Unload blocked: ${res.error}` : 'Unload failed');
        window.setTimeout(() => setWarningMessage(''), 4000);
      }
    } catch (err: any) {
      setWarningMessage(`Unload error: ${err?.message || err}`);
      window.setTimeout(() => setWarningMessage(''), 4000);
    } finally {
      setSystemStatus('idle');
    }
  };

  const handleRemove = async (id: number) => {
    if (demoMode) return;

    const head = selectedToolhead - 1;
    const selected = spools.find((spool) => spool.id === id);
    if (selected?.uiStatus === 'In Use') {
      setWarningMessage('Please unload before removing');
      window.setTimeout(() => setWarningMessage(''), 3000);
      return;
    }

    setWarningMessage('');
    setSystemStatus('removing');
    try {
      if (selectedToolhead === 1) {
        const res = await postRemove(head, id);
        if (!res.ok) {
          setWarningMessage(res.error ? `Remove blocked: ${res.error}` : 'Remove failed');
          window.setTimeout(() => setWarningMessage(''), 4000);
        }
      } else {
        const script = `REMOVEL${id}${selectedToolhead}`;
        const res = await moonrakerGcode(script, 120000);
        if (res?.error) throw new Error(res?.error?.message || 'moonraker_error');
      }
    } catch (err: any) {
      setWarningMessage(`Remove error: ${err?.message || err}`);
      window.setTimeout(() => setWarningMessage(''), 4000);
    } finally {
      setSystemStatus('idle');
    }
  };

  const handleMaterialChange = async (id: number, material: string) => {
    if (demoMode) return;

    setToolheadSpools((prev) => ({
      ...prev,
      [selectedToolhead]: prev[selectedToolhead].map((spool) => (spool.id === id ? { ...spool, material } : spool)),
    }));

    try {
      const res = await setLaneMeta(selectedToolhead, id, { material }, 4000);
      if (res?.ok && res?.meta) {
        setToolheadSpools((prev) => ({
          ...prev,
          [selectedToolhead]: prev[selectedToolhead].map((spool) =>
            spool.id === id ? { ...spool, material: typeof res.meta.material === 'string' ? res.meta.material : material } : spool,
          ),
        }));
      }
    } catch {
    }
  };

  const handleColorChange = async (id: number, color: string) => {
    if (demoMode) return;

    setToolheadSpools((prev) => ({
      ...prev,
      [selectedToolhead]: prev[selectedToolhead].map((spool) => (spool.id === id ? { ...spool, color } : spool)),
    }));

    try {
      const res = await setLaneMeta(selectedToolhead, id, { color }, 4000);
      if (res?.ok && res?.meta) {
        setToolheadSpools((prev) => ({
          ...prev,
          [selectedToolhead]: prev[selectedToolhead].map((spool) =>
            spool.id === id ? { ...spool, color: typeof res.meta.color === 'string' ? res.meta.color : color } : spool,
          ),
        }));
      }
    } catch {
    }
  };

  const handleColorChangeForToolhead = async (toolhead: number, spoolId: number, color: string) => {
    if (demoMode) return;

    setToolheadSpools((prev) => ({
      ...prev,
      [toolhead]: prev[toolhead].map((spool) => (spool.id === spoolId ? { ...spool, color } : spool)),
    }));

    try {
      const res = await setLaneMeta(toolhead, spoolId, { color }, 4000);
      if (res?.ok && res?.meta) {
        setToolheadSpools((prev) => ({
          ...prev,
          [toolhead]: prev[toolhead].map((spool) =>
            spool.id === spoolId ? { ...spool, color: typeof res.meta.color === 'string' ? res.meta.color : color } : spool,
          ),
        }));
      }
    } catch {
    }
  };

  const handleServoIdentifyStart = async (port: number) => {
    setServoMappingError('');
    try {
      const res = await startServoIdentify(port, { lo_us: 1200, hi_us: 1800, period_ms: 500 }, 2000);
      if (!res.ok) setServoMappingError(res.error ? `Servo identify failed: ${res.error}` : 'Servo identify failed');
    } catch (err: any) {
      setServoMappingError(`Servo identify error: ${err?.message || err}`);
    }
  };

  const handleServoIdentifyStop = async () => {
    try {
      await stopServoIdentify(2000);
    } catch {
    }
  };

  const handleServoMappingsChange = async (mapping: ServoPortMapping) => {
    setServoMappings(mapping);
    localStorage.setItem(getServoMappingStorageKey(), JSON.stringify(mapping));

    const previous = servoMappingsRef.current;
    servoMappingsRef.current = mapping;

    if ([1, 2, 3, 4].every((port) => mapping[port as 1 | 2 | 3 | 4] === null)) {
      try {
        await resetServoMapping(2000);
      } catch {
      }
      return;
    }

    for (const port of [1, 2, 3, 4] as const) {
      const prevToolhead = previous[port];
      const nextToolhead = mapping[port];
      if (prevToolhead !== nextToolhead && nextToolhead !== null) {
        try {
          await setServoMapping(nextToolhead, port, 2000);
        } catch {
        }
      }
    }
  };

  const handleServoAction = async (toolhead: number, action: 'open' | 'close') => {
    if (demoMode) return;
    try {
      const res = await moveServoToolhead(toolhead, action, 2500);
      if (!res.ok) console.warn('[servoTest] move failed', res);
    } catch (err: any) {
      console.warn('[servoTest] move error', err?.message || err);
    }
  };

  return (
    <div className="w-screen h-screen bg-black flex items-center justify-center">
      <div className="w-[1024px] h-[600px] bg-black text-white overflow-hidden flex flex-col">
        {currentScreen === 'main' && (
          <>
            <StatusBar
              systemStatus={systemStatus}
              activeSpool={activeSpool}
              spools={spools}
              selectedToolhead={selectedToolhead}
              onToolheadChange={setSelectedToolhead}
              onMenuClick={() => setCurrentScreen('menu')}
              demoMode={demoMode}
            />

            <div className="flex-1 flex gap-2 p-2 overflow-hidden">
              <FilamentSpools
                spools={spools}
                onSpoolSelect={handleSpoolSelect}
                onMaterialChange={handleMaterialChange}
                onColorChange={handleColorChange}
                selectedToolhead={selectedToolhead}
                selectedSpoolId={selectedSpoolId}
              />

              <ControlPanel
                spools={spools}
                systemStatus={systemStatus}
                onLoad={handleLoad}
                onUnload={handleUnload}
                onRemove={handleRemove}
                warningMessage={warningMessage}
                selectedSpoolId={selectedSpoolId}
              />
            </div>
          </>
        )}

        {currentScreen === 'menu' && (
          <MenuScreen
            onClose={() => setCurrentScreen('main')}
            onOverview={() => setCurrentScreen('overview')}
            onOptimization={() => setCurrentScreen('optimizationMaximum')}
            onCalibration={() => setCurrentScreen('calibration')}
            onSettings={() => setCurrentScreen('settings')}
          />
        )}

        {currentScreen === 'overview' && (
          <OverviewScreen allSpools={toolheadSpools} onBack={() => setCurrentScreen('main')} onColorChange={handleColorChangeForToolhead} />
        )}

        {currentScreen === 'optimizationMaximum' && (
          <OptimizationMaximumScreen onBack={() => setCurrentScreen('main')} onDone={() => setCurrentScreen('main')} />
        )}

        {currentScreen === 'calibration' && (
          <CalibrationScreen
            onBack={() => setCurrentScreen('main')}
            onLoadCellCalibration={() => setCurrentScreen('loadCellCalibration')}
            onServoMapping={() => setCurrentScreen('servoMapping')}
            onServoTest={() => setCurrentScreen('servoTest')}
            onServoAdjustment={() => setCurrentScreen('servoAdjustment')}
          />
        )}

        {currentScreen === 'loadCellCalibration' && <LoadCellCalibrationScreen onBack={() => setCurrentScreen('calibration')} />}

        {currentScreen === 'servoMapping' && (
          <ServoMappingScreen
            onBack={() => setCurrentScreen('calibration')}
            onIdentifyStart={handleServoIdentifyStart}
            onIdentifyStop={handleServoIdentifyStop}
            initialMappings={servoMappings}
            onMappingsChange={handleServoMappingsChange}
            errorMessage={servoMappingError}
          />
        )}

        {currentScreen === 'servoTest' && <ServoTestScreen onBack={() => setCurrentScreen('calibration')} onServoAction={handleServoAction} />}

        {currentScreen === 'servoAdjustment' && <ServoAdjustmentScreen onBack={() => setCurrentScreen('calibration')} demoMode={demoMode} />}

        {currentScreen === 'settings' && (
          <SettingsScreen
            onBack={() => setCurrentScreen('main')}
            onAddAuxSidecar={() => console.log('Add Aux Sidecar clicked')}
            demoMode={demoMode}
            onDemoModeChange={setDemoMode}
          />
        )}
      </div>
    </div>
  );
}

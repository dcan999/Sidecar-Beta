import { useEffect, useState } from 'react';
import { Scale } from 'lucide-react';
import type { Spool } from '../App';
import { MaterialSelectionScreen } from './MaterialSelectionScreen';
import { ColorSelectionScreen } from './ColorSelectionScreen';
import { tareManualEmpty, tareMeasureEmpty } from '../lib/sidecarApi';
import { useSelectedToolheadLoadCellState } from '../src/hooks/useSelectedToolheadLoadCellState';
import { Delete } from 'lucide-react';

interface FilamentSpoolsProps {
  spools: Spool[];
  onSpoolSelect: (id: number) => void;
  onMaterialChange: (id: number, material: string) => void;
  onColorChange: (id: number, color: string) => void;
  selectedToolhead: number;
  selectedSpoolId?: number;
}

function getStatusClass(status: string | undefined, spool: Spool) {
  const resolved = status ?? (spool.isActive ? 'In Use' : spool.isLoaded ? 'Ready' : 'Empty');
  switch (resolved) {
    case 'In Use':
      return 'text-white';
    case 'Ready':
      return 'text-green-500';
    case 'Staged':
      return 'text-yellow-400';
    case 'Remove spool':
      return 'text-orange-400';
    default:
      return 'text-neutral-600';
  }
}

export function FilamentSpools({ spools, onSpoolSelect, onMaterialChange, onColorChange, selectedToolhead, selectedSpoolId }: FilamentSpoolsProps) {
  const [openMaterialSelection, setOpenMaterialSelection] = useState<number | null>(null);
  const [openColorSelection, setOpenColorSelection] = useState<number | null>(null);
  const [openTarePopup, setOpenTarePopup] = useState<number | null>(null);
  const [bareSpoolWeights, setBareSpoolWeights] = useState<Record<number, number>>({});
  const [bareWeightInput, setBareWeightInput] = useState('');
  const [manualWeightArmedLane, setManualWeightArmedLane] = useState<number | null>(null);
  const [tareError, setTareError] = useState('');

  const loadCellState = useSelectedToolheadLoadCellState(selectedToolhead, 500);
  const loadCellLanes = loadCellState.lanes;

  useEffect(() => {
    if (openTarePopup === null) return;
    const existing = loadCellLanes?.[openTarePopup]?.empty_spool_g;
    if (typeof existing === 'number' && !Number.isNaN(existing)) {
      setBareSpoolWeights((prev) => (prev[openTarePopup] === existing ? prev : { ...prev, [openTarePopup]: existing }));
    }
    setTareError('');
    setBareWeightInput('');
    setManualWeightArmedLane(null);
  }, [openTarePopup, loadCellLanes]);

  const handleMaterialSelect = (spoolId: number, material: string) => {
    onMaterialChange(spoolId, material);
    setOpenMaterialSelection(null);
  };

  const handleColorSelect = (spoolId: number, color: string) => {
    onColorChange(spoolId, color);
    setOpenColorSelection(null);
  };

  const handleBareWeightSubmit = (spoolId: number) => {
    const weight = parseFloat(bareWeightInput);
    if (!Number.isNaN(weight) && weight > 0) {
      setBareSpoolWeights((prev) => ({ ...prev, [spoolId]: weight }));
      setManualWeightArmedLane(spoolId);
      setBareWeightInput('');
      setTareError('');
    }
  };

  const handleTare = async (spoolId: number) => {
    setTareError('');

    let useManualWeight = manualWeightArmedLane === spoolId;
    let emptySpoolWeight = bareSpoolWeights[spoolId];

    if (!useManualWeight && bareWeightInput) {
      const parsed = parseFloat(bareWeightInput);
      if (!Number.isNaN(parsed) && parsed > 0) {
        emptySpoolWeight = parsed;
        useManualWeight = true;
        setBareSpoolWeights((prev) => ({ ...prev, [spoolId]: parsed }));
      }
    }

    try {
      if (useManualWeight && typeof emptySpoolWeight === 'number' && emptySpoolWeight > 0) {
        const res = await tareManualEmpty(selectedToolhead, spoolId, emptySpoolWeight, 6000);
        if (!res?.ok) throw new Error(res?.error || 'tare_failed');
      } else {
        const res = await tareMeasureEmpty(selectedToolhead, spoolId, 6000);
        if (!res?.ok) throw new Error(res?.error || 'tare_failed');
      }

      setOpenTarePopup(null);
      setManualWeightArmedLane(null);
      setBareWeightInput('');
    } catch (err) {
      setTareError(`Tare failed: ${(err as Error)?.message || String(err)}`);
    }
  };

  const getWeightClass = (weight: number | null) => {
    if (typeof weight !== 'number') return 'text-neutral-400';
    return weight >= 250 ? 'text-white' : 'text-red-500';
  };

  const getBarClass = (weight: number | null) => {
    if (typeof weight !== 'number') return 'bg-neutral-600';
    return weight >= 250 ? 'bg-white' : 'bg-red-500';
  };

  const getWeightPercentage = (weight: number | null) => {
    if (typeof weight !== 'number') return 0;
    return Math.min(100, Math.max(0, (weight / 1000) * 100));
  };

  return (
    <div className="flex-1 grid grid-cols-4 gap-2 relative">
      {spools.map((spool) => {
        const laneState = loadCellLanes?.[spool.id] || {};
        const netG = typeof laneState.net_g === 'number' ? laneState.net_g : null;
        const rawG = typeof laneState.raw_g === 'number' ? laneState.raw_g : null;
        const displayWeight = netG !== null ? netG : spool.weight;
        const statusLabel = spool.uiStatus ?? (spool.isActive ? 'In Use' : spool.isLoaded ? 'Ready' : 'Empty');

        return (
          <div
            key={spool.id}
            onClick={() => onSpoolSelect(spool.id)}
            className={`
              bg-neutral-900 rounded-lg border-2 transition-all relative cursor-pointer flex flex-col items-center py-3 px-2
              ${spool.isActive ? 'border-4 border-white breathe-border' : selectedSpoolId === spool.id ? 'border-4 border-white' : 'border-neutral-700'}
              ${!spool.isLoaded ? 'opacity-50' : ''}
            `}
          >
            <div className="text-3xl text-slate-400 mb-2">Lane {spool.id}</div>

            <div className="text-center mb-6">
              <span className={`text-3xl ${getStatusClass(statusLabel, spool)}`}>{statusLabel}</span>
            </div>

            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                setOpenColorSelection(openColorSelection === spool.id ? null : spool.id);
                setOpenMaterialSelection(null);
                setOpenTarePopup(null);
              }}
              className="transition-opacity hover:opacity-80 cursor-pointer mb-8"
            >
              <div
                className="w-20 h-20 rounded-full border-2 border-neutral-600"
                style={spool.color.startsWith('linear-gradient') ? { backgroundImage: spool.color } : { backgroundColor: spool.color }}
              />
            </button>

            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                setOpenMaterialSelection(openMaterialSelection === spool.id ? null : spool.id);
                setOpenColorSelection(null);
                setOpenTarePopup(null);
              }}
              className="px-4 py-2 rounded border border-slate-600 hover:border-slate-400 hover:bg-slate-700 transition-colors cursor-pointer text-3xl mb-2"
            >
              {spool.material}
            </button>

            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                setOpenTarePopup(openTarePopup === spool.id ? null : spool.id);
                setOpenMaterialSelection(null);
                setOpenColorSelection(null);
              }}
              className="w-12 h-12 rounded bg-neutral-800 border-2 border-white hover:border-neutral-400 hover:bg-neutral-700 transition-colors cursor-pointer flex items-center justify-center mb-1 mt-auto"
            >
              <Scale className="w-7 h-7" />
            </button>

            <div className="w-full">
              <div className={`text-2xl mb-1 text-center ${getWeightClass(displayWeight)}`}>
                {typeof displayWeight === 'number' ? `${displayWeight.toFixed(1)} g` : '—'}
              </div>

              <div className="w-full h-5">
                {spool.isLoaded ? (
                  <div className="bg-neutral-700 rounded-full overflow-hidden h-full">
                    <div
                      className={`h-full transition-all ${getBarClass(displayWeight)} ${typeof displayWeight === 'number' && displayWeight < 50 ? 'blink-low-weight' : ''}`}
                      style={{ width: `${getWeightPercentage(displayWeight)}%` }}
                    />
                  </div>
                ) : (
                  <div className="bg-neutral-700 rounded-full overflow-hidden h-full" />
                )}
              </div>
            </div>

            {openTarePopup === spool.id && (
              <div className="fixed inset-0 z-20 flex items-center justify-center bg-black" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                <div className="w-[1024px] h-[600px] bg-neutral-900 flex gap-6 p-5" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                  <div className="w-1/2 flex flex-col justify-center gap-4">
                    <h2 className="text-2xl mb-1">Toolhead {selectedToolhead} - Lane {spool.id}</h2>
                    <p className="text-lg leading-normal">
                      Place an empty spool of the same brand/type as the spool you will be loading into the tray, and press <span className="text-green-400 font-bold">Tare</span>.
                    </p>
                    <p className="text-lg leading-normal">
                      If you don&apos;t have an empty spool available, manually enter the empty spool weight, press <span className="text-blue-400 font-bold">OK</span>, then press <span className="text-green-400 font-bold">Tare</span> with the tray empty.
                    </p>

                    {tareError ? <div className="bg-red-900 border border-red-600 px-4 py-3 rounded-lg text-base">{tareError}</div> : null}

                    <div className="flex gap-4 mt-1">
                      <button
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleTare(spool.id);
                        }}
                        className="flex-1 bg-white hover:bg-neutral-200 text-black px-5 py-4 rounded-lg transition-colors text-xl"
                      >
                        Tare
                      </button>
                      <button
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenTarePopup(null);
                        }}
                        className="flex-1 bg-neutral-700 hover:bg-neutral-600 text-white px-5 py-4 rounded-lg transition-colors text-xl"
                      >
                        Cancel
                      </button>
                    </div>

                    <div className="mt-1">
                      <label className="block text-lg text-slate-300 text-center">
                        Bare Spool Weight (g)
                        {typeof rawG === 'number' ? <span className="ml-3 text-white font-bold text-2xl">{rawG.toFixed(1)}g</span> : <span className="ml-3 text-neutral-400 font-bold text-2xl">—</span>}
                      </label>
                      <div className="text-center text-sm text-neutral-400 mt-1">Saved empty spool: {typeof bareSpoolWeights[spool.id] === 'number' ? `${bareSpoolWeights[spool.id]}g` : '—'}</div>
                    </div>
                  </div>

                  <div className="w-1/2 flex items-center justify-center">
                    <div className="w-full max-w-md">
                      <div className="bg-black border-2 border-white rounded-lg px-5 py-4 mb-3 text-white text-3xl text-right min-h-[70px] flex items-center justify-end">
                        {bareWeightInput || '—'}
                      </div>

                      <div className="grid grid-cols-3 gap-3 mb-3">
                        {['7', '8', '9', '4', '5', '6', '1', '2', '3', 'Clear', '0', 'Del'].map((key) =>
                          key === 'Clear' ? (
                            <button
                              key={key}
                              onPointerDown={(e) => e.stopPropagation()}
                              onClick={(e) => {
                                e.stopPropagation();
                                setBareWeightInput('');
                              }}
                              className="bg-neutral-700 hover:bg-neutral-600 text-white px-5 py-5 rounded-lg transition-colors text-2xl border-2 border-white"
                            >
                              Clear
                            </button>
                          ) : key === 'Del' ? (
                            <button
                              key={key}
                              onPointerDown={(e) => e.stopPropagation()}
                              onClick={(e) => {
                                e.stopPropagation();
                                setBareWeightInput((prev) => prev.slice(0, -1));
                              }}
                              className="bg-orange-600 hover:bg-orange-700 text-white px-5 py-5 rounded-lg transition-colors flex items-center justify-center"
                            >
                              <Delete size={34} />
                            </button>
                          ) : (
                            <button
                              key={key}
                              onPointerDown={(e) => e.stopPropagation()}
                              onClick={(e) => {
                                e.stopPropagation();
                                setBareWeightInput((prev) => prev + key);
                              }}
                              className="bg-neutral-800 hover:bg-neutral-700 text-white px-5 py-5 rounded-lg transition-colors text-3xl border-2 border-neutral-600"
                            >
                              {key}
                            </button>
                          ),
                        )}
                      </div>

                      <button
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleBareWeightSubmit(spool.id);
                        }}
                        className="w-full bg-white hover:bg-neutral-200 text-black px-6 py-5 rounded-lg transition-colors text-2xl border-2 border-white"
                      >
                        OK
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {openMaterialSelection !== null && (
        <MaterialSelectionScreen
          spoolId={openMaterialSelection}
          toolhead={selectedToolhead}
          currentMaterial={spools.find((s) => s.id === openMaterialSelection)?.material || ''}
          onSelect={(material) => handleMaterialSelect(openMaterialSelection, material)}
          onClose={() => setOpenMaterialSelection(null)}
        />
      )}

      {openColorSelection !== null && (
        <ColorSelectionScreen
          spoolId={openColorSelection}
          toolhead={selectedToolhead}
          currentColor={spools.find((s) => s.id === openColorSelection)?.color || ''}
          onSelect={(color) => handleColorSelect(openColorSelection, color)}
          onClose={() => setOpenColorSelection(null)}
        />
      )}
    </div>
  );
}

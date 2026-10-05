import { ArrowLeft } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { Spool } from '../App';
import { useSidecarState } from '../src/hooks/useSidecarState';
import { useSelectedToolheadLoadCellState } from '../src/hooks/useSelectedToolheadLoadCellState';
import { ColorSelectionScreen } from './ColorSelectionScreen';

interface OverviewScreenProps {
  allSpools: Record<number, Spool[]>;
  onBack: () => void;
  onColorChange: (toolhead: number, spoolId: number, color: string) => void;
}

function deriveLiveSpools(baseSpools: Spool[], state: any, loadCellState: any) {
  const derived = baseSpools.map((spool) => ({ ...spool }));
  const lanes = loadCellState?.lanes || {};

  if (!state?.ok) {
    return derived.map((spool) => {
      const laneWeight = lanes?.[spool.id]?.net_g;
      if (typeof laneWeight === 'number') spool.weight = laneWeight;
      return spool;
    });
  }

  const atGears = Number(state.at_gears || 0);
  const needLth = state.need_lth || {};
  const endstops = state.endstops || {};
  const gsw = state.gsw || {};

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
    const laneWeight = lanes?.[lane]?.net_g;

    spool.isActive = atGears === lane;
    spool.isLoaded = laneGsw === 1;
    if (typeof laneWeight === 'number') spool.weight = laneWeight;

    let uiStatus: string;
    if (spool.isActive) uiStatus = 'In Use';
    else if (laneGsw === 0) uiStatus = 'Empty';
    else if (rsw === 0) uiStatus = 'Remove spool';
    else if (laneNeedLth === 0) uiStatus = 'Ready';
    else uiStatus = 'Staged';

    spool.uiStatus = uiStatus;
  }

  return derived;
}

function getStatusClass(status: string | undefined) {
  switch (status) {
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

function getWeightClass(weight: number | null) {
  if (typeof weight !== 'number') return 'text-neutral-400';
  return weight >= 250 ? 'text-white' : 'text-red-500';
}

function getBarClass(weight: number | null) {
  if (typeof weight !== 'number') return 'bg-neutral-600';
  return weight >= 250 ? 'bg-white' : 'bg-red-500';
}

export function OverviewScreen({ allSpools, onBack, onColorChange }: OverviewScreenProps) {
  const [openColorSelection, setOpenColorSelection] = useState<{ toolhead: number; spoolId: number } | null>(null);

  const state1 = useSidecarState(1, 500);
  const state2 = useSidecarState(2, 500);
  const state3 = useSidecarState(3, 500);
  const state4 = useSidecarState(4, 500);

  const lc1 = useSelectedToolheadLoadCellState(1, 500);
  const lc2 = useSelectedToolheadLoadCellState(2, 500);
  const lc3 = useSelectedToolheadLoadCellState(3, 500);
  const lc4 = useSelectedToolheadLoadCellState(4, 500);

  const liveSpools = useMemo(
    () => ({
      1: deriveLiveSpools(allSpools[1], state1, lc1),
      2: deriveLiveSpools(allSpools[2], state2, lc2),
      3: deriveLiveSpools(allSpools[3], state3, lc3),
      4: deriveLiveSpools(allSpools[4], state4, lc4),
    }),
    [allSpools, state1, state2, state3, state4, lc1, lc2, lc3, lc4],
  );

  return (
    <div className="w-full h-full bg-black z-50 flex flex-col relative">
      <div className="absolute top-3 left-3 z-10">
        <button onClick={onBack} className="bg-neutral-900 hover:bg-neutral-800 rounded-lg transition-colors flex items-center justify-center p-2 border-2 border-white">
          <ArrowLeft size={24} />
        </button>
      </div>

      <div className="p-2 h-full flex flex-col">
        <div className="flex flex-col h-full gap-2">
          {[1, 2, 3, 4].map((toolhead) => (
            <div key={toolhead} className="flex-1" style={{ border: '3px solid white', borderRadius: '12px', padding: '8px', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', position: 'relative', minHeight: 0 }}>
              <div style={{ position: 'absolute', top: '-4px', left: '0', right: '0', textAlign: 'center' }}>
                <span className="text-lg" style={{ fontWeight: 'bold' }}>Toolhead #{toolhead}</span>
              </div>

              <div className="grid grid-cols-4 gap-2 h-full" style={{ marginTop: '22px' }}>
                {liveSpools[toolhead].map((spool) => {
                  const status = spool.uiStatus ?? (spool.isActive ? 'In Use' : spool.isLoaded ? 'Ready' : 'Empty');
                  const weight = typeof spool.weight === 'number' ? spool.weight : null;

                  return (
                    <div
                      key={`${toolhead}-${spool.id}`}
                      className={`bg-neutral-800 rounded transition-all h-full ${spool.isActive ? 'ring-2 ring-white' : ''}`}
                      style={{ padding: '5px', position: 'relative', minHeight: 0 }}
                    >
                      <div style={{ position: 'absolute', top: '5px', left: '5px', height: '14px' }}>
                        <span className="text-xs text-slate-400 leading-none">#{spool.id}</span>
                      </div>

                      <div style={{ position: 'absolute', top: '5px', right: '5px', width: '52px', height: '52px' }}>
                        <button
                          onPointerDown={(e) => e.stopPropagation()}
                          onClick={(e) => {
                            e.stopPropagation();
                            setOpenColorSelection({ toolhead, spoolId: spool.id });
                          }}
                          className="cursor-pointer hover:opacity-80 transition-opacity"
                        >
                          <div
                            className="rounded-full border border-neutral-600"
                            style={
                              spool.color.startsWith('linear-gradient')
                                ? { width: '52px', height: '52px', backgroundImage: spool.color }
                                : { width: '52px', height: '52px', backgroundColor: spool.color }
                            }
                          />
                        </button>
                      </div>

                      <div className="text-center" style={{ position: 'absolute', top: '2px', left: '5px', right: '5px', height: '20px', lineHeight: '20px' }}>
                        <span className={`leading-none text-base ${getStatusClass(status)}`}>{status}</span>
                      </div>

                      <div style={{ position: 'absolute', top: '34px', left: '5px', height: '18px' }}>
                        <span className={`font-bold leading-none text-base ${getWeightClass(weight)}`}>
                          {weight === null ? '—' : `${weight.toFixed(1)} g`}
                        </span>
                      </div>

                      <div className="text-center" style={{ position: 'absolute', top: '50%', left: '5px', right: '5px', transform: 'translateY(-50%)' }}>
                        <span className="leading-none text-2xl">{spool.material}</span>
                      </div>

                      <div style={{ position: 'absolute', bottom: '5px', left: '5px', right: '5px', height: '8px' }}>
                        {spool.isLoaded ? (
                          <div className="bg-neutral-700 rounded-full overflow-hidden h-full">
                            <div
                              className={`h-full transition-all ${getBarClass(weight)} ${typeof weight === 'number' && weight < 50 ? 'blink-low-weight' : ''}`}
                              style={{ width: `${spool.remaining}%` }}
                            />
                          </div>
                        ) : (
                          <div className="bg-neutral-700 rounded-full overflow-hidden h-full" />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {openColorSelection && (() => {
        const spool = liveSpools[openColorSelection.toolhead].find((s) => s.id === openColorSelection.spoolId);
        if (!spool) return null;

        return (
          <ColorSelectionScreen
            toolhead={openColorSelection.toolhead}
            spoolId={openColorSelection.spoolId}
            currentColor={spool.color}
            onSelect={(color) => {
              onColorChange(openColorSelection.toolhead, openColorSelection.spoolId, color);
              setOpenColorSelection(null);
            }}
            onClose={() => setOpenColorSelection(null)}
          />
        );
      })()}
    </div>
  );
}

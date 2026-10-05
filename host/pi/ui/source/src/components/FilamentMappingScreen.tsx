import { ArrowLeft } from 'lucide-react';
import * as React from 'react';
import type { Spool } from '../App';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';
import { ScrollArea } from './ui/scroll-area';

interface FilamentMappingScreenProps {
  allSpools: Record<number, Spool[]>;
  onBack: () => void;
}

export function FilamentMappingScreen({ allSpools, onBack }: FilamentMappingScreenProps) {
  const [selectedToolhead, setSelectedToolhead] = React.useState(1);

  const allSpoolsList: Array<{ toolhead: number; spool: Spool }> = [];
  [1, 2, 3, 4].forEach(toolhead => {
    allSpools[toolhead].forEach(spool => {
      allSpoolsList.push({ toolhead, spool });
    });
  });

  const currentToolheadSpools = allSpoolsList.filter(item => item.toolhead === selectedToolhead);

  const [laneMapping, setLaneMapping] = React.useState<Record<number, number>>(() => {
    const initial: Record<number, number> = {};
    for (let i = 1; i <= 16; i++) {
      initial[i] = i;
    }
    return initial;
  });

  const availableLanes = React.useMemo(() => {
    const startLane = (selectedToolhead - 1) * 4 + 1;
    const endLane = selectedToolhead * 4;
    return Array.from({ length: 4 }, (_, i) => startLane + i);
  }, [selectedToolhead]);

  const handleLaneChange = (physicalPosition: number, newLane: number) => {
    setLaneMapping(prev => {
      const existingPhysicalPosition = Object.entries(prev).find(
        ([pos, lane]) => lane === newLane && parseInt(pos) !== physicalPosition
      );

      if (existingPhysicalPosition) {
        const oldLane = prev[physicalPosition];
        return {
          ...prev,
          [physicalPosition]: newLane,
          [existingPhysicalPosition[0]]: oldLane,
        };
      } else {
        return {
          ...prev,
          [physicalPosition]: newLane,
        };
      }
    });
  };

  const getToolheadStatus = (toolhead: number): 'GOOD' | 'CHECK' => {
    const startPos = (toolhead - 1) * 4 + 1;
    const endPos = toolhead * 4;

    for (let pos = startPos; pos <= endPos; pos++) {
      if (laneMapping[pos] !== pos) {
        return 'CHECK';
      }
    }
    return 'GOOD';
  };

  return (
    <div className="w-full h-full bg-black z-50 flex flex-col relative">
      <div className="absolute top-2 left-2 z-10">
        <button
          onClick={onBack}
          className="bg-neutral-900 hover:bg-neutral-800 rounded-lg transition-colors flex items-center justify-center p-2 border-2 border-white"
        >
          <ArrowLeft size={24} />
        </button>
      </div>

      <div className="text-center pt-2 pb-1">
        <h2>Filament Mapping</h2>
      </div>

      <div className="flex gap-3 justify-center px-6 pb-4">
        {[1, 2, 3, 4].map(toolhead => {
          const status = getToolheadStatus(toolhead);
          return (
            <button
              key={toolhead}
              onClick={() => setSelectedToolhead(toolhead)}
              className={`px-8 py-3 rounded-lg text-xl transition-colors flex flex-col items-center ${
                selectedToolhead === toolhead
                  ? 'bg-white text-black border-2 border-white'
                  : 'bg-neutral-900 text-neutral-400 hover:bg-neutral-800 border-2 border-neutral-700'
              }`}
            >
              <div>Toolhead {toolhead}</div>
              <div className={`text-sm mt-1 ${
                status === 'GOOD' ? 'text-green-400' : 'text-red-400'
              }`}>
                {status}
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex-1 px-6 py-2 flex items-start justify-center">
        <div className="flex gap-6 items-start">
          <div className="flex flex-col gap-4">
            <div className="text-center text-xl text-slate-400 mb-2 h-[32px]">Slicer Assigned</div>
            {currentToolheadSpools.map((item, index) => {
              const physicalPosition = (selectedToolhead - 1) * 4 + index + 1;
              return (
                <div
                  key={physicalPosition}
                  className="h-[80px] bg-neutral-900 rounded px-5 flex items-center gap-3 border-2 border-neutral-700"
                  style={{ width: '320px' }}
                >
                  <span className="text-2xl text-slate-400 w-12">T{physicalPosition}</span>
                  <div
                    className="w-12 h-12 rounded flex-shrink-0"
                    style={{ backgroundColor: item.spool.color }}
                  />
                  <span className="text-xl">{item.spool.material}</span>
                </div>
              );
            })}
          </div>

          <div className="flex items-center text-slate-500 text-4xl" style={{ marginTop: '48px' }}>
            →
          </div>

          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 h-[32px]" style={{ width: '550px' }}>
              <div className="text-center text-xl text-slate-400" style={{ width: '280px' }}>MMU Lane</div>
              <div style={{ width: '130px' }}></div>
              <div style={{ width: '100px' }}></div>
            </div>
            {currentToolheadSpools.map((item, index) => {
              const physicalPosition = (selectedToolhead - 1) * 4 + index + 1;
              const assignedLane = laneMapping[physicalPosition];

              const lanePhysicalSpool = allSpoolsList[assignedLane - 1];

              return (
                <div
                  key={physicalPosition}
                  className="h-[80px] flex items-center gap-3"
                  style={{ width: '550px' }}
                >
                  {lanePhysicalSpool && (
                    <div className="flex items-center gap-3 bg-neutral-800 rounded px-4 h-full border-2 border-neutral-600" style={{ width: '280px' }}>
                      <span className="text-2xl text-neutral-400 w-12">L{assignedLane}</span>
                      <div
                        className="w-12 h-12 rounded flex-shrink-0"
                        style={{ backgroundColor: lanePhysicalSpool.spool.color }}
                      />
                      <span className="text-xl">{lanePhysicalSpool.spool.material}</span>
                    </div>
                  )}

                  <Select
                    value={assignedLane.toString()}
                    onValueChange={(value) => handleLaneChange(physicalPosition, parseInt(value))}
                  >
                    <SelectTrigger className="w-[130px] h-[60px] bg-neutral-900 border-2 border-white text-xl">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent
                      className="bg-neutral-900 border-2 border-white text-white max-h-[300px] overflow-y-auto z-[100]"
                      position="popper"
                      sideOffset={2}
                    >
                      <ScrollArea className="h-full">
                        <div className="p-1">
                          <SelectItem
                            value="0"
                            className="hover:bg-neutral-800 focus:bg-neutral-800 text-white text-lg py-3"
                          >
                            Unassigned
                          </SelectItem>

                          {availableLanes.map((laneNum) => (
                            <SelectItem
                              key={laneNum}
                              value={laneNum.toString()}
                              className="hover:bg-neutral-800 focus:bg-neutral-800 text-white text-lg py-3"
                            >
                              Lane {laneNum}
                            </SelectItem>
                          ))}
                        </div>
                      </ScrollArea>
                    </SelectContent>
                  </Select>

                  <div className="w-[100px] flex items-center justify-center">
                    {assignedLane === physicalPosition ? (
                      <span className="text-green-500 text-xl">GOOD</span>
                    ) : (
                      <span className="text-red-500 text-xl">CHECK</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

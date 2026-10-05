import { ArrowLeft } from 'lucide-react';
import { useMemo, useState } from 'react';

interface ServoMappingScreenProps {
  onBack: () => void;
  initialMappings: { 1: number | null; 2: number | null; 3: number | null; 4: number | null };
  onIdentifyStart: (port: number) => void;
  onIdentifyStop: () => void;
  onMappingsChange: (mapping: { 1: number | null; 2: number | null; 3: number | null; 4: number | null }) => void;
  errorMessage?: string;
}

type ToolheadOption = 1 | 2 | 3 | 4;

export function ServoMappingScreen({ onBack, initialMappings, onIdentifyStart, onIdentifyStop, onMappingsChange, errorMessage }: ServoMappingScreenProps) {
  const initial = useMemo(
    () => ({
      1: initialMappings?.[1] ?? null,
      2: initialMappings?.[2] ?? null,
      3: initialMappings?.[3] ?? null,
      4: initialMappings?.[4] ?? null,
    }),
    [],
  );
  const [servoMappings, setServoMappings] = useState(initial);
  const [openDropdown, setOpenDropdown] = useState<number | null>(null);

  const applyMappings = (next: { 1: number | null; 2: number | null; 3: number | null; 4: number | null }) => {
    setServoMappings(next);
    onMappingsChange?.(next);
  };

  const handleServoClick = (servoNumber: number) => {
    const nextOpen = openDropdown !== servoNumber;
    setOpenDropdown(nextOpen ? servoNumber : null);
    if (nextOpen) onIdentifyStart(servoNumber);
    else onIdentifyStop();
  };

  const handleToolheadSelect = (servoNumber: number, toolhead: ToolheadOption) => {
    const next = { ...servoMappings, [servoNumber]: toolhead } as { 1: number | null; 2: number | null; 3: number | null; 4: number | null };
    applyMappings(next);
    onIdentifyStop();
    setOpenDropdown(null);
  };

  const handleReset = () => {
    onIdentifyStop();
    setOpenDropdown(null);
    applyMappings({ 1: null, 2: null, 3: null, 4: null });
  };

  const handleBack = () => {
    onIdentifyStop();
    onBack();
  };

  const getAvailableToolheads = (currentServo: number): ToolheadOption[] => {
    const allToolheads: ToolheadOption[] = [1, 2, 3, 4];
    const usedToolheads = Object.entries(servoMappings)
      .filter(([servo, toolhead]) => Number(servo) !== currentServo && toolhead !== null)
      .map(([, toolhead]) => toolhead as ToolheadOption);

    return allToolheads.filter((th) => !usedToolheads.includes(th));
  };

  const getButtonLabel = (servoNumber: number) => {
    const mapping = servoMappings[servoNumber as keyof typeof servoMappings];
    return mapping ? `Toolhead ${mapping}` : `Servo ${servoNumber}`;
  };

  return (
    <div className="w-full h-full bg-black flex flex-col">
      <div className="bg-neutral-900 p-5 flex items-center justify-center border-b border-neutral-700 relative">
        <button onClick={handleBack} className="absolute left-5 p-2 hover:bg-neutral-800 rounded transition-colors">
          <ArrowLeft size={32} />
        </button>

        <h1 className="text-3xl">Servo Mapping</h1>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-6 p-8">
        <h2 className="text-2xl">Click a Servo Port to Identify</h2>

        {errorMessage ? <div className="bg-red-900 border border-red-600 px-5 py-3 rounded-lg text-lg text-center max-w-3xl">{errorMessage}</div> : null}

        <div className="grid grid-cols-2 gap-6 w-full max-w-3xl">
          {[1, 2, 3, 4].map((servoNum) => (
            <div key={servoNum} className="relative">
              <button
                onClick={() => handleServoClick(servoNum)}
                className="w-full bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[160px] flex flex-col items-center justify-center text-2xl"
              >
                {getButtonLabel(servoNum)}
              </button>

              {openDropdown === servoNum && (
                <div className={`absolute left-0 right-0 ${servoNum > 2 ? 'bottom-full mb-2' : 'top-full mt-2'} bg-neutral-800 border-2 border-white rounded-lg overflow-hidden z-10`}>
                  {getAvailableToolheads(servoNum).map((toolhead) => (
                    <button
                      key={toolhead}
                      onClick={() => handleToolheadSelect(servoNum, toolhead)}
                      className="w-full p-4 text-xl hover:bg-neutral-700 transition-colors text-left"
                    >
                      Toolhead {toolhead}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        <button onClick={handleReset} className="bg-neutral-700 hover:bg-neutral-600 px-10 py-3 rounded-lg transition-colors text-xl border-2 border-white">
          Reset Mapping
        </button>
      </div>
    </div>
  );
}

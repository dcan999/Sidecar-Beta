import { X, ArrowLeft } from 'lucide-react';

interface OptimizationMaximumScreenProps {
  onBack: () => void;
  onDone: () => void;
}

export function OptimizationMaximumScreen({ onBack, onDone }: OptimizationMaximumScreenProps) {
  const sidecarSpools = [
    [
      { lane: 1, color: '#ffffff' },
      { lane: 2, color: '#3b82f6' },
      { lane: 3, color: '#22c55e' },
      { lane: 4, color: '#a16207' },
    ],
    [
      { lane: 5, color: '#e5e5e5' },
      { lane: 6, color: '#ef4444' },
      { lane: 7, color: '#84cc16' },
      { lane: 8, color: '#eab308' },
    ],
    [
      { lane: 9, color: '#06b6d4' },
      { lane: 10, color: '#6b7280' },
      { lane: 11, color: '#f97316' },
      { lane: 12, color: '#8b5cf6' },
    ],
    [
      { lane: 13, color: '#0ea5e9' },
      { lane: 14, color: '#ec4899' },
      { lane: 15, color: '#14b8a6' },
      { lane: 16, color: '#10b981' },
    ],
  ];

  return (
    <div className="w-full h-full bg-black z-50 flex flex-col">
      <div className="bg-neutral-900 p-3 flex items-center justify-center border-b border-neutral-700 relative">
        <button
          onClick={onBack}
          className="absolute left-3 p-2 hover:bg-neutral-800 rounded transition-colors"
        >
          <X size={28} />
        </button>

        <h1 className="text-2xl font-semibold">Optimization</h1>
      </div>

      <div className="flex-1 p-2.5 flex flex-col overflow-hidden">
        <div className="max-w-full space-y-2 flex-1 flex flex-col">
          <div className="bg-neutral-900 p-2 rounded-lg border border-neutral-700">
            <h3 className="text-base mb-1 font-bold">Instructions:</h3>
            <div className="text-neutral-300 text-base">
              Arrange spools in each Sidecar as shown below
            </div>
          </div>

          <div className="flex-1 flex flex-col min-h-0">
            <h3 className="text-base mb-1.5 text-center font-semibold">Recommended Spool Arrangement</h3>
            <div className="grid grid-cols-4 gap-2">
              {sidecarSpools.map((spools, sidecarIndex) => (
                <div key={sidecarIndex} className="bg-neutral-900 p-2 rounded-lg border border-neutral-700">
                  <div className="text-center text-sm mb-2 text-neutral-400 font-medium">
                    Sidecar {sidecarIndex + 1}
                  </div>
                  <div className="flex items-center justify-center gap-1.5">
                    {spools.map((spool) => (
                      <div key={spool.lane} className="flex items-center justify-center">
                        <div
                          className="w-10 h-10 rounded flex items-center justify-center text-black font-bold text-sm border border-white flex-shrink-0"
                          style={{ backgroundColor: spool.color }}
                        >
                          {spool.lane}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-center">
            <button
              onClick={onDone}
              className="px-12 py-3 bg-white text-black rounded-lg hover:bg-neutral-200 transition-colors text-xl font-semibold"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

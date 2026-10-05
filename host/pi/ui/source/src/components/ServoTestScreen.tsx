import { ArrowLeft } from 'lucide-react';

interface ServoTestScreenProps {
  onBack: () => void;
  onServoAction: (toolhead: number, action: 'open' | 'close') => void;
}

export function ServoTestScreen({ onBack, onServoAction }: ServoTestScreenProps) {
  return (
    <div className="w-full h-full bg-black flex flex-col">
      <div className="bg-neutral-900 p-5 flex items-center justify-center border-b border-neutral-700 relative">
        <button
          onClick={onBack}
          className="absolute left-5 p-2 hover:bg-neutral-800 rounded transition-colors"
        >
          <ArrowLeft size={32} />
        </button>

        <h1 className="text-3xl">Servo Test</h1>
      </div>

      <div className="flex-1 flex items-center justify-center p-8">
        <div className="grid grid-cols-4 gap-6 w-full max-w-5xl">
          {[1, 2, 3, 4].map((toolhead) => (
            <div key={toolhead} className="flex flex-col items-center gap-4">
              <h2 className="text-2xl font-semibold mb-2">Toolhead {toolhead}</h2>

              <button
                onClick={() => onServoAction(toolhead, 'close')}
                className="w-full bg-neutral-700 hover:bg-neutral-600 px-6 py-6 rounded-lg transition-colors text-xl border-2 border-white"
              >
                CLOSE
              </button>

              <button
                onClick={() => onServoAction(toolhead, 'open')}
                className="w-full bg-neutral-700 hover:bg-neutral-600 px-6 py-6 rounded-lg transition-colors text-xl border-2 border-white"
              >
                OPEN
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

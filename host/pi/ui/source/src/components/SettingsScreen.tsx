import { X } from 'lucide-react';

interface SettingsScreenProps {
  onBack: () => void;
  onAddAuxSidecar: () => void;
  demoMode: boolean;
  onDemoModeChange: (enabled: boolean) => void;
}

export function SettingsScreen({ onBack, onAddAuxSidecar, demoMode, onDemoModeChange }: SettingsScreenProps) {
  return (
    <div className="w-full h-full bg-black z-50 flex flex-col">
      <div className="bg-neutral-900 p-5 flex items-center justify-center border-b border-neutral-700 relative">
        <button
          onClick={onBack}
          className="absolute left-5 p-2 hover:bg-neutral-800 rounded transition-colors"
        >
          <X size={32} />
        </button>

        <h1 className="text-3xl">Settings</h1>
      </div>

      <div className="flex-1 flex items-start justify-center p-10 overflow-y-auto">
        <div className="w-full max-w-2xl space-y-4">
          <div className="w-full bg-neutral-900 p-6 rounded-lg border-2 border-white flex flex-col items-start">
            <div className="flex items-center justify-between w-full">
              <div>
                <div className="text-xl">Demo Mode</div>
                <div className="text-sm text-neutral-400 mt-2">
                  Allow visitors to interact without making changes
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={demoMode}
                  onChange={(e) => onDemoModeChange(e.target.checked)}
                />
                <div className="w-14 h-7 bg-neutral-700 rounded-full peer peer-checked:bg-green-600 transition-colors relative">
                  <div className={`absolute top-0.5 left-0.5 bg-white w-6 h-6 rounded-full transition-transform ${demoMode ? 'translate-x-7' : ''}`}></div>
                </div>
              </label>
            </div>
          </div>

          <button
            onClick={onAddAuxSidecar}
            className="w-full bg-neutral-900 hover:bg-neutral-800 p-6 rounded-lg transition-colors border-2 border-white flex flex-col items-start"
          >
            <div className="text-xl">Add Aux Sidecar</div>
            <div className="text-sm text-neutral-400 mt-2">Connect additional filament feeder</div>
          </button>
        </div>
      </div>
    </div>
  );
}

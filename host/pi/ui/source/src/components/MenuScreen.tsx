import { X } from 'lucide-react';

interface MenuScreenProps {
  onClose: () => void;
  onOverview: () => void;
  onOptimization: () => void;
  onCalibration: () => void;
  onSettings: () => void;
}

export function MenuScreen({ onClose, onOverview, onOptimization, onCalibration, onSettings }: MenuScreenProps) {
  return (
    <div className="w-full h-full bg-black z-50 flex flex-col">
      <div className="bg-neutral-900 p-5 flex items-center justify-center border-b border-neutral-700 relative">
        <button
          onClick={onClose}
          className="absolute left-5 p-2 hover:bg-neutral-800 rounded transition-colors"
        >
          <X size={32} />
        </button>

        <h1 className="text-3xl">Menu</h1>
      </div>

      <div className="flex-1 flex items-center justify-center p-10">
        <div className="grid grid-cols-2 gap-6 max-w-4xl w-full">
          <button
            onClick={onOverview}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[180px] flex flex-col items-center justify-center"
          >
            <div className="text-xl">Overview</div>
            <div className="text-sm text-neutral-400 mt-2">View all filament lanes</div>
          </button>

          <button
            onClick={onOptimization}
            className="bg-neutral-800 hover:bg-neutral-700 transition-colors p-8 rounded-lg border-2 border-white/20"
          >
            <div className="text-2xl">Optimization</div>
          </button>

          <button
            onClick={onSettings}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[180px] flex flex-col items-center justify-center"
          >
            <div className="text-xl">Settings</div>
            <div className="text-sm text-neutral-400 mt-2">Configure system settings</div>
          </button>

          <button
            onClick={onCalibration}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[180px] flex flex-col items-center justify-center"
          >
            <div className="text-xl">Calibration</div>
            <div className="text-sm text-neutral-400 mt-2">Calibrate sensors</div>
          </button>
        </div>
      </div>
    </div>
  );
}

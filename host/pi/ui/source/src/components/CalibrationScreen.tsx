import { ArrowLeft } from 'lucide-react';

interface CalibrationScreenProps {
  onBack: () => void;
  onLoadCellCalibration: () => void;
  onServoMapping: () => void;
  onServoTest: () => void;
  onServoAdjustment: () => void;
}

export function CalibrationScreen({ onBack, onLoadCellCalibration, onServoMapping, onServoTest, onServoAdjustment }: CalibrationScreenProps) {
  return (
    <div className="w-full h-full bg-black flex flex-col">
      <div className="bg-neutral-900 p-5 flex items-center justify-center border-b border-neutral-700 relative">
        <button
          onClick={onBack}
          className="absolute left-5 p-2 hover:bg-neutral-800 rounded transition-colors"
        >
          <ArrowLeft size={32} />
        </button>

        <h1 className="text-3xl">Calibration</h1>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-8 p-10">
        <div className="grid grid-cols-2 gap-8 w-full max-w-4xl">
          <button
            onClick={onLoadCellCalibration}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[220px] flex flex-col items-center justify-center"
          >
            <div className="text-2xl mb-3">Load Cell Calibration</div>
            <div className="text-base text-neutral-400">Calibrate the load cell sensors</div>
          </button>
          <button
            onClick={onServoMapping}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[220px] flex flex-col items-center justify-center"
          >
            <div className="text-2xl mb-3">Servo Mapping</div>
            <div className="text-base text-neutral-400">Map the servo positions</div>
          </button>
          <button
            onClick={onServoTest}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[220px] flex flex-col items-center justify-center"
          >
            <div className="text-2xl mb-3">Servo Test</div>
            <div className="text-base text-neutral-400">Test the servo movements</div>
          </button>
          <button
            onClick={onServoAdjustment}
            className="bg-neutral-900 hover:bg-neutral-800 p-8 rounded-lg transition-colors border-2 border-white h-[220px] flex flex-col items-center justify-center"
          >
            <div className="text-2xl mb-3">Servo Adjustment</div>
            <div className="text-base text-neutral-400">Adjust the servo settings</div>
          </button>
        </div>
      </div>
    </div>
  );
}

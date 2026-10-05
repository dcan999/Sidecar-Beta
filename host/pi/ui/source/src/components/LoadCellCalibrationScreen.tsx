import { useState } from 'react';
import { ArrowLeft, Check } from 'lucide-react';
import { calibrateLoadCell, resetLoadCellCalibration } from '../lib/sidecarApi';

interface LoadCellCalibrationScreenProps {
  onBack: () => void;
  selectedToolhead: number;
}

export function LoadCellCalibrationScreen({ onBack, selectedToolhead }: LoadCellCalibrationScreenProps) {
  const [step, setStep] = useState<'full' | 'empty'>('full');
  const [weight, setWeight] = useState('');
  const [fullCompleted, setFullCompleted] = useState(false);
  const [emptyCompleted, setEmptyCompleted] = useState(false);
  const [showWarning, setShowWarning] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const handleCalibrate = async () => {
    const knownWeight = parseFloat(weight);
    if (Number.isNaN(knownWeight) || knownWeight <= 0) return;

    setErrorMessage('');
    setSuccessMessage('');

    try {
      const res = await calibrateLoadCell(selectedToolhead, step, knownWeight, 8000);
      if (!res?.ok) throw new Error(res?.error || 'calibrate_failed');

      if (typeof res?.lane === 'number') {
        setSuccessMessage(`Calibrated lane ${res.lane} (${step.toUpperCase()})`);
      }

      if (step === 'full') {
        setFullCompleted(true);
        setStep('empty');
        setWeight('');
      } else {
        setEmptyCompleted(true);
      }
    } catch (err) {
      setErrorMessage(`Calibration failed: ${(err as Error)?.message || String(err)}`);
    }
  };

  const handleExit = () => {
    if (!fullCompleted || !emptyCompleted) {
      setShowWarning(true);
    } else {
      onBack();
    }
  };

  const confirmExit = async () => {
    try {
      await resetLoadCellCalibration(selectedToolhead, 2000);
    } catch {
    }
    onBack();
  };

  const cancelExit = () => {
    setShowWarning(false);
  };

  const handleNumberClick = (num: string) => {
    setWeight((prev) => prev + num);
  };

  const handleClear = () => {
    setWeight('');
  };

  const handleBackspace = () => {
    setWeight((prev) => prev.slice(0, -1));
  };

  return (
    <div className="w-full h-full bg-black flex flex-col">
      <div className="bg-neutral-900 p-4 flex items-center justify-center border-b border-neutral-700 relative">
        <button onClick={handleExit} className="absolute left-4 p-2 hover:bg-neutral-800 rounded transition-colors">
          <ArrowLeft size={28} />
        </button>

        <h1 className="text-2xl">Load Cell Calibration</h1>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center p-3 overflow-y-auto">
        <div className="max-w-2xl w-full space-y-3">
          <div className="flex justify-center gap-12">
            <div className="flex flex-col items-center gap-1">
              <div className="text-sm text-neutral-300">FULL</div>
              <div className={`w-6 h-6 rounded border-2 flex items-center justify-center ${fullCompleted ? 'bg-white border-white' : 'border-neutral-500'}`}>
                {fullCompleted && <Check size={20} className="text-black" />}
              </div>
            </div>
            <div className="flex flex-col items-center gap-1">
              <div className="text-sm text-neutral-300">EMPTY</div>
              <div className={`w-6 h-6 rounded border-2 flex items-center justify-center ${emptyCompleted ? 'bg-white border-white' : 'border-neutral-500'}`}>
                {emptyCompleted && <Check size={20} className="text-black" />}
              </div>
            </div>
          </div>

          <div className="bg-neutral-900 p-3 rounded-lg border border-neutral-700">
            <p className="text-base text-center leading-tight">
              {step === 'full'
                ? 'Place a full spool of known weight in the center of the tray, enter the weight in the box, and press CALIBRATE'
                : 'Place an empty spool of known weight on the tray, enter the weight, and press CALIBRATE'}
            </p>
          </div>

          {errorMessage ? <div className="bg-red-900 border border-red-600 p-3 rounded-lg text-center text-base">{errorMessage}</div> : null}
          {successMessage ? <div className="bg-neutral-900 border border-neutral-700 p-3 rounded-lg text-center text-sm text-neutral-300">{successMessage}</div> : null}

          <div className="bg-neutral-900 p-2 rounded-lg border-2 border-white">
            <div className="text-xs text-neutral-400 text-center mb-1">Weight (grams)</div>
            <div className="text-3xl text-center h-12 flex items-center justify-center">{weight || '0'}</div>
          </div>

          {!(fullCompleted && emptyCompleted) && (
            <div className="grid grid-cols-3 gap-2">
              {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((num) => (
                <button
                  key={num}
                  onClick={() => handleNumberClick(num)}
                  className="bg-neutral-800 hover:bg-neutral-700 p-3 rounded-lg text-xl transition-colors border border-neutral-600"
                >
                  {num}
                </button>
              ))}
              <button onClick={handleClear} className="bg-neutral-800 hover:bg-neutral-700 p-3 rounded-lg text-sm transition-colors border border-neutral-600">
                Clear
              </button>
              <button onClick={() => handleNumberClick('0')} className="bg-neutral-800 hover:bg-neutral-700 p-3 rounded-lg text-xl transition-colors border border-neutral-600">
                0
              </button>
              <button onClick={handleBackspace} className="bg-neutral-800 hover:bg-neutral-700 p-3 rounded-lg text-sm transition-colors border border-neutral-600">
                ←
              </button>
            </div>
          )}

          {!(fullCompleted && emptyCompleted) && (
            <button
              onClick={() => void handleCalibrate()}
              disabled={!weight}
              className={`w-full py-3 rounded-lg text-xl font-semibold transition-colors ${weight ? 'bg-white text-black hover:bg-neutral-200' : 'bg-neutral-700 text-neutral-500 cursor-not-allowed'}`}
            >
              CALIBRATE
            </button>
          )}

          {fullCompleted && emptyCompleted && (
            <div className="bg-green-900 border border-green-600 p-8 rounded-lg text-center">
              <p className="text-2xl text-green-200">✓ Calibration Complete!</p>
              <p className="text-sm text-green-300 mt-2">You can now exit this screen</p>
            </div>
          )}
        </div>
      </div>

      {showWarning && (
        <div className="absolute inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50">
          <div className="bg-neutral-900 p-8 rounded-lg border-2 border-red-500 max-w-md">
            <h2 className="text-2xl mb-4 text-center text-red-500">Warning</h2>
            <p className="text-lg mb-6 text-center">You haven't completed both calibrations. Are you sure you want to exit?</p>
            <div className="flex gap-4">
              <button onClick={cancelExit} className="flex-1 py-3 bg-neutral-700 hover:bg-neutral-600 rounded-lg text-lg transition-colors">
                Cancel
              </button>
              <button onClick={() => void confirmExit()} className="flex-1 py-3 bg-red-600 hover:bg-red-700 rounded-lg text-lg transition-colors">
                Exit Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { Download, Upload, XCircle } from 'lucide-react';
import type { Spool } from '../App';

interface ControlPanelProps {
  spools: Spool[];
  systemStatus: 'idle' | 'loading' | 'unloading' | 'feeding' | 'removing';
  onLoad: (id: number) => void;
  onUnload: (id: number) => void;
  onRemove: (id: number) => void;
  warningMessage: string;
  selectedSpoolId?: number;
}

export function ControlPanel({ spools, systemStatus, onLoad, onUnload, onRemove, warningMessage, selectedSpoolId }: ControlPanelProps) {
  const isProcessing = systemStatus !== 'idle';

  const inUseSpool = spools.find((spool) => spool.uiStatus === 'In Use');
  const selectedSpool = selectedSpoolId ? spools.find((spool) => spool.id === selectedSpoolId) : inUseSpool;
  const selectedStatus = selectedSpool?.uiStatus ?? (selectedSpool?.isActive ? 'In Use' : selectedSpool?.isLoaded ? 'Ready' : 'Empty');

  const canLoad = !!selectedSpool && (selectedStatus === 'Ready' || selectedStatus === 'Staged') && !isProcessing;
  const canUnload = !!selectedSpool && selectedStatus === 'In Use' && !isProcessing;
  const canRemove = !!selectedSpool && !!selectedSpool.isLoaded && selectedStatus !== 'In Use' && !isProcessing;

  return (
    <div className="w-44 flex flex-col gap-3">
      {warningMessage && (
        <div className="bg-neutral-900 border-2 border-white text-white px-3 py-3.5 rounded text-base leading-tight text-center animate-pulse">
          {warningMessage}
        </div>
      )}

      <button
        onClick={() => selectedSpool && onLoad(selectedSpool.id)}
        disabled={!canLoad}
        className="flex-1 bg-white hover:bg-neutral-200 disabled:bg-neutral-800 disabled:text-neutral-600 text-black rounded-lg flex flex-col items-center justify-center gap-2.5 transition-colors active:scale-95"
      >
        <Upload className="w-14 h-14" />
        <span className="text-base">Load</span>
      </button>

      <button
        onClick={() => selectedSpool && onUnload(selectedSpool.id)}
        disabled={!canUnload}
        className="flex-1 bg-neutral-700 hover:bg-neutral-600 disabled:bg-neutral-800 disabled:text-neutral-600 rounded-lg flex flex-col items-center justify-center gap-2.5 transition-colors active:scale-95"
      >
        <Download className="w-14 h-14" />
        <span className="text-base">Unload</span>
      </button>

      <button
        onClick={() => selectedSpool && onRemove(selectedSpool.id)}
        disabled={!canRemove}
        className="flex-1 bg-neutral-600 hover:bg-neutral-500 disabled:bg-neutral-800 disabled:text-neutral-600 rounded-lg flex flex-col items-center justify-center gap-2.5 transition-colors active:scale-95"
      >
        <XCircle className="w-14 h-14" />
        <span className="text-base">Remove</span>
        <span className="text-base">Spool</span>
      </button>
    </div>
  );
}

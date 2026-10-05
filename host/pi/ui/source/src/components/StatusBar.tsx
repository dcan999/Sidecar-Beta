import { Menu } from 'lucide-react';
import type { Spool } from '../App';

interface StatusBarProps {
  systemStatus: 'idle' | 'loading' | 'unloading' | 'feeding' | 'removing';
  activeSpool: Spool | undefined;
  spools: Spool[];
  selectedToolhead: number;
  onToolheadChange: (toolhead: number) => void;
  onMenuClick: () => void;
  demoMode?: boolean;
}

export function StatusBar({ systemStatus, activeSpool, spools, selectedToolhead, onToolheadChange, onMenuClick, demoMode }: StatusBarProps) {
  const getStatusColor = () => {
    switch (systemStatus) {
      case 'loading':
      case 'unloading':
      case 'feeding':
      case 'removing':
        return 'text-yellow-400';
      default:
        return 'text-green-400';
    }
  };

  const getStatusText = () => {
    switch (systemStatus) {
      case 'loading':
        return 'LOADING...';
      case 'unloading':
        return 'UNLOADING...';
      case 'feeding':
        return 'FEEDING...';
      case 'removing':
        return 'REMOVING...';
      default:
        return 'CONNECTED';
    }
  };

  const nextSpool = spools.find(s => s.isLoaded && !s.isActive);

  return (
    <div className="bg-neutral-900 px-4 py-2.5 flex items-center justify-between border-b border-neutral-700">
      <div className="flex items-center gap-3">
        <button className="hover:bg-neutral-800 p-2 rounded transition-colors" onClick={onMenuClick}>
          <Menu className="w-8 h-8" />
        </button>
        <select
          className="bg-neutral-800 text-white px-8 py-2 rounded border-2 border-white cursor-pointer hover:bg-neutral-700 focus:outline-none focus:ring-2 focus:ring-white text-3xl min-w-[320px] [&>option]:text-5xl [&>option]:py-6 [&>option]:px-8"
          value={selectedToolhead}
          onChange={(e) => onToolheadChange(Number(e.target.value))}
        >
          <option value={1}>Toolhead #1</option>
          <option value={2}>Toolhead #2</option>
          <option value={3}>Toolhead #3</option>
          <option value={4}>Toolhead #4</option>
        </select>
      </div>

      <div className="flex-1 flex items-center justify-center gap-6">
        {demoMode && (
          <div className="bg-orange-600 px-6 py-2 rounded text-2xl font-bold border-2 border-orange-400">
            DEMO MODE
          </div>
        )}
      </div>

      <div className={`text-4xl ${getStatusColor()}`}>
        {getStatusText()}
      </div>
    </div>
  );
}

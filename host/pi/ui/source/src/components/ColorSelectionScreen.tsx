import { X } from 'lucide-react';

interface ColorSelectionScreenProps {
  onSelect: (color: string) => void;
  onClose: () => void;
  currentColor: string;
  spoolId: number;
  toolhead: number;
}

const PRESET_COLORS = [
  '#ffffff', '#000000', '#64748b', '#94a3b8',
  '#ff0000', '#dc2626', '#991b1b', '#ef4444', '#f97316', '#ea580c',
  '#c2410c', '#ff8800', '#ffff00', '#f59e0b', '#d97706', '#eab308',
  '#00ff00', '#84cc16', '#65a30d', '#22c55e', '#16a34a', '#10b981',
  '#00ffff', '#14b8a6', '#0d9488', '#06b6d4', '#0891b2', '#0ea5e9',
  '#0284c7', '#0000ff', '#3b82f6', '#2563eb', '#6366f1', '#4f46e5',
  '#8b5cf6', '#7c3aed', '#a855f7', '#9333ea', '#d946ef', '#c026d3',
  '#ec4899', '#db2777', '#f43f5e', '#e11d48', '#ff00ff', '#ffccff',
  'linear-gradient(90deg, #ff0000, #ffff00)',
  'linear-gradient(90deg, #00ff00, #0000ff)',
  'linear-gradient(90deg, #ff00ff, #00ffff)',
  'linear-gradient(90deg, #ff0000, #ffff00, #0000ff)'
];

export function ColorSelectionScreen({ onSelect, onClose, currentColor, spoolId, toolhead }: ColorSelectionScreenProps) {
  const lane = spoolId;

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black">
      <div className="w-[1024px] h-[600px] bg-neutral-900 flex flex-col border-2 border-white">
        <div className="bg-neutral-900 px-6 py-2 border-b-2 border-white">
          <div className="flex items-center justify-between">
            <h2 className="text-2xl">Select Color</h2>
            <div className="text-base text-neutral-400">
              Lane {(toolhead - 1) * 4 + spoolId}
            </div>
            <button
              onClick={onClose}
              className="hover:bg-neutral-800 p-2 rounded transition-colors"
            >
              <X className="w-7 h-7" />
            </button>
          </div>
        </div>

        <div className="flex-1 p-3 flex items-center justify-center overflow-hidden">
          <div className="grid grid-cols-10 gap-2.5">
            {PRESET_COLORS.map(color => (
              <button
                key={color}
                onClick={() => onSelect(color)}
                className={`
                  w-[90px] h-[90px] rounded-lg transition-all
                  ${currentColor === color
                    ? 'border-4 border-white ring-4 ring-blue-400'
                    : 'border-2 border-white/30 hover:border-white'
                  }
                `}
                style={color.startsWith('linear-gradient')
                  ? { backgroundImage: color }
                  : { backgroundColor: color }
                }
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

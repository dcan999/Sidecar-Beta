import { X } from 'lucide-react';

interface MaterialSelectionScreenProps {
  onSelect: (material: string) => void;
  onClose: () => void;
  currentMaterial: string;
  spoolId: number;
  toolhead: number;
}

const MATERIAL_TYPES = [
  'PLA', 'PETG', 'ABS', 'TPU (64D+)', 'PA/PPA', 'ASA',
  'HIPS', 'PC', 'PVA'
];

export function MaterialSelectionScreen({ onSelect, onClose, currentMaterial, spoolId, toolhead }: MaterialSelectionScreenProps) {
  const lane = spoolId;

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black">
      <div className="w-[1024px] h-[600px] bg-neutral-900 flex flex-col border-2 border-white">
        <div className="bg-neutral-900 px-6 py-2 border-b-2 border-white">
          <div className="flex items-center justify-between">
            <h2 className="text-2xl">Select Material Type</h2>
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

        <div className="flex-1 p-8 overflow-y-auto">
          <div className="grid grid-cols-4 gap-4">
            {MATERIAL_TYPES.map(material => (
              <button
                key={material}
                onClick={() => onSelect(material)}
                className={`
                  px-8 py-8 rounded-lg text-3xl transition-all
                  ${currentMaterial === material
                    ? 'bg-white text-black border-2 border-white'
                    : 'bg-neutral-900 text-white border-2 border-neutral-700 hover:bg-neutral-800 hover:border-white'
                  }
                `}
              >
                {material}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

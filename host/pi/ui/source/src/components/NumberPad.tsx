import { Delete } from 'lucide-react';

interface NumberPadProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}

export function NumberPad({ value, onChange, onSubmit }: NumberPadProps) {
  const handleNumberClick = (num: string) => {
    onChange(value + num);
  };

  const handleBackspace = () => {
    onChange(value.slice(0, -1));
  };

  const handleClear = () => {
    onChange('');
  };

  const buttons = [
    '7', '8', '9',
    '4', '5', '6',
    '1', '2', '3',
    'Clear', '0', 'Del'
  ];

  return (
    <div className="w-full">
      <div className="bg-black border-2 border-white rounded-lg px-6 py-6 mb-4 text-white text-4xl text-right min-h-[80px] flex items-center justify-end">
        {value || '—'}
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4">
        {buttons.map((btn) => {
          if (btn === 'Clear') {
            return (
              <button
                key={btn}
                onClick={handleClear}
                className="bg-neutral-700 hover:bg-neutral-600 text-white px-6 py-6 rounded-lg transition-colors text-3xl border-2 border-white"
              >
                Clear
              </button>
            );
          }
          if (btn === 'Del') {
            return (
              <button
                key={btn}
                onClick={handleBackspace}
                className="bg-orange-600 hover:bg-orange-700 text-white px-6 py-6 rounded-lg transition-colors flex items-center justify-center"
              >
                <Delete size={40} />
              </button>
            );
          }
          return (
            <button
              key={btn}
              onClick={() => handleNumberClick(btn)}
              className="bg-neutral-800 hover:bg-neutral-700 text-white px-6 py-6 rounded-lg transition-colors text-4xl border-2 border-neutral-600"
            >
              {btn}
            </button>
          );
        })}
      </div>

      <button
        onClick={(e) => {
          e.stopPropagation();
          onSubmit();
        }}
        className="w-full bg-white hover:bg-neutral-200 text-black px-8 py-6 rounded-lg transition-colors text-3xl border-2 border-white"
      >
        OK
      </button>
    </div>
  );
}

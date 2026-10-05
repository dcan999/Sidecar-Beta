import { ArrowLeft, ChevronDown, ChevronUp } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { getServoMapping, moveServoToolhead, saveServoToolheadSettings } from '../lib/sidecarApi';

interface ServoAdjustmentScreenProps {
  onBack: () => void;
  demoMode?: boolean;
}

type ToolheadKey = 1 | 2 | 3 | 4;
type ServoSettingsState = Record<ToolheadKey, { close: number; open: number }>;
type SaveStatus = 'idle' | 'saving' | 'success' | 'error';

const DEFAULT_SETTINGS: ServoSettingsState = {
  1: { close: 1800, open: 1225 },
  2: { close: 1100, open: 1800 },
  3: { close: 1150, open: 1860 },
  4: { close: 1175, open: 1875 },
};

function clampUs(value: number) {
  return Math.max(500, Math.min(2500, value));
}

export function ServoAdjustmentScreen({ onBack, demoMode = false }: ServoAdjustmentScreenProps) {
  const [servoSettings, setServoSettings] = useState<ServoSettingsState>(DEFAULT_SETTINGS);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [message, setMessage] = useState('');
  const [mappedPorts, setMappedPorts] = useState<Record<ToolheadKey, number | null>>({ 1: null, 2: null, 3: null, 4: null });

  useEffect(() => {
    let alive = true;

    async function hydrate() {
      try {
        const data = await getServoMapping(2500);
        if (!alive || !data?.ok) return;

        const cfgToolheads = data?.cfg?.toolheads || {};
        setServoSettings({
          1: {
            close: clampUs(Number(cfgToolheads?.['1']?.closed_us ?? DEFAULT_SETTINGS[1].close)),
            open: clampUs(Number(cfgToolheads?.['1']?.open_us ?? DEFAULT_SETTINGS[1].open)),
          },
          2: {
            close: clampUs(Number(cfgToolheads?.['2']?.closed_us ?? DEFAULT_SETTINGS[2].close)),
            open: clampUs(Number(cfgToolheads?.['2']?.open_us ?? DEFAULT_SETTINGS[2].open)),
          },
          3: {
            close: clampUs(Number(cfgToolheads?.['3']?.closed_us ?? DEFAULT_SETTINGS[3].close)),
            open: clampUs(Number(cfgToolheads?.['3']?.open_us ?? DEFAULT_SETTINGS[3].open)),
          },
          4: {
            close: clampUs(Number(cfgToolheads?.['4']?.closed_us ?? DEFAULT_SETTINGS[4].close)),
            open: clampUs(Number(cfgToolheads?.['4']?.open_us ?? DEFAULT_SETTINGS[4].open)),
          },
        });

        const mapping: Record<ToolheadKey, number | null> = { 1: null, 2: null, 3: null, 4: null };
        const toolheadToPort = data?.mapping?.toolhead_to_port || {};
        for (const [toolheadStr, portVal] of Object.entries(toolheadToPort)) {
          const toolhead = Number(toolheadStr) as ToolheadKey;
          const port = Number(portVal);
          if ((toolhead === 1 || toolhead === 2 || toolhead === 3 || toolhead === 4) && port >= 1 && port <= 4) {
            mapping[toolhead] = port;
          }
        }
        setMappedPorts(mapping);
      } catch {
      }
    }

    void hydrate();
    return () => {
      alive = false;
    };
  }, []);

  const unmappedToolheads = useMemo(
    () => ([1, 2, 3, 4] as ToolheadKey[]).filter((toolhead) => mappedPorts[toolhead] == null),
    [mappedPorts],
  );

  const clearTransientMessage = () => {
    window.setTimeout(() => {
      setSaveStatus((prev) => (prev === 'success' || prev === 'error' ? 'idle' : prev));
      setMessage('');
    }, 2000);
  };

  const handleAdjust = async (toolhead: ToolheadKey, type: 'close' | 'open', delta: number) => {
    const nextValue = clampUs(servoSettings[toolhead][type] + delta);
    setServoSettings((prev) => ({
      ...prev,
      [toolhead]: {
        ...prev[toolhead],
        [type]: nextValue,
      },
    }));

    if (demoMode) return;

    if (mappedPorts[toolhead] == null) {
      setMessage(`Toolhead ${toolhead} is not mapped`);
      setSaveStatus('error');
      clearTransientMessage();
      return;
    }

    try {
      const res = await moveServoToolhead(toolhead, type === 'open' ? 'open' : 'close', 2500, nextValue);
      if (!res?.ok) throw new Error(res?.error || 'preview_failed');
      setMessage('');
      setSaveStatus('idle');
    } catch (err: any) {
      setMessage(`Preview failed for Toolhead ${toolhead}: ${err?.message || err}`);
      setSaveStatus('error');
      clearTransientMessage();
    }
  };

  const handleSave = async () => {
    if (demoMode) return;

    setSaveStatus('saving');
    setMessage('');
    try {
      for (const toolhead of [1, 2, 3, 4] as ToolheadKey[]) {
        const settings = servoSettings[toolhead];
        const res = await saveServoToolheadSettings(toolhead, settings.close, settings.open, 2500);
        if (!res?.ok) throw new Error(`Toolhead ${toolhead}: ${res?.error || 'save_failed'}`);
      }
      setSaveStatus('success');
      setMessage('Saved!');
      clearTransientMessage();
    } catch (err: any) {
      setSaveStatus('error');
      setMessage(err?.message || 'Failed to save servo settings');
      clearTransientMessage();
    }
  };

  return (
    <div className="w-full h-full bg-black flex flex-col overflow-hidden">
      <div className="bg-neutral-900 p-3 flex items-center justify-center border-b border-neutral-700 relative flex-shrink-0">
        <button onClick={onBack} className="absolute left-3 p-2 hover:bg-neutral-800 rounded transition-colors">
          <ArrowLeft size={28} />
        </button>

        <h1 className="text-2xl">Servo Adjustment</h1>
      </div>

      <div className="flex-1 p-3 flex flex-col min-h-0">
        {message ? (
          <div className={`mb-3 px-4 py-2 rounded text-center text-base ${saveStatus === 'error' ? 'bg-red-900 border border-red-600' : saveStatus === 'success' ? 'bg-green-900 border border-green-600' : 'bg-neutral-900 border border-neutral-700'}`}>
            {message}
          </div>
        ) : null}

        {unmappedToolheads.length > 0 ? (
          <div className="mb-3 px-4 py-2 rounded text-center text-sm bg-yellow-900 border border-yellow-600 text-yellow-100">
            Unmapped toolheads cannot preview-move until Servo Mapping is completed.
          </div>
        ) : null}

        <div className="grid grid-cols-4 gap-3 flex-1">
          {[1, 2, 3, 4].map((toolhead) => (
            <div key={toolhead} className="bg-neutral-900 rounded-lg border-2 border-white p-3 flex flex-col">
              <div className="text-lg text-center mb-2 font-bold">Toolhead {toolhead}</div>
              <div className="text-center text-xs text-neutral-400 mb-2">{mappedPorts[toolhead as ToolheadKey] ? `Mapped to Servo Port ${mappedPorts[toolhead as ToolheadKey]}` : 'Not mapped'}</div>

              <div className="flex-1 flex flex-col items-center justify-center mb-2">
                <div className="text-sm mb-1">Closed μs</div>
                <button type="button" onClick={() => void handleAdjust(toolhead as ToolheadKey, 'close', 10)} className="bg-neutral-800 hover:bg-neutral-700 p-1 rounded transition-colors mb-1">
                  <ChevronUp size={24} />
                </button>
                <div className="bg-black border-2 border-white rounded px-3 py-1.5 text-lg min-w-[110px] text-center mb-1">{servoSettings[toolhead as ToolheadKey].close}</div>
                <button type="button" onClick={() => void handleAdjust(toolhead as ToolheadKey, 'close', -10)} className="bg-neutral-800 hover:bg-neutral-700 p-1 rounded transition-colors">
                  <ChevronDown size={24} />
                </button>
              </div>

              <div className="flex-1 flex flex-col items-center justify-center">
                <div className="text-sm mb-1">Opened μs</div>
                <button type="button" onClick={() => void handleAdjust(toolhead as ToolheadKey, 'open', 10)} className="bg-neutral-800 hover:bg-neutral-700 p-1 rounded transition-colors mb-1">
                  <ChevronUp size={24} />
                </button>
                <div className="bg-black border-2 border-white rounded px-3 py-1.5 text-lg min-w-[110px] text-center mb-1">{servoSettings[toolhead as ToolheadKey].open}</div>
                <button type="button" onClick={() => void handleAdjust(toolhead as ToolheadKey, 'open', -10)} className="bg-neutral-800 hover:bg-neutral-700 p-1 rounded transition-colors">
                  <ChevronDown size={24} />
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="flex justify-center pt-3">
          <button
            onClick={() => void handleSave()}
            disabled={saveStatus === 'saving' || demoMode}
            className={`px-10 py-2 rounded-lg text-lg font-bold transition-colors ${
              saveStatus === 'success'
                ? 'bg-green-600 hover:bg-green-700'
                : saveStatus === 'error'
                ? 'bg-red-600 hover:bg-red-700'
                : saveStatus === 'saving'
                ? 'bg-neutral-700 cursor-wait'
                : demoMode
                ? 'bg-neutral-700 cursor-not-allowed'
                : 'bg-white text-black hover:bg-neutral-200'
            }`}
          >
            {demoMode
              ? 'Demo Mode'
              : saveStatus === 'saving'
              ? 'Saving...'
              : saveStatus === 'success'
              ? 'Saved!'
              : saveStatus === 'error'
              ? 'Error - Try Again'
              : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}

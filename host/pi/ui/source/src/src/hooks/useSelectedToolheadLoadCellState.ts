import { useEffect, useMemo, useState } from 'react';
import { getLoadCellStateWithFallback } from '../../lib/sidecarApi';

export function useSelectedToolheadLoadCellState(toolhead: number, pollMs = 500) {
  const [state, setState] = useState<any>(null);

  useEffect(() => {
    let alive = true;

    async function poll() {
      try {
        const data = await getLoadCellStateWithFallback(toolhead, 2500);
        if (!alive) return;
        setState(data);
      } catch {
        if (!alive) return;
        setState({ ok: false, error: 'fetch_failed' });
      }
    }

    poll();
    const timer = window.setInterval(poll, pollMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [toolhead, pollMs]);

  return useMemo(() => {
    const lanes = state?.lanes || {};
    return {
      raw: state,
      lanes: {
        1: lanes['1'] || {},
        2: lanes['2'] || {},
        3: lanes['3'] || {},
        4: lanes['4'] || {},
      },
    };
  }, [state]);
}

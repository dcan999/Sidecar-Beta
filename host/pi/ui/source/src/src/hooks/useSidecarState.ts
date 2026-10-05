import { useEffect, useState } from 'react';
import { getSidecarState } from '../../lib/sidecarApi';

export function useSidecarState(unit: number, pollMs = 500) {
  const [state, setState] = useState<any>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | null = null;

    async function poll() {
      try {
        const data = await getSidecarState(unit, 2500);
        if (!alive) return;
        setState(data);
      } catch (err) {
        if (!alive) return;
        setState({ ok: false, error: 'fetch_failed', detail: String(err) });
      } finally {
        if (alive) timer = window.setTimeout(poll, pollMs);
      }
    }

    poll();
    return () => {
      alive = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [unit, pollMs]);

  return state;
}

import { useEffect, useState } from "react";

export function useLane1SpoolGrams(pollMs = 500) {
  const [grams, setGrams] = useState<number | null>(null);

  useEffect(() => {
    const host = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'localhost'
      : window.location.hostname;
    const url = `http://${host}:7125/printer/objects/query?load_cell%20hx711_scale`;

    let alive = true;
    let hasLoggedError = false;

    async function poll() {
      try {
        const r = await fetch(url);
        const j = await r.json();
        const v = j?.result?.status?.["load_cell hx711_scale"]?.force_g;
        if (!alive) return;
        setGrams(typeof v === "number" ? v : null);
      } catch (err) {
        if (!hasLoggedError) {
          console.warn('[useLane1SpoolGrams] Could not reach Moonraker API (expected in dev environment)');
          hasLoggedError = true;
        }
        if (!alive) return;
        setGrams(null);
      }
    }

    poll();
    const t = setInterval(poll, pollMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [pollMs]);

  return grams;
}

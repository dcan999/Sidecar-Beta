export type JsonObject = Record<string, any>;

const SERVO_MAPPING_STORAGE_KEY = 'sc_servo_port_to_toolhead_v1';

export function getServoMappingStorageKey() {
  return SERVO_MAPPING_STORAGE_KEY;
}

function getSidecarApiBase() {
  const envBase = (globalThis as any)?.__APP_CONFIG__?.VITE_SC_API_BASE ?? (import.meta as any)?.env?.VITE_SC_API_BASE;
  const host = window.location.hostname;
  return (envBase && String(envBase).length ? String(envBase) : `http://${host}:8090`).replace(/\/$/, '');
}

function getMoonrakerBase() {
  return `http://${window.location.hostname}:7125`;
}

async function requestJson(path: string, init: RequestInit = {}, timeoutMs = 10000) {
  const url = path.startsWith('http') ? path : `${getSidecarApiBase()}${path.startsWith('/') ? '' : '/'}${path}`;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(init.headers || {}),
      },
    });
    const text = await res.text();
    let data: JsonObject = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { ok: false, error: 'bad_json', detail: text };
    }
    if (!res.ok) data._http = res.status;
    return data;
  } finally {
    window.clearTimeout(timer);
  }
}

async function requestMoonraker(path: string, init: RequestInit = {}, timeoutMs = 2500) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${getMoonrakerBase()}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(init.headers || {}),
      },
    });
    const text = await res.text();
    try {
      return text ? JSON.parse(text) : {};
    } catch {
      return { error: { message: 'bad_json', detail: text } };
    }
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getSidecarState(unit = 1, timeoutMs = 3000) {
  const safeUnit = Number(unit || 1);
  return requestJson(`/api/v1/state?unit=${safeUnit}`, { method: 'GET' }, timeoutMs);
}

export async function postLoad(head: number, lane: number, extra: JsonObject = {}) {
  return requestJson('/api/v1/load', {
    method: 'POST',
    body: JSON.stringify({ head, lane, ...extra }),
  }, 900000);
}

export async function postUnload(head: number, lane: number, extra: JsonObject = {}) {
  return requestJson('/api/v1/unload', {
    method: 'POST',
    body: JSON.stringify({ head, lane, ...extra }),
  }, 900000);
}

export async function postRemove(head: number, lane: number, extra: JsonObject = {}) {
  return requestJson('/api/v1/remove', {
    method: 'POST',
    body: JSON.stringify({ head, lane, ...extra }),
  }, 120000);
}

export async function moonrakerObjectQuery(objects: JsonObject, timeoutMs = 2500) {
  return requestMoonraker('/printer/objects/query', {
    method: 'POST',
    body: JSON.stringify({ objects }),
  }, timeoutMs);
}

export async function moonrakerGcode(script: string, timeoutMs = 120000) {
  return requestMoonraker('/printer/gcode/script', {
    method: 'POST',
    body: JSON.stringify({ script }),
  }, timeoutMs);
}

function valueToForceG(obj: any) {
  const force = Number(obj?.force_g);
  if (Number.isFinite(force)) return force;

  const countsPerGram = Number(obj?.counts_per_gram);
  const tareCounts = Number(obj?.tare_counts);
  const refTareCounts = Number(obj?.reference_tare_counts);
  if (Number.isFinite(countsPerGram) && countsPerGram !== 0 && Number.isFinite(tareCounts) && Number.isFinite(refTareCounts)) {
    return (tareCounts - refTareCounts) / countsPerGram;
  }

  return null;
}

export async function getAuxToolheadLoadCellState(toolhead: number, timeoutMs = 2500) {
  if (toolhead < 2 || toolhead > 4) {
    return { ok: false, error: 'bad_toolhead', detail: `toolhead=${toolhead}` };
  }

  const objects: JsonObject = {};
  const unit = String(toolhead);
  for (const lane of [1, 2, 3, 4]) {
    objects[`load_cell aux${unit}_l${lane}_scale`] = null;
  }

  const status = (await moonrakerObjectQuery(objects, timeoutMs))?.result?.status || {};
  const lanes: Record<string, { raw_g: number | null; net_g: number | null }> = {};
  for (const lane of [1, 2, 3, 4]) {
    const forceG = valueToForceG(status?.[`load_cell aux${unit}_l${lane}_scale`]);
    lanes[String(lane)] = { raw_g: forceG, net_g: forceG };
  }

  return { ok: true, lanes };
}

export async function getLoadCellState(unit = 1, timeoutMs = 2500) {
  return requestJson(`/api/v1/loadcell/state?unit=${Number(unit || 1)}`, { method: 'GET' }, timeoutMs);
}

export async function getLoadCellStateWithFallback(unit = 1, timeoutMs = 2500) {
  const data = await getLoadCellState(unit, timeoutMs);
  if (unit === 1 || (data?.ok && Number(data?.unit) === Number(unit))) {
    return data;
  }
  return getAuxToolheadLoadCellState(unit, timeoutMs);
}

export async function tareMeasureEmpty(unit: number, lane: number, timeoutMs = 6000) {
  return requestJson('/api/v1/loadcell/tare', {
    method: 'POST',
    body: JSON.stringify({ unit, lane, mode: 'measure_empty' }),
  }, timeoutMs);
}

export async function tareManualEmpty(unit: number, lane: number, emptySpoolG: number, timeoutMs = 6000) {
  return requestJson('/api/v1/loadcell/tare', {
    method: 'POST',
    body: JSON.stringify({ unit, lane, mode: 'manual_empty', empty_spool_g: emptySpoolG }),
  }, timeoutMs);
}

export async function calibrateLoadCell(unit: number, step: 'full' | 'empty', knownG: number, timeoutMs = 8000) {
  return requestJson('/api/v1/loadcell/calibrate', {
    method: 'POST',
    body: JSON.stringify({ unit, step, known_g: knownG }),
  }, timeoutMs);
}

export async function resetLoadCellCalibration(unit: number, timeoutMs = 2500) {
  return requestJson('/api/v1/loadcell/calibrate/reset', {
    method: 'POST',
    body: JSON.stringify({ unit }),
  }, timeoutMs);
}

export async function getServoMapping(timeoutMs = 2500) {
  return requestJson('/api/v1/servo/mapping', { method: 'GET' }, timeoutMs);
}

export async function setServoMapping(toolhead: number, port: number, timeoutMs = 2500) {
  return requestJson('/api/v1/servo/mapping', {
    method: 'POST',
    body: JSON.stringify({ toolhead, port }),
  }, timeoutMs);
}

export async function resetServoMapping(timeoutMs = 2500) {
  return requestJson('/api/v1/servo/mapping/reset', { method: 'POST' }, timeoutMs);
}

export async function startServoIdentify(port: number, opts: JsonObject = {}, timeoutMs = 2500) {
  return requestJson('/api/v1/servo/identify/start', {
    method: 'POST',
    body: JSON.stringify({ port, ...opts }),
  }, timeoutMs);
}

export async function stopServoIdentify(timeoutMs = 2500) {
  return requestJson('/api/v1/servo/identify/stop', { method: 'POST' }, timeoutMs);
}

export async function moveServoToolhead(toolhead: number, action: 'open' | 'close', timeoutMs = 2500, us?: number) {
  return requestJson('/api/v1/servo/toolhead/move', {
    method: 'POST',
    body: JSON.stringify(us == null ? { toolhead, action } : { toolhead, action, us }),
  }, timeoutMs);
}

export async function saveServoToolheadSettings(toolhead: number, closedUs: number, openUs: number, timeoutMs = 2500) {
  return requestJson('/api/v1/servo/toolhead/settings', {
    method: 'POST',
    body: JSON.stringify({ toolhead, closed_us: closedUs, open_us: openUs }),
  }, timeoutMs);
}

function laneMetaPath(toolhead?: number | null, lane?: number | null) {
  const qs: string[] = [];
  if (toolhead != null) qs.push(`toolhead=${encodeURIComponent(String(toolhead))}`);
  if (lane != null) qs.push(`lane=${encodeURIComponent(String(lane))}`);
  return qs.length ? `/api/v1/lane-meta?${qs.join('&')}` : '/api/v1/lane-meta';
}

export async function getLaneMeta(toolhead?: number | null, lane?: number | null, timeoutMs = 2500) {
  return requestJson(laneMetaPath(toolhead, lane), { method: 'GET' }, timeoutMs);
}

export async function setLaneMeta(toolhead: number, lane: number, patch: { color?: string; material?: string }, timeoutMs = 4000) {
  return requestJson('/api/v1/lane-meta', {
    method: 'POST',
    body: JSON.stringify({ toolhead, lane, ...patch }),
  }, timeoutMs);
}

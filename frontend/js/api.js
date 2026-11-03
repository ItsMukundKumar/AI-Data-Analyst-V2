/* api.js: ALL network + session-storage code lives here. UI files never call fetch directly. */
const API_BASE = localStorage.getItem('ada_api_base') || 'http://127.0.0.1:8000';
const SESSION_KEY = 'ada_session';
const HISTORY_KEY = 'ada_history';

/** Low-level JSON request with friendly errors (FastAPI errors arrive as {"detail": ...}). */
async function request(path, { method = 'GET', body } = {}) {
    let res;
    try {
        res = await fetch(`${API_BASE}/api/v1${path}`, {
            method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
            body: body ? JSON.stringify(body) : undefined
        });
    } catch {
        throw new Error('Cannot reach the backend at ' + API_BASE + '. Is FastAPI running (and CORS enabled)?');
    }
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        let msg = data.detail;
        if (Array.isArray(msg)) msg = msg.map(e => e.msg).join('; ');
        const err = new Error(typeof msg === 'string' ? msg : `Request failed (${res.status}).`);
        err.status = res.status; throw err;
    }
    return res;
}
const json = async (path, opts) => (await request(path, opts)).json();

const Api = {
    /** POST /api/v1/upload as multipart/form-data (field name: "file"). Returns normalized metadata. */
    async uploadDataset(file) {
        const form = new FormData();
        form.append('file', file); // don't set Content-Type: the browser adds the multipart boundary
        let res;
        try {
            res = await fetch(`${API_BASE}/api/v1/upload`, { method: 'POST', body: form });
        } catch {
            throw new Error('Cannot reach the backend at ' + API_BASE + '. Is FastAPI running (and CORS enabled)?');
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.success === false) {
            throw new Error(typeof data.detail === 'string' ? data.detail : data.message || `Upload failed (${res.status}).`);
        }
        if (!data.dataset_id) throw new Error('Backend response did not include a dataset_id.');
        return {
            dataset_id: data.dataset_id,
            filename: data.filename ?? file.name,
            file_type: data.file_type ?? null,
            file_size: data.file_size ?? null,
            rows: data.rows ?? null,
            columns: data.columns ?? null,
            column_info: Array.isArray(data.column_info) ? data.column_info : null
        };
    },
    profile: (id) => json(`/analytics/${id}/profile`),
    stats: (id, filters) => json(`/analytics/${id}/stats`, { method: 'POST', body: { filters } }),
    recommendations: (id, filters) => json(`/analytics/${id}/recommendations`, { method: 'POST', body: { filters } }),
    chart: (id, config, filters) => json(`/analytics/${id}/chart`, { method: 'POST', body: { config, filters } }),
    insights: (id, filters) => json(`/analytics/${id}/insights`, { method: 'POST', body: { filters } }),
    explorer: (id, q) => json(`/analytics/${id}/explorer`, { method: 'POST', body: q }),
    cleanPreview: (id, opts) => json(`/analytics/${id}/clean/preview`, { method: 'POST', body: opts }),
    async cleanDownload(id, opts) { return (await request(`/analytics/${id}/clean/download`, { method: 'POST', body: opts })).blob(); },
    recent: () => json('/analytics/datasets'),
    chat: (id, question, filters) => json('/chat', { method: 'POST', body: { dataset_id: id, question, filters } }),
    async health() { const r = await fetch(`${API_BASE}/health`); if (!r.ok) throw new Error('unhealthy'); return r.json(); }
};

/** Session state persisted in localStorage so a refresh restores the workspace. */
const Session = {
    save(meta) { localStorage.setItem(SESSION_KEY, JSON.stringify(meta)); Session.remember(meta); },
    load() { try { return JSON.parse(localStorage.getItem(SESSION_KEY)); } catch { return null; } },
    clear: () => localStorage.removeItem(SESSION_KEY),
    history() { try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch { return []; } },
    remember(meta) {
        const h = Session.history().filter(x => x.dataset_id !== meta.dataset_id);
        h.unshift({ ...meta, opened_at: Date.now() });
        localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 20)));
    },
    forget(id) { localStorage.setItem(HISTORY_KEY, JSON.stringify(Session.history().filter(x => x.dataset_id !== id))); }
};

/** Per-dataset dashboard filters + pinned charts, shared between Dashboard and AI Chat. */
const Store = {
    _get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    filters: (id) => Store._get('ada_filters_' + id, []),
    setFilters: (id, f) => localStorage.setItem('ada_filters_' + id, JSON.stringify(f)),
    pins: (id) => Store._get('ada_pins_' + id, []),
    addPin(id, pin) {
        const p = Store.pins(id), key = JSON.stringify(pin.config);
        if (p.some(x => JSON.stringify(x.config) === key)) return false;
        p.push(pin); localStorage.setItem('ada_pins_' + id, JSON.stringify(p)); return true;
    },
    removePin(id, i) { const p = Store.pins(id); p.splice(i, 1); localStorage.setItem('ada_pins_' + id, JSON.stringify(p)); },
    clearAll() { Object.keys(localStorage).filter(k => k.startsWith('ada_')).forEach(k => k !== 'ada_api_base' && localStorage.removeItem(k)); }
};

/** Small shared formatters */
const Fmt = {
    bytes(n) { if (n == null) return '—'; const u = ['B', 'KB', 'MB', 'GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${u[i]}`; },
    num: (n) => (n == null ? '—' : Number(n).toLocaleString())
};

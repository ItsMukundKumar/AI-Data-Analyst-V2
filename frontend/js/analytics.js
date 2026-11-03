/* analytics.js: Analytics Dashboard page. Hash-routed views: overview, dashboard, explorer, insights, cleaning, recent, settings.
   All numbers/charts come from the FastAPI endpoints; nothing here is sample data. */
(() => {
    const { h, icon } = UI;
    const $ = (id) => document.getElementById(id);
    const NO_DATASET_VIEWS = ['recent', 'settings'];
    const FILTER_VIEWS = ['overview', 'dashboard', 'explorer', 'insights', 'cleaning'];
    const TITLES = { overview: 'Overview', dashboard: 'Analytics Dashboard', explorer: 'Data Explorer', insights: 'AI Insights', cleaning: 'Data Cleaning', recent: 'Recent Datasets', settings: 'Settings' };

    let session = Session.load();
    const currentView = () => { const v = (location.hash || '#overview').slice(1); return TITLES[v] ? v : 'overview'; };
    if (!session && !NO_DATASET_VIEWS.includes(currentView())) { location.replace('index.html'); return; }

    const state = { profile: null, filters: session ? Store.filters(session.dataset_id) : [], token: 0, cache: {} };
    const id = () => session.dataset_id;
    const kindOf = (c) => (state.profile.columns.find(x => x.name === c) || {}).kind;
    const colsOf = (...k) => state.profile.columns.filter(c => k.includes(c.kind)).map(c => c.name);

    // ------------------------------------------------------------------ data access (cached per filter set)
    const fkey = () => JSON.stringify(state.filters);
    function cached(name, loader) {
        const k = name + fkey();
        if (!state.cache[k]) state.cache[k] = loader().catch(e => { delete state.cache[k]; throw e; });
        return state.cache[k];
    }
    const getStats = () => cached('stats', () => Api.stats(id(), state.filters));
    const getRecs = () => cached('recs', () => Api.recommendations(id(), state.filters));
    const getInsights = () => cached('ins', () => Api.insights(id(), state.filters));

    // ------------------------------------------------------------------ header
    function renderHeader(view) {
        $('a-title').textContent = TITLES[view];
        const chips = $('a-chips'); chips.replaceChildren();
        const acts = $('a-actions'); acts.replaceChildren();
        if (session) {
            chips.append(h('span', { class: 'chip accent' }, session.filename || 'Dataset'),
                h('span', { class: 'chip' }, (session.file_type || '').toUpperCase() || '—'),
                h('span', { class: 'chip' }, Fmt.num(session.rows) + ' rows'),
                h('span', { class: 'chip' }, Fmt.num(session.columns) + ' columns'));
            if (FILTER_VIEWS.includes(view)) {
                const n = state.filters.length;
                acts.append(
                    h('button', { class: 'btn sm', onclick: () => { state.cache = {}; render(); UI.toast('Refreshed from the server.'); } }, icon('refresh-cw', 14), 'Refresh'),
                    h('button', { class: 'btn sm', onclick: () => { const fh = $('filter-host'); fh.classList.toggle('hidden'); } }, icon('filter', 14), n ? `Filters (${n})` : 'Filters'),
                    h('a', { class: 'btn sm btn-primary', href: 'dashboard.html' }, icon('message-square', 14), 'Ask AI'));
            }
        }
        UI.refreshIcons();
    }

    // ------------------------------------------------------------------ filters
    function buildFilterBar() {
        const host = $('filter-host'); host.replaceChildren();
        if (!state.profile) return;
        const bar = h('div', { class: 'filter-bar' });
        const row = h('div', { class: 'row' });
        const apply = UI.debounce(() => {
            Store.setFilters(id(), state.filters); state.cache = {};
            renderHeader(currentView()); render(true);
        }, 400);

        const filterable = state.profile.columns.filter(c =>
            c.kind === 'numeric' || c.kind === 'datetime' || ((c.kind === 'categorical' || c.kind === 'boolean') && c.categories && c.categories.length));
        const add = h('select', { 'aria-label': 'Add filter' }, h('option', { value: '' }, '+ Add filter…'),
            ...filterable.map(c => h('option', { value: c.name }, `${c.name} (${c.kind})`)));
        add.addEventListener('change', () => {
            const c = state.profile.columns.find(x => x.name === add.value); add.value = '';
            if (!c || state.filters.some(f => f.column === c.name)) return;
            state.filters.push(c.kind === 'numeric' ? { column: c.name, op: 'range' } : c.kind === 'datetime' ? { column: c.name, op: 'date_range' } : { column: c.name, op: 'in', values: [] });
            drawCards(); // new filter has no restriction until the user sets a value
        });

        const cards = h('div', { class: 'row', style: 'display:contents' });
        function drawCards() {
            cards.replaceChildren();
            state.filters.forEach((f, i) => {
                const c = state.profile.columns.find(x => x.name === f.column);
                let body;
                if (f.op === 'range') {
                    const mk = (key, ph) => h('input', {
                        type: 'number', placeholder: ph, step: 'any', value: f[key] ?? '',
                        onchange: e => {
                            const v = e.target.value === '' ? undefined : Number(e.target.value);
                            const next = { ...f, [key]: v };
                            if (next.min != null && next.max != null && next.min > next.max) return UI.toast('Min cannot be greater than max.', 'error');
                            if (v === undefined) delete f[key]; else f[key] = v; apply();
                        }
                    });
                    body = h('div', { class: 'f-body' }, mk('min', String(c.min)), '–', mk('max', String(c.max)));
                } else if (f.op === 'date_range') {
                    const mk = (key, ph) => h('input', {
                        type: 'date', value: f[key] || '', min: (c.min || '').slice(0, 10), max: (c.max || '').slice(0, 10), 'aria-label': ph,
                        onchange: e => {
                            const next = { ...f, [key]: e.target.value || undefined };
                            if (next.start && next.end && next.start > next.end) return UI.toast('Start date is after end date.', 'error');
                            if (e.target.value) f[key] = e.target.value; else delete f[key]; apply();
                        }
                    });
                    body = h('div', { class: 'f-body' }, mk('start', 'From'), '–', mk('end', 'To'));
                } else {
                    const list = h('div', { class: 'cat-list' }, ...c.categories.map(cat => h('label', {},
                        h('input', {
                            type: 'checkbox', checked: f.values.includes(cat.value), onchange: e => {
                                f.values = e.target.checked ? [...f.values, cat.value] : f.values.filter(v => v !== cat.value); apply();
                            }
                        }), `${cat.value} `, h('small', { class: 'muted' }, `(${cat.count})`))));
                    body = list;
                }
                cards.append(h('div', { class: 'f-card' },
                    h('div', { class: 'f-head' }, h('strong', {}, f.column), h('button', { class: 'icon-btn', 'aria-label': 'Remove filter', onclick: () => { state.filters.splice(i, 1); drawCards(); apply(); } }, icon('x', 14))), body));
            });
            if (state.filters.length) cards.append(h('button', { class: 'btn sm ghost', onclick: () => { state.filters = []; drawCards(); apply(); } }, 'Reset all'));
            UI.refreshIcons();
        }
        row.append(add, cards); bar.append(row); host.append(bar); drawCards();
        host.classList.toggle('hidden', !state.filters.length && currentView() !== 'dashboard');
    }

    // ------------------------------------------------------------------ KPI cards
    function kpiCards(k) {
        const filtered = k.rows !== k.total_rows;
        const defs = [
            ['Total Rows', Fmt.num(k.rows), filtered ? `of ${Fmt.num(k.total_rows)} (filtered)` : 'records', 'rows-3'],
            ['Total Columns', Fmt.num(k.columns), 'fields', 'columns-3'],
            ['Missing Values', Fmt.num(k.missing_values), `${k.missing_pct}% of cells`, 'circle-help', k.missing_values > 0],
            ['Duplicate Rows', Fmt.num(k.duplicate_rows), k.rows ? `${(k.duplicate_rows / k.rows * 100).toFixed(1)}% of rows` : '', 'copy', k.duplicate_rows > 0],
            ['Numerical Columns', Fmt.num(k.numeric_columns), 'measures', 'hash'],
            ['Categorical Columns', Fmt.num(k.categorical_columns), 'categories / text', 'tags'],
            ['Memory Usage', Fmt.bytes(k.memory_bytes), 'in memory (pandas)', 'cpu'],
        ];
        return h('div', { class: 'kpis' }, ...defs.map(([l, v, s, ic, warn]) =>
            h('div', { class: 'card kpi' + (warn ? ' warn' : '') }, h('div', { class: 'lbl' }, icon(ic, 14), l), h('div', { class: 'val' }, v), h('div', { class: 'sub' }, s))));
    }
    function kpiSection(host, token) {
        host.replaceChildren(h('div', { class: 'kpis' }, ...Array(7).fill(0).map(() => h('div', { class: 'skeleton', style: 'height:92px' }))));
        getStats().then(r => { if (token === state.token) { host.replaceChildren(kpiCards(r.kpis)); UI.refreshIcons(); } })
            .catch(e => token === state.token && host.replaceChildren(UI.error(e.message, () => { state.cache = {}; render(); })));
    }

    // ------------------------------------------------------------------ chart helpers
    const chartCard = (c, extra = {}) => Charts.card({ title: c.title, subtitle: c.why, figure: c.figure, notes: c.notes || [], ...extra });
    const pinAction = (c) => ({
        icon: 'pin', label: 'Pin to dashboard', onClick: () => {
            if (!c.config) return UI.toast('This chart is computed automatically and is already on the dashboard.');
            UI.toast(Store.addPin(id(), { title: c.title, config: c.config }) ? 'Pinned to your dashboard.' : 'Already pinned.', 'success');
        }
    });

    // ------------------------------------------------------------------ views
    const SECTIONS = [
        ['numerical', 'Numerical Analysis', 'Histograms, box plots and distributions'],
        ['categorical', 'Categorical Analysis', 'Category frequencies and shares'],
        ['relationships', 'Relationship Analysis', 'Correlations and scatter plots'],
        ['timeseries', 'Time-Series Analysis', 'Trends across dates'],
        ['quality', 'Data Quality', 'Missing values, duplicates and column types'],
    ];

    function columnsTable() {
        const rows = state.profile.columns;
        const detail = (c) => c.kind === 'numeric' ? `${c.min} – ${c.max} (mean ${c.mean})` : c.kind === 'datetime' ? `${(c.min || '').slice(0, 10)} → ${(c.max || '').slice(0, 10)}`
            : c.categories ? c.categories.slice(0, 3).map(x => x.value).join(', ') + (c.unique > 3 ? '…' : '') : (c.sample || []).join(', ');
        return h('div', { class: 'table-wrap' }, h('table', { class: 't' },
            h('thead', {}, h('tr', {}, ...['Column', 'Type', 'Non-null', 'Missing', 'Unique', 'Summary'].map(t => h('th', {}, t)))),
            h('tbody', {}, ...rows.map(c => h('tr', {}, h('td', {}, c.name), h('td', {}, h('span', { class: 'kind ' + c.kind }, c.kind)),
                h('td', {}, Fmt.num(c.non_null)), h('td', {}, c.missing ? `${Fmt.num(c.missing)} (${c.missing_pct}%)` : '0'), h('td', {}, Fmt.num(c.unique)), h('td', {}, detail(c)))))));
    }

    function insightCards(list) {
        return h('div', { class: 'insights' }, ...list.map(i => h('div', { class: 'card insight ' + i.level }, h('h4', {}, i.title), h('p', {}, i.text))));
    }

    function viewOverview(root, token) {
        const kpiHost = h('div'); root.append(kpiHost); kpiSection(kpiHost, token);
        const colSec = h('section', { class: 'section' }, h('div', { class: 'sec-head' }, h('h2', {}, 'Dataset overview'), h('span', { class: 'sec-sub' }, 'Column types and profile (full dataset, unfiltered)')), columnsTable());
        const qHost = h('div', { class: 'grid' }, UI.loading());
        const iHost = h('div', {}, UI.loading());
        root.append(colSec,
            h('section', { class: 'section' }, h('div', { class: 'sec-head' }, h('h2', {}, 'Data quality')), qHost),
            h('section', { class: 'section' }, h('div', { class: 'sec-head' }, h('h2', {}, 'Highlights'), h('a', { class: 'sec-sub', href: '#insights' }, 'All insights →')), iHost),
            h('section', { class: 'section' }, h('div', { class: 'sec-head' }, h('h2', {}, 'Where next?')), h('div', { class: 'cols2' },
                ...[['bar-chart-3', 'Analytics Dashboard', 'Auto-generated charts and a custom chart builder.', '#dashboard'], ['message-square', 'AI Chat', 'Ask questions and get computed answers with charts.', 'dashboard.html'],
                ['table-2', 'Data Explorer', 'Browse, search and sort the raw rows.', '#explorer'], ['sparkles', 'Data Cleaning', 'Preview fixes and download a cleaned CSV.', '#cleaning']]
                    .map(([ic, t, d, href]) => h('a', { class: 'card', href }, h('div', { class: 'lbl muted', style: 'display:flex;gap:8px;align-items:center' }, icon(ic, 16), h('strong', { style: 'color:var(--text)' }, t)), h('p', { class: 'muted', style: 'margin-top:6px;font-size:13px' }, d))))));
        getRecs().then(r => { if (token !== state.token) return; qHost.replaceChildren(...r.charts.filter(c => c.section === 'quality').map(c => chartCard(c, { height: 300 })));
            if (!qHost.children.length) qHost.replaceChildren(UI.empty('No rows to analyze.')); }).catch(e => qHost.replaceChildren(UI.error(e.message)));
        getInsights().then(r => { if (token === state.token) iHost.replaceChildren(insightCards(r.insights.slice(0, 4))); }).catch(e => iHost.replaceChildren(UI.error(e.message)));
    }

    function viewDashboard(root, token) {
        const kpiHost = h('div'); root.append(kpiHost); kpiSection(kpiHost, token);
        const pillHost = h('div', { class: 'pills' });
        const pinHost = h('section', { class: 'section', id: 'pinned' });
        const autoHost = h('div', {}, h('div', { class: 'grid' }, ...Array(4).fill(0).map(() => h('div', { class: 'skeleton' }))));
        const builderHost = h('section', { class: 'section', id: 'builder' });
        const aiHost = h('section', { class: 'section', id: 'ai-insights' });
        root.append(pillHost, pinHost, autoHost, builderHost, aiHost);

        drawPins(pinHost, token);
        drawBuilder(builderHost);
        aiHost.append(h('div', { class: 'sec-head' }, h('h2', {}, 'AI Insights'), h('a', { class: 'sec-sub', href: '#insights' }, 'View all →')), UI.loading());
        getInsights().then(r => { if (token !== state.token) return; aiHost.replaceChildren(h('div', { class: 'sec-head' }, h('h2', {}, 'AI Insights'), h('a', { class: 'sec-sub', href: '#insights' }, 'View all →')), insightCards(r.insights.slice(0, 6))); })
            .catch(e => aiHost.replaceChildren(UI.error(e.message)));

        getRecs().then(r => {
            if (token !== state.token) return;
            autoHost.replaceChildren();
            if (!r.charts.length) return autoHost.append(UI.empty(r.message || 'No charts could be generated for the current filters.'));
            const present = SECTIONS.filter(([k]) => r.charts.some(c => c.section === k));
            pillHost.append(...present.map(([k, t]) => h('a', { class: 'pill', href: 'javascript:void(0)', onclick: () => document.getElementById('sec-' + k)?.scrollIntoView({ behavior: 'smooth' }) }, t)),
                h('a', { class: 'pill', href: 'javascript:void(0)', onclick: () => $('builder').scrollIntoView({ behavior: 'smooth' }) }, 'Chart Builder'));
            for (const [k, title, sub] of present) {
                autoHost.append(h('section', { class: 'section', id: 'sec-' + k }, h('div', { class: 'sec-head' }, h('h2', {}, title), h('span', { class: 'sec-sub' }, sub)),
                    h('div', { class: 'grid' }, ...r.charts.filter(c => c.section === k).map(c => chartCard(c, { actions: c.config ? [pinAction(c)] : [] })))));
            }
            UI.refreshIcons();
        }).catch(e => { autoHost.replaceChildren(UI.error(e.message, () => { state.cache = {}; render(); })); });
    }

    function drawPins(host, token) {
        host.replaceChildren();
        const pins = Store.pins(id());
        if (!pins.length) return;
        host.append(h('div', { class: 'sec-head' }, h('h2', {}, 'Pinned charts'), h('span', { class: 'sec-sub' }, 'Added from AI Chat or the Chart Builder · they follow your filters')));
        const grid = h('div', { class: 'grid' }); host.append(grid);
        pins.forEach((p, i) => {
            const slot = h('div', { class: 'card chart-card' }, h('header', {}, h('h3', {}, p.title)), UI.loading());
            grid.append(slot);
            Api.chart(id(), p.config, state.filters).then(r => {
                if (token !== state.token) return;
                if (r.empty) return slot.replaceChildren(h('header', {}, h('h3', {}, p.title), h('button', { class: 'icon-btn', onclick: () => { Store.removePin(id(), i); drawPins(host, token); } }, icon('x', 14))), UI.empty(r.message));
                slot.replaceWith(Charts.card({ title: p.title, figure: r.figure, notes: r.notes, actions: [{ icon: 'x', label: 'Remove from dashboard', onClick: () => { Store.removePin(id(), i); drawPins(host, token); } }] }));
            }).catch(e => slot.replaceChildren(h('header', {}, h('h3', {}, p.title), h('button', { class: 'icon-btn', onclick: () => { Store.removePin(id(), i); drawPins(host, token); } }, icon('x', 14))), UI.error(e.message)));
        });
        UI.refreshIcons();
    }

    // ------------------------------------------------------------------ custom chart builder
    const CHART_FIELDS = {   // which controls each chart type uses
        bar: { x: 'X-axis (category)', y: 'Y-axis (value)', agg: 1, color: 1, top: 1 },
        line: { x: 'X-axis (date / order)', y: 'Y-axis (value)', agg: 1, color: 1, grain: 1 },
        scatter: { x: 'X-axis (numeric)', y: 'Y-axis (numeric)', color: 1 },
        pie: { x: 'Category', y: 'Value (optional)', agg: 1, top: 1 },
        donut: { x: 'Category', y: 'Value (optional)', agg: 1, top: 1 },
        histogram: { x: 'Numeric column', color: 1, bins: 1 },
        box: { y: 'Numeric column', x: 'Group by (optional)' },
        heatmap: { x: 'X (optional)', y: 'Y (optional)', value: 1, agg: 1 },
    };
    function optionsFor(type, field) {
        const num = colsOf('numeric'), grp = colsOf('categorical', 'boolean'), dt = colsOf('datetime');
        const any = state.profile.columns.filter(c => !['constant', 'identifier'].includes(c.kind) && !(c.kind === 'text')).map(c => c.name);
        if (type === 'scatter') return num;
        if (type === 'histogram') return field === 'x' ? num : [];
        if (type === 'box') return field === 'y' ? num : [...grp, ...num];
        if (field === 'color') return [...grp, ...(type === 'scatter' ? num : [])];
        if (field === 'value') return num;
        if (field === 'y') return [...num, ...grp];
        if (type === 'line') return [...dt, ...num, ...grp];
        if (type === 'heatmap') return any;
        if (type === 'pie' || type === 'donut') return [...grp, ...colsOf('text')];
        return [...grp, ...dt, ...num, ...colsOf('text')];
    }

    function drawBuilder(host) {
        host.replaceChildren(h('div', { class: 'sec-head' }, h('h2', {}, 'Custom Chart Builder'), h('span', { class: 'sec-sub' }, 'Pick a chart type and columns - the chart updates automatically and respects the filters above')));
        const cfg = JSON.parse(sessionStorage.getItem('ada_builder_' + id()) || 'null') || { chart_type: 'bar', agg: 'count', bins: 20, top_n: 15 };
        const out = h('div', { class: 'builder-out' });
        const controls = h('div', { class: 'card controls' });
        const sel = (key, label, opts, optional = true) => {
            const s = h('select', { 'aria-label': label }, optional ? h('option', { value: '' }, '— none —') : null, ...opts.map(o => h('option', { value: o.value ?? o, selected: (cfg[key] || '') === (o.value ?? o) }, o.label ?? o)));
            s.addEventListener('change', () => { cfg[key] = s.value || null; if (key === 'chart_type') { reset(); } schedule(); persist(); });
            return h('label', { 'data-field': key }, label, s);
        };
        const num = (key, label, min, max) => h('label', { 'data-field': key }, label, h('input', { type: 'number', min, max, value: cfg[key] ?? '', onchange: e => { cfg[key] = Number(e.target.value) || undefined; schedule(); persist(); } }));
        const persist = () => sessionStorage.setItem('ada_builder_' + id(), JSON.stringify(cfg));
        const AGG = ['count', 'sum', 'mean', 'median', 'min', 'max', 'nunique'].map(a => ({ value: a, label: { count: 'Count', sum: 'Sum', mean: 'Average', median: 'Median', min: 'Minimum', max: 'Maximum', nunique: 'Unique count' }[a] }));

        function reset() { // drop selections that are no longer valid for the new chart type
            for (const f of ['x', 'y', 'color', 'value']) if (cfg[f] && !optionsFor(cfg.chart_type, f).includes(cfg[f])) cfg[f] = null;
            const f = CHART_FIELDS[cfg.chart_type];
            if (!cfg.x && f.x && !['heatmap'].includes(cfg.chart_type)) cfg.x = optionsFor(cfg.chart_type, 'x')[0] || null;
            if (cfg.chart_type === 'scatter' && !cfg.y) cfg.y = optionsFor('scatter', 'y').find(c => c !== cfg.x) || null;
            if (cfg.chart_type === 'box' && !cfg.y) cfg.y = optionsFor('box', 'y')[0] || null;
            if (cfg.chart_type === 'box' && cfg.x && cfg.x === cfg.y) cfg.x = null;
            if (cfg.chart_type === 'histogram' && !cfg.x) cfg.x = optionsFor('histogram', 'x')[0] || null;
            if (!['bar', 'line', 'pie', 'donut', 'heatmap'].includes(cfg.chart_type)) cfg.agg = 'count';
            buildControls();
        }
        function buildControls() {
            const f = CHART_FIELDS[cfg.chart_type];
            controls.replaceChildren(...[
                sel('chart_type', 'Chart type', Object.keys(CHART_FIELDS).map(t => ({ value: t, label: t === 'box' ? 'Box plot' : t[0].toUpperCase() + t.slice(1) })), false),
                f.x ? sel('x', f.x, optionsFor(cfg.chart_type, 'x'), !['bar', 'pie', 'donut', 'line', 'histogram', 'scatter'].includes(cfg.chart_type)) : null,
                f.y ? sel('y', f.y, optionsFor(cfg.chart_type, 'y'), cfg.chart_type !== 'scatter' && cfg.chart_type !== 'box') : null,
                f.value ? sel('value', 'Value column', optionsFor(cfg.chart_type, 'value')) : null,
                f.agg ? sel('agg', 'Aggregation', AGG, false) : null,
                f.color ? sel('color', 'Colour / group by', optionsFor(cfg.chart_type, 'color')) : null,
                f.grain ? sel('time_grain', 'Time grouping', [{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }, { value: 'quarter', label: 'Quarter' }, { value: 'year', label: 'Year' }]) : null,
                f.bins ? num('bins', 'Bins', 2, 200) : null, f.top ? num('top_n', 'Show top N', 1, 100) : null,
                cfg.chart_type === 'heatmap' ? h('p', { class: 'hint' }, 'Leave X and Y empty for a correlation heatmap of numeric columns.') : null,
                h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
                    h('button', { class: 'btn sm btn-primary', onclick: pin }, icon('pin', 14), 'Pin to dashboard'),
                    h('button', { class: 'btn sm', onclick: () => { Object.assign(cfg, { x: null, y: null, color: null, value: null, agg: 'count', time_grain: null }); reset(); schedule(); persist(); } }, 'Reset'))].filter(Boolean));
            UI.refreshIcons();
        }
        let seq = 0;
        async function run() {
            const my = ++seq; out.replaceChildren(UI.loading('Building chart…'));
            const body = { chart_type: cfg.chart_type, x: cfg.x || null, y: cfg.y || null, color: cfg.color || null, value: cfg.value || null, agg: cfg.agg || 'count', bins: cfg.bins || 20, top_n: cfg.top_n || 15, time_grain: cfg.time_grain || null };
            try {
                const r = await Api.chart(id(), body, state.filters);
                if (my !== seq) return;
                if (r.empty) return out.replaceChildren(UI.empty(r.message));
                out.replaceChildren(Charts.card({ title: r.figure.layout.title.text, figure: r.figure, notes: r.notes, height: 420 }));
            } catch (e) { if (my === seq) out.replaceChildren(UI.error(e.message)); }
        }
        const schedule = UI.debounce(run, 250);
        function pin() {
            const t = out.querySelector('h3')?.textContent;
            if (!t) return UI.toast('Build a valid chart first.', 'error');
            const config = { chart_type: cfg.chart_type, x: cfg.x || null, y: cfg.y || null, color: cfg.color || null, value: cfg.value || null, agg: cfg.agg || 'count', bins: cfg.bins || 20, top_n: cfg.top_n || 15, time_grain: cfg.time_grain || null };
            UI.toast(Store.addPin(id(), { title: t, config }) ? 'Pinned. It appears under "Pinned charts" at the top.' : 'Already pinned.', 'success');
            drawPins($('pinned'), state.token);
        }
        // first-time defaults come from real columns
        if (!cfg.x && !cfg.y) { cfg.chart_type = 'bar'; cfg.x = colsOf('categorical', 'boolean')[0] || colsOf('numeric')[0] || null; }
        host.append(h('div', { class: 'builder' }, controls, out)); buildControls(); run();
    }

    // ------------------------------------------------------------------ explorer
    function viewExplorer(root, token) {
        const q = { page: 1, page_size: 25, sort_by: null, sort_dir: 'asc', search: '' };
        const tableHost = h('div', {}, UI.loading());
        const search = h('input', { type: 'search', placeholder: 'Search all columns…', 'aria-label': 'Search rows', oninput: UI.debounce(e => { q.search = e.target.value; q.page = 1; load(); }, 400) });
        const size = h('select', { 'aria-label': 'Rows per page', onchange: e => { q.page_size = Number(e.target.value); q.page = 1; load(); } }, ...[25, 50, 100].map(n => h('option', { value: n }, n + ' / page')));
        root.append(h('div', { class: 'toolbar' }, search, size), tableHost);
        async function load() {
            try {
                const r = await Api.explorer(id(), { ...q, search: q.search || null, filters: state.filters });
                if (token !== state.token) return;
                const pages = Math.max(1, Math.ceil(r.total / r.page_size));
                tableHost.replaceChildren(
                    h('div', { class: 'table-wrap', style: 'max-height:65vh' }, h('table', { class: 't' },
                        h('thead', {}, h('tr', {}, ...r.columns.map(c => h('th', { class: 'sortable', title: 'Click to sort', onclick: () => { q.sort_dir = q.sort_by === c.name && q.sort_dir === 'asc' ? 'desc' : 'asc'; q.sort_by = c.name; load(); } },
                            c.name + (q.sort_by === c.name ? (q.sort_dir === 'asc' ? ' ▲' : ' ▼') : ''), ' ', h('span', { class: 'kind ' + c.kind }, c.kind))))),
                        h('tbody', {}, ...r.rows.map(row => h('tr', {}, ...row.map(v => v == null ? h('td', { class: 'null' }, 'null') : h('td', { title: String(v) }, typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(v)))))))),
                    r.total === 0 ? UI.empty('No rows match your search or filters.') : null,
                    h('div', { class: 'pager' }, `${Fmt.num(r.total)} rows`,
                        h('button', { class: 'btn sm', disabled: q.page <= 1, onclick: () => { q.page--; load(); } }, 'Previous'), `Page ${q.page} of ${pages}`,
                        h('button', { class: 'btn sm', disabled: q.page >= pages, onclick: () => { q.page++; load(); } }, 'Next')));
            } catch (e) { tableHost.replaceChildren(UI.error(e.message, load)); }
        }
        load();
    }

    // ------------------------------------------------------------------ insights
    function viewInsights(root, token) {
        const host = h('div', {}, UI.loading('Analyzing the data…')); root.append(host);
        getInsights().then(r => {
            if (token !== state.token) return;
            const ask = (q) => h('a', { class: 'btn sm', href: 'dashboard.html#ask=' + encodeURIComponent(q) }, icon('message-square', 14), 'Investigate in chat');
            host.replaceChildren(
                h('section', { class: 'section' }, h('div', { class: 'sec-head' }, h('h2', {}, 'Key findings'), h('span', { class: 'sec-sub' }, 'Computed with pandas / SciPy from your data'), ask('Give me the key insights.')), insightCards(r.insights)),
                h('section', { class: 'section' }, h('div', { class: 'sec-head' }, h('h2', {}, 'Unusual values (IQR method)'), ask('Identify unusual values in the dataset.')),
                    r.outliers.length ? h('div', { class: 'table-wrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, ...['Column', 'Outliers', '% of values', 'Normal range', 'Example rows'].map(t => h('th', {}, t)))),
                        h('tbody', {}, ...r.outliers.map(o => h('tr', {}, h('td', {}, o.column), h('td', {}, Fmt.num(o.count)), h('td', {}, o.pct + '%'), h('td', {}, `${o.lower_bound} to ${o.upper_bound}`),
                            h('td', { title: o.examples.map(e => JSON.stringify(e)).join('\n') }, o.examples.slice(0, 2).map(e => e[o.column]).join(', ') + (o.count > 2 ? '…' : ''))))))) : UI.empty('No numeric outliers were detected.')));
            UI.refreshIcons();
        }).catch(e => host.replaceChildren(UI.error(e.message, render)));
    }

    // ------------------------------------------------------------------ cleaning
    function viewCleaning(root, token) {
        const opts = { drop_duplicates: false, drop_missing_rows: false, fill_numeric: null, fill_categorical_mode: false };
        const result = h('div', {});
        const chk = (key, label) => h('label', { class: 'chk' }, h('input', { type: 'checkbox', onchange: e => { opts[key] = e.target.checked; preview(); } }), label);
        const fill = h('select', { 'aria-label': 'Fill numeric missing values', onchange: e => { opts.fill_numeric = e.target.value || null; preview(); } },
            h('option', { value: '' }, 'Leave numeric gaps as they are'), h('option', { value: 'median' }, 'Fill with median'), h('option', { value: 'mean' }, 'Fill with mean'), h('option', { value: 'zero' }, 'Fill with 0'));
        const dl = h('button', { class: 'btn btn-primary', onclick: async () => {
            try { UI.download(await Api.cleanDownload(id(), { ...opts, filters: state.filters }), `cleaned_${(session.filename || 'dataset').replace(/\.[^.]+$/, '')}.csv`); UI.toast('Cleaned CSV downloaded.', 'success'); }
            catch (e) { UI.toast(e.message, 'error'); }
        } }, icon('download', 16), 'Download cleaned CSV');
        root.append(h('div', { class: 'cols2' },
            h('div', { class: 'card form-card' }, h('h3', {}, 'Cleaning options'), h('p', { class: 'muted', style: 'font-size:13px' }, 'Preview only - your uploaded file is never modified. The download is a separate cleaned copy.'),
                chk('drop_duplicates', 'Remove duplicate rows'), fill, chk('fill_categorical_mode', 'Fill categorical gaps with the most frequent value'), chk('drop_missing_rows', 'Remove rows that still have missing values'), dl),
            result));
        async function preview() {
            result.replaceChildren(UI.loading('Calculating preview…'));
            try {
                const r = await Api.cleanPreview(id(), { ...opts, filters: state.filters });
                if (token !== state.token) return;
                const box = (t, k) => h('div', { class: 'card kpi' }, h('div', { class: 'lbl' }, t), h('div', { class: 'val' }, `${Fmt.num(k.rows)} rows`), h('div', { class: 'sub' }, `${Fmt.num(k.missing_values)} missing · ${Fmt.num(k.duplicate_rows)} duplicates`));
                result.replaceChildren(h('div', { class: 'ba' }, box('Before', r.before), box('After', r.after)), h('h3', { style: 'margin:16px 0 6px;font-size:14px' }, 'What will change'), h('ul', { class: 'steps' }, ...r.steps.map(s => h('li', {}, s))));
            } catch (e) { result.replaceChildren(UI.error(e.message, preview)); }
        }
        preview();
    }

    // ------------------------------------------------------------------ recent datasets + settings
    async function viewRecent(root) {
        const host = h('div', {}, UI.loading()); root.append(host);
        const open = (meta) => { Session.save(meta); session = meta; state.filters = Store.filters(meta.dataset_id); state.profile = null; state.cache = {}; location.hash = '#dashboard'; render(); renderHeader('dashboard'); };
        let server = [];
        try { server = (await Api.recent()).datasets; } catch (e) { host.replaceChildren(UI.error(e.message, () => { root.replaceChildren(); viewRecent(root); })); return; }
        const hist = Session.history(), known = new Set(hist.map(x => x.dataset_id));
        const alive = new Map(server.map(x => [x.dataset_id, x]));
        const rows = hist.filter(x => alive.has(x.dataset_id)).map(m => ({ meta: m, current: session && session.dataset_id === m.dataset_id }));
        server.filter(s => !known.has(s.dataset_id)).forEach(s => rows.push({ meta: { dataset_id: s.dataset_id, filename: `Dataset ${s.dataset_id.slice(0, 8)}.${s.file_type}`, file_type: s.file_type, file_size: s.file_size, rows: null, columns: null }, orphan: true }));
        if (!rows.length) return host.replaceChildren(UI.empty('No datasets yet. Upload one from Home.'));
        host.replaceChildren(...rows.map(({ meta, current, orphan }) => h('div', { class: 'card dataset-row' }, icon('file-spreadsheet', 22),
            h('div', { class: 'meta' }, h('div', { class: 'name' }, meta.filename, current ? h('span', { class: 'chip accent', style: 'margin-left:8px' }, 'Current') : null),
                h('div', { class: 'sub' }, [meta.file_type && meta.file_type.toUpperCase(), Fmt.bytes(meta.file_size), meta.rows != null ? `${Fmt.num(meta.rows)} rows × ${Fmt.num(meta.columns)} cols` : null, meta.dataset_id].filter(Boolean).join(' · '))),
            h('button', { class: 'btn sm btn-primary', onclick: async () => {
                if (orphan) { try { const p = await Api.profile(meta.dataset_id); meta = { ...meta, rows: p.rows, columns: p.columns.length }; } catch (e) { return UI.toast(e.message, 'error'); } }
                open(meta);
            } }, 'Open'),
            !orphan ? h('button', { class: 'icon-btn', 'aria-label': 'Remove from list', onclick: () => { Session.forget(meta.dataset_id); root.replaceChildren(); viewRecent(root); } }, icon('trash-2', 16)) : null)));
        UI.refreshIcons();
    }

    function viewSettings(root) {
        const url = h('input', { type: 'text', value: API_BASE, 'aria-label': 'Backend URL' });
        const status = h('p', { class: 'muted', style: 'font-size:13px' });
        root.append(h('div', { class: 'card form-card' }, h('h3', {}, 'Backend connection'),
            h('label', { class: 'muted', style: 'font-size:12px' }, 'FastAPI base URL', url), status,
            h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
                h('button', { class: 'btn sm', onclick: async () => { try { await Api.health(); status.textContent = '✔ Backend is reachable at ' + API_BASE; } catch { status.textContent = '✖ Cannot reach ' + API_BASE; } } }, 'Test connection'),
                h('button', { class: 'btn sm btn-primary', onclick: () => { localStorage.setItem('ada_api_base', url.value.replace(/\/+$/, '')); UI.toast('Saved. Reloading…', 'success'); setTimeout(() => location.reload(), 600); } }, 'Save'))),
            h('div', { class: 'card form-card', style: 'margin-top:16px' }, h('h3', {}, 'Local data'),
                h('p', { class: 'muted', style: 'font-size:13px' }, 'Filters, pinned charts and recent-dataset history are stored in this browser only. Uploaded files stay on the server.'),
                h('button', { class: 'btn sm', onclick: () => { Store.clearAll(); UI.toast('Local data cleared.', 'success'); setTimeout(() => location.href = 'index.html', 600); } }, icon('trash-2', 14), 'Clear saved filters, pins and history')));
        UI.refreshIcons();
    }

    // ------------------------------------------------------------------ router
    async function render(keepFilterBar = false) {
        const view = currentView(), token = ++state.token, root = $('content');
        renderHeader(view);
        root.replaceChildren();
        if (!session && !NO_DATASET_VIEWS.includes(view)) { location.replace('index.html'); return; }
        if (NO_DATASET_VIEWS.includes(view)) { $('filter-host').replaceChildren(); return view === 'recent' ? viewRecent(root) : viewSettings(root); }
        if (!state.profile) {
            root.append(UI.loading('Profiling your dataset…'));
            try { state.profile = await Api.profile(id()); }
            catch (e) {
                if (token !== state.token) return;
                root.replaceChildren(UI.error(e.status === 404 ? 'This dataset is no longer on the server. Please upload it again.' : e.message, e.status === 404 ? () => { Session.clear(); location.href = 'index.html'; } : render));
                return;
            }
            if (token !== state.token) return;
            // drop stale saved filters that reference columns missing from this dataset
            state.filters = state.filters.filter(f => state.profile.columns.some(c => c.name === f.column));
            root.replaceChildren();
        }
        if (!keepFilterBar || !$('filter-host').children.length) buildFilterBar();
        $('filter-host').classList.toggle('hidden', !FILTER_VIEWS.includes(view) || (!state.filters.length && view !== 'dashboard'));
        ({ overview: viewOverview, dashboard: viewDashboard, explorer: viewExplorer, insights: viewInsights, cleaning: viewCleaning })[view](root, token);
        UI.refreshIcons();
    }

    window.addEventListener('hashchange', () => render(true));
    render();
})();

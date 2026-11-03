/* dashboard.js: AI Chat workspace (state, rendering, chat UI). Answers come from the backend, computed on the real dataset. */
(() => {
    const $ = (id) => document.getElementById(id);
    const session = Session.load();
    if (!session) { window.location.replace('index.html'); return; } // no dataset → back to upload
    const filters = () => Store.filters(session.dataset_id); // same filters as the Analytics Dashboard

    // ---- Header + context panel: only real values from the backend, "—" otherwise ----
    const type = (session.file_type || session.filename.split('.').pop() || '').toUpperCase() || '—';
    $('h-file').textContent = session.filename;
    $('h-format').textContent = type;
    $('h-rows').textContent = Fmt.num(session.rows) + ' rows';
    $('h-cols').textContent = Fmt.num(session.columns) + ' columns';
    $('p-file').textContent = session.filename; $('p-type').textContent = type;
    $('p-size').textContent = Fmt.bytes(session.file_size); $('p-rows').textContent = Fmt.num(session.rows);
    $('p-cols').textContent = Fmt.num(session.columns); $('p-id').textContent = session.dataset_id;
    const nf = filters().length;
    if (nf) { $('h-filters').hidden = false; $('h-filters').textContent = `${nf} dashboard filter${nf > 1 ? 's' : ''} applied`; }

    // Column list + data-driven suggestions from the real profile
    const list = $('col-list');
    Api.profile(session.dataset_id).then(p => {
        p.columns.forEach(c => {
            const li = document.createElement('li'); li.innerHTML = '<span></span><small></small>';
            li.firstChild.textContent = c.name; li.lastChild.textContent = c.kind; list.appendChild(li);
        });
        const num = p.columns.find(c => c.kind === 'numeric'), cat = p.columns.find(c => c.kind === 'categorical'), dt = p.columns.find(c => c.kind === 'datetime');
        const qs = [];
        if (num && dt) qs.push(`Show monthly ${num.name} trends.`);
        if (num && cat) qs.push(`Which ${cat.name} has the highest ${num.name}?`);
        if (num) qs.push(`Show the distribution of ${num.name}.`);
        const box = document.querySelector('.suggestions');
        qs.forEach(q => { const b = document.createElement('button'); b.className = 'suggestion'; b.textContent = q; b.addEventListener('click', () => send(q)); box.prepend(b); });
    }).catch(e => { $('col-empty').classList.remove('hidden'); $('col-empty').textContent = e.message; });

    // ---- Chat ----
    const thread = $('thread'), input = $('input'), sendBtn = $('send'), welcome = $('welcome');
    let busy = false;

    function addMsg(role, text, isError) {
        welcome.classList.add('hidden');
        const row = document.createElement('div'); row.className = 'msg ' + role;
        const bubble = document.createElement('div'); bubble.className = 'bubble' + (isError ? ' err' : '');
        bubble.textContent = text; // textContent (not innerHTML) prevents injecting HTML
        if (role === 'ai') row.innerHTML = '<div class="avatar"><i data-lucide="sparkles"></i></div>';
        row.appendChild(bubble); thread.appendChild(row);
        window.lucide && lucide.createIcons();
        $('messages').scrollTop = $('messages').scrollHeight;
        return row;
    }

    /** AI answer with optional table + interactive Plotly charts (each can be added to the dashboard). */
    function addAnswer(res) {
        welcome.classList.add('hidden');
        const row = document.createElement('div'); row.className = 'msg ai';
        row.innerHTML = '<div class="avatar"><i data-lucide="sparkles"></i></div>';
        const rich = UI.h('div', { class: 'rich' });
        rich.append(UI.h('div', { class: 'bubble' }, res.answer));
        if (res.table && res.table.rows.length) {
            rich.append(UI.h('div', { class: 'table-wrap' }, UI.h('table', { class: 't' },
                UI.h('thead', {}, UI.h('tr', {}, ...res.table.columns.map(c => UI.h('th', {}, c)))),
                UI.h('tbody', {}, ...res.table.rows.map(r => UI.h('tr', {}, ...r.map(v => v == null ? UI.h('td', { class: 'null' }, 'null') : UI.h('td', {}, typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(v)))))))));
        }
        (res.charts || []).forEach(c => {
            const actions = c.config ? [{
                icon: 'layout-dashboard', label: 'Add to Analytics Dashboard', onClick: () => {
                    UI.toast(Store.addPin(session.dataset_id, { title: c.title, config: c.config }) ? 'Added to your Analytics Dashboard.' : 'This chart is already on your dashboard.', 'success');
                }
            }] : [];
            rich.append(Charts.card({ title: c.title, figure: c.figure, notes: c.notes || [], actions, height: 320 }));
        });
        if ((res.charts || []).some(c => c.config)) rich.append(UI.h('a', { class: 'sec-sub', href: 'analytics.html#dashboard' }, 'Open Analytics Dashboard →'));
        row.append(rich); thread.append(row);
        UI.refreshIcons();
        $('messages').scrollTop = $('messages').scrollHeight;
    }

    async function send(text) {
        text = text.trim(); if (!text || busy) return;
        busy = true; sendBtn.disabled = true; input.value = ''; autosize();
        addMsg('user', text);
        const loading = addMsg('ai', '');
        loading.querySelector('.bubble').innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
        try {
            const res = await Analysis.ask(session.dataset_id, text, filters());
            loading.remove(); addAnswer(res);
        } catch (e) {
            loading.remove(); addMsg('ai', e.message, true);
        } finally { busy = false; sendBtn.disabled = false; input.focus(); }
    }

    function autosize() { input.style.height = 'auto'; input.style.height = input.scrollHeight + 'px'; }
    $('composer').addEventListener('submit', e => { e.preventDefault(); send(input.value); });
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); } }); // Shift+Enter = newline
    input.addEventListener('input', autosize);
    document.querySelectorAll('.suggestion').forEach(b => b.addEventListener('click', () => send(b.textContent)));
    $('clear').addEventListener('click', () => { thread.querySelectorAll('.msg').forEach(m => m.remove()); welcome.classList.remove('hidden'); });

    // ---- Panel toggle ----
    const panel = $('panel'), toggle = $('toggle-panel');
    toggle.addEventListener('click', () => { const hide = panel.classList.toggle('hidden'); toggle.setAttribute('aria-expanded', String(!hide)); });
    window.lucide && lucide.createIcons();

    // Deep link from the dashboard: dashboard.html#ask=<question>
    const m = location.hash.match(/^#ask=(.+)$/);
    if (m) { history.replaceState(null, '', location.pathname); send(decodeURIComponent(m[1])); }
})();

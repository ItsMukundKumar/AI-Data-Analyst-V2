/* nav.js: renders the single shared sidebar on every page so navigation stays consistent. */
(() => {
    const ITEMS = [
        { id: 'overview', label: 'Overview', icon: 'layout-grid', href: 'analytics.html#overview', needs: true },
        { id: 'dashboard', label: 'Analytics Dashboard', icon: 'bar-chart-3', href: 'analytics.html#dashboard', needs: true },
        { id: 'chat', label: 'AI Chat', icon: 'message-square', href: 'dashboard.html', needs: true },
        { id: 'explorer', label: 'Data Explorer', icon: 'table-2', href: 'analytics.html#explorer', needs: true },
        { id: 'insights', label: 'AI Insights', icon: 'lightbulb', href: 'analytics.html#insights', needs: true },
        { id: 'cleaning', label: 'Data Cleaning', icon: 'sparkles', href: 'analytics.html#cleaning', needs: true },
        { id: 'recent', label: 'Recent Datasets', icon: 'history', href: 'analytics.html#recent' },
    ];
    const side = document.getElementById('sidebar');
    if (!side) return;
    const page = location.pathname.split('/').pop() || 'index.html';
    const hash = (location.hash || '#overview').slice(1);
    const current = page === 'dashboard.html' ? 'chat' : page === 'analytics.html' ? hash : 'home';
    const session = Session.load();

    side.setAttribute('aria-label', 'Main navigation');
    side.append(UI.h('div', { class: 'brand' }, UI.icon('bar-chart-3'), ' AI Data Analyst'));
    const nav = UI.h('nav', { class: 'nav' },
        UI.h('a', { class: 'nav-link' + (current === 'home' ? ' active' : ''), href: 'index.html' }, UI.icon('home'), ' Home'),
        UI.h('a', { class: 'nav-link', href: '#', 'data-new-analysis': true }, UI.icon('plus-circle'), ' New Analysis'),
        ...ITEMS.map(i => {
            const disabled = i.needs && !session;
            return UI.h('a', {
                class: 'nav-link' + (current === i.id ? ' active' : ''), href: disabled ? null : i.href, 'data-nav': i.id,
                'aria-disabled': disabled ? 'true' : null, tabindex: disabled ? '-1' : null,
                title: disabled ? 'Upload a dataset first' : null
            }, UI.icon(i.icon), ' ' + i.label);
        }));
    side.append(nav, UI.h('div', { class: 'nav-bottom' },
        UI.h('a', { class: 'nav-link' + (current === 'settings' ? ' active' : ''), href: 'analytics.html#settings' }, UI.icon('settings'), ' Settings'),
        UI.h('div', { class: 'version' }, 'Version V2')));

    // Mobile: collapsible sidebar
    const btn = UI.h('button', { class: 'menu-btn', 'aria-label': 'Toggle navigation', onclick: () => side.classList.toggle('open') }, UI.icon('menu', 20));
    document.body.append(btn);
    side.addEventListener('click', e => { if (e.target.closest('a')) side.classList.remove('open'); });

    // Keep the active state in sync when switching views inside analytics.html
    window.addEventListener('hashchange', () => {
        if (page !== 'analytics.html') return;
        const h = location.hash.slice(1);
        side.querySelectorAll('.nav-link').forEach(a => a.classList.toggle('active', a.dataset.nav === h || (h === 'settings' && a.getAttribute('href') === 'analytics.html#settings')));
    });

    // New analysis from any page except Home (Home's upload.js handles its own)
    if (page !== 'index.html') {
        side.querySelector('[data-new-analysis]').addEventListener('click', e => { e.preventDefault(); Session.clear(); location.href = 'index.html'; });
    }
    UI.refreshIcons();
})();

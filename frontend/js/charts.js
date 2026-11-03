/* charts.js: Plotly.js rendering (theme, responsive resize, PNG download). Specs come from the backend. */
const Charts = {
    PALETTE: ['#378EFF', '#3FB950', '#F2A33A', '#B07CFF', '#FF6B8B', '#2FD0C8', '#E3C84B', '#7D8FA6', '#FF8A4C', '#8BD450'],
    theme(layout = {}, compact = false) {
        const grid = '#252D38', txt = '#C9D1D9';
        const axis = (a = {}) => ({ gridcolor: grid, zerolinecolor: grid, linecolor: grid, automargin: true, ...a, title: a.title ? { ...a.title, font: { size: 12, color: '#929BA8' } } : undefined });
        const t = layout.title && layout.title.text ? { text: layout.title.text, x: 0.01, xanchor: 'left', font: { size: 14, color: '#F5F7FA' } } : undefined;
        return {
            ...layout, title: compact ? undefined : t, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
            font: { family: 'Inter, system-ui, sans-serif', color: txt, size: 12 }, colorway: Charts.PALETTE,
            margin: { l: 50, r: 20, t: compact ? 20 : 46, b: 50 }, hoverlabel: { bgcolor: '#151B23', bordercolor: '#378EFF', font: { color: '#F5F7FA' } },
            xaxis: axis(layout.xaxis), yaxis: axis(layout.yaxis),
            legend: { orientation: 'h', y: -0.2, font: { size: 11 } }, autosize: true
        };
    },
    /** Render a backend figure into `el`. Returns the element. */
    render(el, figure, compact = false) {
        if (!window.Plotly) { el.replaceChildren(UI.error('Plotly.js failed to load (check your internet connection).')); return el; }
        const layout = Charts.theme(figure.layout, compact);
        Plotly.react(el, figure.data, layout, {
            responsive: true, displaylogo: false, scrollZoom: false,
            modeBarButtonsToRemove: ['select2d', 'lasso2d'],
            toImageButtonOptions: { format: 'png', filename: 'chart', scale: 2, height: 600, width: 1000 }
        });
        return el;
    },
    downloadPng(el, name) {
        if (!window.Plotly || !el.data) return UI.toast('Chart is not ready yet.', 'error');
        Plotly.downloadImage(el, { format: 'png', filename: (name || 'chart').replace(/[^\w\-]+/g, '_'), scale: 2, width: 1100, height: 650, bgcolor: '#151B23' });
    },
    /** A titled chart card with PNG download and optional extra actions: [{icon,label,onClick}] */
    card({ title, subtitle, figure, notes = [], actions = [], height = 340, wide = false }) {
        const plot = UI.h('div', { class: 'plot', style: `height:${height}px` });
        const acts = UI.h('div', { class: 'card-actions' },
            ...actions.map(a => UI.h('button', { class: 'icon-btn', title: a.label, 'aria-label': a.label, onclick: () => a.onClick(plot) }, UI.icon(a.icon, 15))),
            UI.h('button', { class: 'icon-btn', title: 'Download PNG', 'aria-label': 'Download chart as PNG', onclick: () => Charts.downloadPng(plot, title) }, UI.icon('download', 15)));
        const card = UI.h('article', { class: 'card chart-card' + (wide ? ' wide' : '') },
            UI.h('header', {}, UI.h('div', {}, UI.h('h3', {}, title), subtitle ? UI.h('p', { class: 'sub' }, subtitle) : null), acts),
            plot, notes.length ? UI.h('p', { class: 'notes' }, notes.join(' ')) : null);
        // Render after the card is in the DOM so Plotly can measure the width
        requestAnimationFrame(() => Charts.render(plot, figure, true)); // card header already shows the title
        UI.refreshIcons();
        return card;
    }
};
// Plotly's `responsive` handles window resize; this also catches sidebar/panel layout shifts.
if (window.ResizeObserver) {
    new ResizeObserver(UI.debounce(() => document.querySelectorAll('.plot').forEach(p => p.data && window.Plotly && Plotly.Plots.resize(p)), 150)).observe(document.body);
}

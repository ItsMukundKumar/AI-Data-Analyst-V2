/* ui.js: tiny DOM helpers shared by all pages. Text is always set via textContent (no HTML injection). */
const UI = {
    /** h('div', {class:'x', onclick:fn}, 'text', childNode) */
    h(tag, attrs = {}, ...kids) {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v == null || v === false) continue;
            if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
            else if (k === 'class') el.className = v;
            else if (k === 'html') el.innerHTML = v;      // only used with trusted static strings (icons)
            else el.setAttribute(k, v === true ? '' : v);
        }
        for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(String(k)));
        return el;
    },
    icon(name, size = 16) { return UI.h('i', { 'data-lucide': name, width: size, height: size }); },
    refreshIcons() { window.lucide && lucide.createIcons(); },
    loading(msg = 'Loading…') { return UI.h('div', { class: 'state loading' }, UI.h('span', { class: 'spinner' }), msg); },
    empty(msg) { return UI.h('div', { class: 'state empty' }, msg); },
    error(msg, retry) {
        return UI.h('div', { class: 'state error' }, UI.icon('alert-triangle'), UI.h('span', {}, msg),
            retry ? UI.h('button', { class: 'btn', onclick: retry }, 'Retry') : null);
    },
    toast(msg, kind = 'info') {
        let box = document.getElementById('toasts');
        if (!box) { box = UI.h('div', { id: 'toasts', 'aria-live': 'polite' }); document.body.append(box); }
        const t = UI.h('div', { class: 'toast ' + kind }, msg); box.append(t);
        setTimeout(() => t.remove(), 3500);
    },
    debounce(fn, ms = 350) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; },
    download(blob, name) {
        const a = UI.h('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    }
};

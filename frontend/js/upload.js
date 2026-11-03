/* upload.js: file selection, validation, upload, redirect (Home page only). */
(() => {
    const MAX = 50 * 1024 * 1024, OK_EXT = ['csv', 'xlsx', 'xls'];
    const $ = (id) => document.getElementById(id);
    const zone = $('dropzone'), input = $('file-input'), card = $('file-card'),
        statusEl = $('status'), uploadBtn = $('upload-btn');
    let selected = null;

    const ext = (f) => f.name.split('.').pop().toLowerCase();
    function setStatus(type, msg) {
        statusEl.className = 'status ' + (type || 'hidden');
        statusEl.textContent = msg || '';
    }

    /** Returns an error string, or null if the file is acceptable. */
    function validate(f) {
        if (!OK_EXT.includes(ext(f))) return 'Unsupported format. Please choose a CSV, XLSX or XLS file.';
        if (f.size > MAX) return `File is ${Fmt.bytes(f.size)}. The maximum is 50 MB.`;
        if (f.size === 0) return 'This file is empty.';
        return null;
    }

    function select(f) {
        const err = validate(f);
        if (err) { clear(); return setStatus('error', err); }
        selected = f; setStatus();
        $('file-name').textContent = f.name;
        $('file-sub').textContent = `${ext(f).toUpperCase()} · ${Fmt.bytes(f.size)}`;
        card.classList.remove('hidden'); uploadBtn.disabled = false;
    }
    function clear() { selected = null; input.value = ''; card.classList.add('hidden'); uploadBtn.disabled = true; }

    async function upload() {
        if (!selected) return;
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<span class="spinner"></span> Uploading…';
        setStatus();
        try {
            Session.save(await Api.uploadDataset(selected));
            setStatus('success', 'Upload complete. Opening your workspace…');
            window.location.href = 'dashboard.html'; // automatic navigation to page two
        } catch (e) {
            setStatus('error', e.message);
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = '<i data-lucide="upload"></i> Upload';
            window.lucide && lucide.createIcons();
        }
    }

    // Drag and drop: preventDefault is required or the browser opens the file instead
    ['dragenter', 'dragover'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.add('dragover'); }));
    ['dragleave', 'drop'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.remove('dragover'); }));
    zone.addEventListener('drop', e => e.dataTransfer.files[0] && select(e.dataTransfer.files[0]));
    input.addEventListener('change', () => input.files[0] && select(input.files[0]));
    $('browse-btn').addEventListener('click', () => input.click());
    $('remove-btn').addEventListener('click', () => { clear(); setStatus(); });
    uploadBtn.addEventListener('click', upload);
    document.querySelectorAll('[data-scroll-upload]').forEach(b => b.addEventListener('click', e => { e.preventDefault(); zone.scrollIntoView({ behavior: 'smooth', block: 'center' }); $('browse-btn').focus({ preventScroll: true }); }));
    document.querySelectorAll('[data-new-analysis]').forEach(b => b.addEventListener('click', e => { e.preventDefault(); Session.clear(); clear(); setStatus(); zone.scrollIntoView({ behavior: 'smooth', block: 'center' }); }));
    window.lucide && lucide.createIcons();
})();
(() => {
    'use strict';
    document.addEventListener('DOMContentLoaded', () => {
        const API_DATA_URL = '/api/landing/data';
        const API_DOC_URL = '/api/landing/doc?path=';
        const DEFAULT_DOC_PATH = 'docs/ai-context/README.md';
        const elements = {
            latestCommit: document.getElementById('latest-commit'),
            testsCount: document.getElementById('tests-count'),
            updatedAt: document.getElementById('updated-at'),
            metricCommit: document.getElementById('metric-commit'),
            metricTests: document.getElementById('metric-tests'),
            metricUpdated: document.getElementById('metric-updated'),
            docsTree: document.getElementById('docs-tree'),
            docsCount: document.getElementById('docs-count'),
            docsCurrentTitle: document.getElementById('docs-current-title'),
            docsCurrentPath: document.getElementById('docs-current-path'),
            docsContent: document.getElementById('docs-content'),
            techStack: document.getElementById('tech-stack'),
            copyAiPrompt: document.getElementById('copy-ai-prompt'),
            downloadZip: document.getElementById('download-zip'),
            toast: document.getElementById('toast')
        };
        let docsTree = [];
        let toastTimer = null;
        let currentDocRequest = 0;
        function setText(el, v) { if (el) el.textContent = v == null ? '' : String(v); }
        function showToast(msg) {
            if (!elements.toast) return;
            setText(elements.toast, msg);
            elements.toast.classList.add('is-visible');
            if (toastTimer !== null) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => { elements.toast.classList.remove('is-visible'); toastTimer = null; }, 2000);
        }
        function pluralize(n, one, few, many) {
            const t = n % 100, o = n % 10;
            if (t >= 11 && t <= 14) return many;
            if (o === 1) return one;
            if (o >= 2 && o <= 4) return few;
            return many;
        }
        function formatRelativeDate(v) {
            if (!v) return '—';
            const ts = Date.parse(v);
            if (!Number.isFinite(ts)) return '—';
            const diff = Math.max(0, Date.now() - ts);
            const m = Math.floor(diff / 60000);
            if (m < 1) return 'только что';
            if (m < 60) return `${m} ${pluralize(m, 'минуту', 'минуты', 'минут')} назад`;
            const h = Math.floor(m / 60);
            if (h < 24) return `${h} ${pluralize(h, 'час', 'часа', 'часов')} назад`;
            const d = Math.floor(h / 24);
            return `${d} ${pluralize(d, 'день', 'дня', 'дней')} назад`;
        }
        function basename(p) { const n = String(p || '').replace(/\\/g, '/'); const a = n.split('/').filter(Boolean); return a.length ? a[a.length - 1] : n; }
        function resetMetrics() { [elements.latestCommit, elements.testsCount, elements.updatedAt, elements.metricCommit, elements.metricTests, elements.metricUpdated].forEach(e => setText(e, '—')); }
        function renderMetrics(data) {
            const c = (data && data.latest_commit) || {};
            const sha = typeof c.sha === 'string' ? c.sha.slice(0, 7) : '';
            const msg = typeof c.message === 'string' ? c.message.trim() : '';
            const short = msg.length > 60 ? msg.slice(0, 60) + '…' : msg;
            const label = sha ? (sha + (short ? ' — ' + short : '')) : '—';
            const raw = Number(data && data.tests_count);
            const tests = Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;
            const rel = formatRelativeDate(c.date);
            setText(elements.latestCommit, label);
            setText(elements.testsCount, tests > 0 ? `${tests} тестов` : '—');
            setText(elements.updatedAt, rel);
            setText(elements.metricCommit, sha || '—');
            setText(elements.metricTests, tests > 0 ? String(tests) : '—');
            setText(elements.metricUpdated, rel);
        }
        function renderDocsTree(items) {
            if (!elements.docsTree) return;
            elements.docsTree.replaceChildren();
            const valid = Array.isArray(items) ? items.filter(i => i && typeof i.path === 'string' && i.path.length > 0) : [];
            docsTree = valid;
            setText(elements.docsCount, String(valid.length));
            if (!valid.length) {
                const p = document.createElement('p'); p.className = 'docs-placeholder'; p.textContent = 'Документация пока недоступна.'; elements.docsTree.appendChild(p); return;
            }
            valid.forEach((item, idx) => {
                const b = document.createElement('button'); b.type = 'button'; b.className = 'docs-item'; b.dataset.path = item.path;
                const t = document.createElement('strong'); t.textContent = item.title || basename(item.path);
                const f = document.createElement('small'); f.textContent = basename(item.path);
                b.append(t, f);
                b.addEventListener('click', () => selectDocument(item.path, b));
                if (idx === 0) b.classList.add('is-active');
                elements.docsTree.appendChild(b);
            });
            selectDocument(valid[0].path, elements.docsTree.querySelector('.docs-item'));
        }
        function renderTechStack(stack) {
            if (!elements.techStack) return;
            elements.techStack.replaceChildren();
            if (!stack || typeof stack !== 'object' || Array.isArray(stack)) {
                const p = document.createElement('p'); p.className = 'tech-placeholder'; p.textContent = 'Данные о технологиях недоступны.'; elements.techStack.appendChild(p); return;
            }
            const entries = Object.entries(stack);
            if (!entries.length) {
                const p = document.createElement('p'); p.className = 'tech-placeholder'; p.textContent = 'Данные о технологиях пока не опубликованы.'; elements.techStack.appendChild(p); return;
            }
            entries.forEach(([k, v]) => {
                const card = document.createElement('article'); card.className = 'tech-card';
                const l = document.createElement('span'); l.className = 'tech-label'; l.textContent = k;
                const d = document.createElement('strong');
                let dv;
                if (Array.isArray(v)) dv = v.map(String).join(', ');
                else if (v && typeof v === 'object') dv = JSON.stringify(v);
                else dv = v == null ? '—' : String(v);
                d.textContent = dv || '—';
                card.append(l, d); elements.techStack.appendChild(card);
            });
        }
        async function selectDocument(path, clicked) {
            if (!path || !elements.docsContent) return;
            if (elements.docsTree) elements.docsTree.querySelectorAll('.docs-item').forEach(i => i.classList.remove('is-active'));
            const btn = clicked || (elements.docsTree ? Array.from(elements.docsTree.querySelectorAll('.docs-item')).find(i => i.dataset.path === path) : null);
            if (btn) btn.classList.add('is-active');
            const info = docsTree.find(i => i.path === path);
            setText(elements.docsCurrentTitle, info && info.title ? info.title : basename(path));
            setText(elements.docsCurrentPath, path);
            const reqId = ++currentDocRequest;
            const loading = document.createElement('p'); loading.className = 'docs-placeholder'; loading.textContent = 'Загрузка документа…'; elements.docsContent.replaceChildren(loading);
            try {
                const r = await fetch(`${API_DOC_URL}${encodeURIComponent(path)}`, { method: 'GET', headers: { Accept: 'application/json' } });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const result = await r.json();
                if (reqId !== currentDocRequest) return;
                if (typeof result.html !== 'string') throw new Error('no html');
                elements.docsContent.innerHTML = result.html;
                elements.docsContent.scrollTop = 0;
            } catch (e) {
                if (reqId !== currentDocRequest) return;
                const p = document.createElement('p'); p.className = 'docs-placeholder'; p.textContent = 'Не удалось загрузить документ.';
                elements.docsContent.replaceChildren(p); elements.docsContent.scrollTop = 0;
            }
        }
        async function copyText(text) {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
            }
            const ta = document.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0'; ta.style.left = '-9999px';
            document.body.appendChild(ta); ta.focus(); ta.select();
            let ok = false;
            try { ok = document.execCommand('copy'); } catch (e) { ok = false; } finally { ta.remove(); }
            return ok;
        }
        async function handleCopyPrompt() {
            const active = elements.docsTree ? elements.docsTree.querySelector('.docs-item.is-active') : null;
            const cur = active ? active.dataset.path : DEFAULT_DOC_PATH;
            const prompt = [
                `Прочитай https://ai.pqnet.ru/api/landing/doc?path=${cur}`,
                `и https://ai.pqnet.ru/api/landing/doc?path=${DEFAULT_DOC_PATH}.`,
                'Схема: я даю идеи, ты формулируешь промпт для GPT, GPT применяет код в GitHub, я проверяю в браузере.'
            ].join('\n');
            const ok = await copyText(prompt);
            showToast(ok ? 'Скопировано' : 'Не удалось скопировать текст');
        }
        async function loadLandingData() {
            try {
                const r = await fetch(API_DATA_URL, { method: 'GET', headers: { Accept: 'application/json' } });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const data = await r.json();
                renderMetrics(data); renderDocsTree(data.docs_tree); renderTechStack(data.tech_stack);
            } catch (e) {
                resetMetrics();
                if (elements.docsTree) {
                    const p = document.createElement('p'); p.className = 'docs-placeholder'; p.textContent = 'Не удалось загрузить список. Попробуйте позже.';
                    elements.docsTree.replaceChildren(p);
                }
                setText(elements.docsCount, '—');
                if (elements.techStack) {
                    const p = document.createElement('p'); p.className = 'tech-placeholder'; p.textContent = 'Данные о технологиях временно недоступны.';
                    elements.techStack.replaceChildren(p);
                }
                showToast('Данные временно недоступны');
            }
        }
        if (elements.copyAiPrompt) elements.copyAiPrompt.addEventListener('click', handleCopyPrompt);
        if (elements.downloadZip) elements.downloadZip.addEventListener('click', e => { e.preventDefault(); window.location.href = '/api/landing/download'; });
        loadLandingData();
    });
})();

/* ============================================================
   Tennis Dashboard — front-end logic
   Loads data/tournaments.json and data/reservations.json,
   renders filters, status chips, and the booking form.
   ============================================================ */

(() => {
    'use strict';

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // ---------- tab switching ----------
    $$('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.tab').forEach(b => b.classList.remove('active'));
            $$('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
        });
    });

    // ---------- date helpers ----------
    const today = new Date().toISOString().slice(0, 10);
    const setDefaultDate = () => {
        const f = $('#f-date');
        if (!f.value) f.value = today;
        f.min = today;
    };

    // ---------- load data ----------
    async function fetchJSON(path) {
        try {
            const r = await fetch(path, { cache: 'no-store' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return await r.json();
        } catch (e) {
            console.warn(`Failed to load ${path}:`, e);
            return null;
        }
    }

    function isFileProtocol() {
        return location.protocol === 'file:';
    }

    function fmtDate(s) {
        if (!s) return '';
        const d = new Date(s + 'T00:00:00');
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function fmtDateRange(start, end) {
        if (!start) return '';
        if (!end || start === end) return fmtDate(start);
        return `${fmtDate(start)} → ${fmtDate(end)}`;
    }

    function daysUntil(s) {
        if (!s) return Infinity;
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const target = new Date(s + 'T00:00:00');
        return Math.round((target - today) / 86400000);
    }

    // ---------- render status bar ----------
    function setDotStatus(dotEl, status) {
        dotEl.className = 'status-dot ' + (status || '');
    }

    function renderStatus(tournamentData, reservationCount) {
        const lastRefresh = tournamentData?.generated_at
            ? new Date(tournamentData.generated_at).toLocaleString('en-US', {
                month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
            })
            : 'never';
        $('#last-refresh').textContent = lastRefresh;

        if (tournamentData?.sources) {
            setDotStatus($('#dot-utr'), tournamentData.sources.utr?.status);
            setDotStatus($('#dot-usta'), tournamentData.sources.usta?.status);
        }

        // ANC dot: green if reservations file present, yellow otherwise
        if (reservationCount !== undefined) {
            setDotStatus($('#dot-anc'), reservationCount >= 0 ? 'ok' : 'error');
        }
    }

    // ---------- banners ----------
    function renderTournamentBanners(data) {
        const out = $('#banner-tournaments');
        out.innerHTML = '';

        if (isFileProtocol() && !data) {
            out.innerHTML = `<div class="banner info">
                ℹ️ <span>The browser blocks <code>fetch()</code> on the <code>file://</code> protocol.
                To preview locally, run <code>python -m http.server 8765</code> in the
                <code>tennis-dashboard/</code> directory, then open
                <a href="http://localhost:8765" style="color: inherit; text-decoration: underline;">http://localhost:8765</a>.
                On GitHub Pages this works automatically.</span>
            </div>`;
            return;
        }

        if (!data) {
            out.innerHTML = `<div class="banner error">❌ Could not load <code>data/tournaments.json</code>. Run <code>python scripts/fetch_tournaments.py</code> locally to generate it.</div>`;
            return;
        }
        const { sources } = data;
        if (!sources) return;

        const needs = [];
        if (sources.utr?.status === 'needs_login') needs.push('UTR');
        if (sources.usta?.status === 'needs_login') needs.push('USTA');
        if (needs.length) {
            out.innerHTML = `<div class="banner warn">
                ⚠️ <span><strong>${needs.join(' + ')}</strong> needs a one-time login capture.
                Open the <a href="#" onclick="document.querySelector('[data-tab=&quot;setup&quot;]').click(); return false;" style="color: inherit; text-decoration: underline;">Setup tab</a>
                for instructions.</span>
            </div>`;
        } else if (sources.utr?.status === 'error' || sources.usta?.status === 'error') {
            const errs = [sources.utr, sources.usta].filter(s => s?.status === 'error').map(s => s.error).join(' / ');
            out.innerHTML = `<div class="banner error">❌ Scraper error: ${escapeHTML(errs)}</div>`;
        }
    }

    function escapeHTML(s) {
        return String(s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[c]);
    }

    // ---------- tournaments list ----------
    function renderTournaments(data) {
        const list = $('#tournament-list');
        const count = $('#tournament-count');
        const radius = $('#radius-display');

        if (!data) {
            list.innerHTML = '<div class="empty"><h3>No data</h3><p>Generate tournaments.json to populate this list.</p></div>';
            count.textContent = '';
            return;
        }

        radius.textContent = data.home?.radius_miles || 80;

        const source = $('#filter-source').value;
        const when = $('#filter-when').value;
        const sort = $('#filter-sort').value;

        let items = data.tournaments || [];

        if (source) items = items.filter(t => t.source === source);
        if (when === 'future') items = items.filter(t => daysUntil(t.start_date) >= 0);

        items.sort((a, b) => {
            if (sort === 'distance') return (a.distance_miles || 999) - (b.distance_miles || 999);
            if (sort === 'name') return a.name.localeCompare(b.name);
            // date asc
            return (a.start_date || '9999').localeCompare(b.start_date || '9999');
        });

        count.textContent = `${items.length} of ${(data.tournaments || []).length}`;

        if (!items.length) {
            list.innerHTML = `<div class="empty">
                <h3>No matching tournaments</h3>
                <p>Try widening the filter or refreshing the data.</p>
            </div>`;
            return;
        }

        list.innerHTML = items.map(t => {
            const days = daysUntil(t.start_date);
            const daysLabel = days < 0 ? '' :
                              days === 0 ? '<span style="color: var(--orange); font-weight: 600;">today</span>' :
                              days === 1 ? '<span style="color: var(--orange);">tomorrow</span>' :
                              days <= 14 ? `<span style="color: var(--orange);">in ${days}d</span>` :
                              '';
            return `
            <div class="tournament">
                <div>
                    <div class="t-name">
                        ${escapeHTML(t.name || '(untitled)')}
                        <span class="t-badge ${(t.source || '').toLowerCase()}">${t.source || '?'}</span>
                        ${daysLabel ? `· <span style="font-weight: 400; font-size: 0.85rem;">${daysLabel}</span>` : ''}
                    </div>
                    <div class="t-meta">
                        <span>${fmtDateRange(t.start_date, t.end_date)}</span>
                        ${t.venue ? `<span>${escapeHTML(t.venue)}</span>` : ''}
                        ${t.city ? `<span>${escapeHTML(t.city)}${t.state ? ', ' + escapeHTML(t.state) : ''}</span>` : ''}
                        ${t.level ? `<span>${escapeHTML(t.level)}</span>` : ''}
                        ${t.surface ? `<span>${escapeHTML(t.surface)}</span>` : ''}
                        ${t.age_division ? `<span>${escapeHTML(t.age_division)}</span>` : ''}
                        ${t.registration_deadline ? `<span>Reg by ${fmtDate(t.registration_deadline)}</span>` : ''}
                    </div>
                </div>
                <div class="t-actions">
                    ${t.distance_miles != null ? `<div class="t-distance">${t.distance_miles} mi</div>` : ''}
                    ${t.registration_url ? `<a class="t-link" href="${escapeHTML(t.registration_url)}" target="_blank" rel="noopener noreferrer">Register ↗</a>` : ''}
                </div>
            </div>`;
        }).join('');
    }

    // ---------- reservations ----------
    function renderReservations(data) {
        const list = $('#reservation-list');
        const count = $('#reservation-count');

        if (!data || !Array.isArray(data.reservations) || !data.reservations.length) {
            list.innerHTML = `<div class="empty">
                <h3>No reservations yet</h3>
                <p>Use the form above to plan or book a court at Anderson Mill.</p>
            </div>`;
            count.textContent = '0';
            return;
        }

        const sorted = [...data.reservations].sort((a, b) => {
            const ad = (a.date || '') + ' ' + (a.start_time || '');
            const bd = (b.date || '') + ' ' + (b.start_time || '');
            return ad.localeCompare(bd);
        });

        count.textContent = sorted.length;

        list.innerHTML = sorted.map(r => `
            <div class="reservation">
                <div>
                    <div class="r-when">${fmtDate(r.date)} at ${r.start_time || '?'}</div>
                    <div class="r-what">
                        ${escapeHTML(r.facility || 'Anderson Mill')}
                        ${r.court ? ` · Court ${escapeHTML(r.court)}` : ''}
                        · ${r.duration_min || 60} min
                        ${r.confirmation_id ? ` · Conf #${escapeHTML(r.confirmation_id)}` : ''}
                        ${r.notes ? ` · ${escapeHTML(r.notes)}` : ''}
                    </div>
                </div>
                <div class="r-status ${r.status}">${r.status.replace('_', ' ')}</div>
            </div>
        `).join('');
    }

    // ---------- booking form ----------
    function attachBookingHandlers() {
        // We can't actually invoke the local Python script from a static page,
        // but we DO record plans in localStorage so the dashboard reflects intent
        // even when running purely client-side. The Python pipeline reconciles
        // with data/reservations.json when run locally.

        const STORAGE_KEY = 'tennis_dashboard_plans';

        function getPlans() {
            try {
                return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
            } catch { return []; }
        }
        function setPlans(p) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
        }

        function renderLocalPlans() {
            const plans = getPlans();
            const merged = [...(window.__reservationsData?.reservations || []),
                            ...plans.map(p => ({ ...p, _local: true }))];
            renderReservations({ reservations: merged });
        }

        $('#btn-plan').addEventListener('click', () => {
            const date = $('#f-date').value;
            const time = $('#f-time').value;
            const duration = parseInt($('#f-duration').value, 10);
            const court = $('#f-court').value.trim();

            if (!date || !time) {
                alert('Please pick a date and time.');
                return;
            }
            const plans = getPlans();
            plans.push({
                id: 'local-' + Date.now(),
                facility: 'Anderson Mill Tennis Court',
                court,
                date,
                start_time: time,
                duration_min: duration,
                status: 'planned',
                created_at: new Date().toISOString(),
                notes: 'Local-only plan (run python scripts/book_court.py to persist to data/reservations.json)',
            });
            setPlans(plans);
            renderLocalPlans();
            flashBanner($('#banner-courts'), 'success',
                `✓ Plan saved locally for ${fmtDate(date)} at ${time}. ` +
                `To make it real, run: <code>python scripts/book_court.py --date ${date} --time ${time} --duration ${duration}${court ? ' --court ' + court : ''}</code>`);
        });

        $('#btn-book').addEventListener('click', () => {
            flashBanner($('#banner-courts'), 'warn',
                `Booking must be triggered locally — this page is static. Run from a terminal:<br>
                <code>python scripts/book_court.py --date ${$('#f-date').value} --time ${$('#f-time').value} --duration ${$('#f-duration').value}${($('#f-court').value.trim()) ? ' --court ' + $('#f-court').value.trim() : ''}</code>`);
        });

        // Expose for re-render
        window.__renderLocalPlans = renderLocalPlans;
    }

    function flashBanner(el, type, html) {
        el.innerHTML = `<div class="banner ${type}">${html}</div>`;
        setTimeout(() => { el.innerHTML = ''; }, 12_000);
    }

    // ---------- filters ----------
    function attachFilterHandlers(loadTournamentData) {
        ['filter-source', 'filter-when', 'filter-sort'].forEach(id => {
            document.getElementById(id).addEventListener('change', () => {
                renderTournaments(window.__tournamentData);
            });
        });
    }

    // ---------- bootstrap ----------
    async function init() {
        setDefaultDate();
        attachBookingHandlers();

        const [tournamentData, reservationsData] = await Promise.all([
            fetchJSON('data/tournaments.json'),
            fetchJSON('data/reservations.json'),
        ]);
        window.__tournamentData = tournamentData;
        window.__reservationsData = reservationsData || { reservations: [] };

        renderStatus(tournamentData, reservationsData?.reservations?.length);
        renderTournamentBanners(tournamentData);
        renderTournaments(tournamentData);

        // Render reservations including local-only plans
        const renderReservationsWithLocal = () => {
            const plans = (() => {
                try { return JSON.parse(localStorage.getItem('tennis_dashboard_plans') || '[]'); }
                catch { return []; }
            })();
            const merged = [
                ...(window.__reservationsData?.reservations || []),
                ...plans.map(p => ({ ...p, _local: true })),
            ];
            renderReservations({ reservations: merged });
        };
        renderReservationsWithLocal();

        attachFilterHandlers(tournamentData);

        // Periodic refresh of the status bar
        setInterval(() => {
            const lastRefresh = window.__tournamentData?.generated_at;
            if (lastRefresh) {
                $('#last-refresh').textContent = new Date(lastRefresh).toLocaleString('en-US', {
                    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
                });
            }
        }, 60_000);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
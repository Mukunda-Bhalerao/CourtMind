/**
 * CourtMind — Simulation Player
 *
 * Drives the animated courtroom UI by stepping through simulation events,
 * updating actor cards, speech bubbles, evidence board, and playback state.
 */

(function () {
    "use strict";

    // ── DOM references ──────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const btnPlay    = $("#btn-play");
    const btnNext    = $("#btn-next");
    const btnPrev    = $("#btn-prev");
    const btnRestart = $("#btn-restart");
    const btnBack    = $("#btn-back");
    const speedSel   = $("#speed-select");
    const progressBar = $("#progress-fill");
    const statusBadge = $("#status-badge");
    const eventCounter = $("#event-counter");

    // Verdict overlay
    const verdictOverlay = $("#verdict-overlay");
    const verdictTitle   = $("#verdict-title");
    const verdictDetail  = $("#verdict-detail");
    const verdictGavel   = $("#verdict-gavel");
    const btnReplay      = $("#btn-replay");
    const btnDetails     = $("#btn-details");
    const btnHome        = $("#btn-home");

    // Report panel
    const reportPanel    = $("#report-panel");
    const reportContent  = $("#report-content");
    const btnCloseReport = $("#btn-close-report");

    // ── State ───────────────────────────────────────────────────
    let events       = [];
    let currentIndex = -1;
    let playing      = false;
    let timer        = null;

    const ACTORS = [
        "victim", "accused", "prosecutor", "defense",
        "textualist_judge", "evidence_judge", "burden_judge",
        "panel", "system"
    ];

    // Map event_type → which actor card lights up
    const EVENT_ACTOR_MAP = {
        case_start:            "system",
        victim_statement:      "victim",
        accused_statement:     "accused",
        prosecutor_argument:   "prosecutor",
        defense_argument:      "defense",
        evidence_presented:    "prosecutor",
        judge_question:        null,        // uses event.actor
        judge_thinking:        null,
        panel_deliberation:    "panel",
        judge_vote:            null,
        verdict_delivered:     "panel",
        strategy_presented:    "system",
        explanation_displayed: "system",
        hearing_feedback:      "panel",
        hearing_update:        "system",
    };

    // ── Initialise ──────────────────────────────────────────────
    function init() {
        if (typeof SIMULATION_EVENTS !== "undefined" && SIMULATION_EVENTS.events) {
            events = SIMULATION_EVENTS.events;
        } else if (Array.isArray(SIMULATION_EVENTS)) {
            events = SIMULATION_EVENTS;
        } else {
            events = [];
        }
        eventCounter.textContent = `0 / ${events.length}`;
        statusBadge.textContent  = "Ready";
        setAllIdle();
        renderUploadedEvidence();
        bindControls();
    }

    function bindControls() {
        btnPlay.addEventListener("click", togglePlay);
        btnNext.addEventListener("click", stepForward);
        btnPrev.addEventListener("click", stepBack);
        btnRestart.addEventListener("click", restart);
        btnBack.addEventListener("click", () => window.location.href = "/");
        speedSel.addEventListener("change", () => {
            if (playing) { clearInterval(timer); startTimer(); }
        });

        btnReplay.addEventListener("click", () => {
            verdictOverlay.classList.add("hidden");
            restart();
        });
        btnDetails.addEventListener("click", showReport);
        btnHome.addEventListener("click", () => window.location.href = "/");
        btnCloseReport.addEventListener("click", () => reportPanel.classList.add("hidden"));
    }

    // ── Playback ────────────────────────────────────────────────
    function togglePlay() {
        if (playing) { pause(); } else { play(); }
    }

    function play() {
        if (currentIndex >= events.length - 1) restart();
        playing = true;
        btnPlay.innerHTML = "&#9646;&#9646; Pause";
        statusBadge.textContent = "In Session";
        statusBadge.className = "px-3 py-1 rounded-full text-sm font-semibold bg-green-600";
        startTimer();
    }

    function pause() {
        playing = false;
        clearInterval(timer);
        btnPlay.innerHTML = "&#9654; Play";
        statusBadge.textContent = "Paused";
        statusBadge.className = "px-3 py-1 rounded-full text-sm font-semibold bg-yellow-600";
    }

    function startTimer() {
        const speed = parseInt(speedSel.value, 10);
        timer = setInterval(() => {
            if (currentIndex < events.length - 1) {
                stepForward();
            } else {
                pause();
                statusBadge.textContent = "Complete";
                statusBadge.className = "px-3 py-1 rounded-full text-sm font-semibold bg-blue-600";
            }
        }, speed);
    }

    function stepForward() {
        if (currentIndex >= events.length - 1) return;
        currentIndex++;
        renderEvent(events[currentIndex]);
        updateProgress();
    }

    function stepBack() {
        if (currentIndex <= 0) return;
        // Replay from the start up to currentIndex-1
        const target = currentIndex - 1;
        resetUI();
        for (let i = 0; i <= target; i++) {
            renderEvent(events[i], true);
        }
        currentIndex = target;
        updateProgress();
    }

    function restart() {
        clearInterval(timer);
        playing = false;
        currentIndex = -1;
        resetUI();
        btnPlay.innerHTML = "&#9654; Play";
        statusBadge.textContent = "Ready";
        statusBadge.className = "px-3 py-1 rounded-full text-sm font-semibold bg-blue-600";
        eventCounter.textContent = `0 / ${events.length}`;
        progressBar.style.width = "0%";
        verdictOverlay.classList.add("hidden");
    }

    function updateProgress() {
        const pct = events.length ? ((currentIndex + 1) / events.length * 100) : 0;
        progressBar.style.width = pct + "%";
        eventCounter.textContent = `${currentIndex + 1} / ${events.length}`;
    }

    // ── Render a single event ───────────────────────────────────
    function renderEvent(evt, silent) {
        const actor  = EVENT_ACTOR_MAP[evt.event_type] || evt.actor || "system";
        const type   = evt.event_type;
        const msg    = evt.message || "";

        // Reset previous active states (unless replaying silently)
        if (!silent) setAllIdle();

        // Animate actor card
        setActorState(actor, getStateForType(type));

        // Speech bubble
        setSpeech(actor, msg, silent);

        // Event log entry
        addLogEntry(evt, silent);

        // Type-specific rendering
        switch (type) {
            case "evidence_presented":
                addEvidenceCard(msg);
                break;
            case "judge_vote":
                showJudgeVote(evt);
                break;
            case "verdict_delivered":
                if (!silent) showVerdict(evt);
                break;
        }
    }

    // ── Actor state management ──────────────────────────────────
    function setAllIdle() {
        ACTORS.forEach(a => {
            const card = $(`#card-${a}`);
            if (card) {
                card.classList.remove("speaking", "thinking", "voting");
                card.classList.add("idle");
            }
            const st = $(`#state-${a}`);
            if (st) st.textContent = "Idle";
        });
    }

    function setActorState(actor, state) {
        const card = $(`#card-${actor}`);
        if (!card) return;
        card.classList.remove("idle", "speaking", "thinking", "voting");
        card.classList.add(state);
        const st = $(`#state-${actor}`);
        if (st) st.textContent = capitalize(state);
    }

    function getStateForType(type) {
        if (type === "judge_thinking" || type === "panel_deliberation") return "thinking";
        if (type === "judge_vote") return "voting";
        return "speaking";
    }

    // ── Speech bubbles ──────────────────────────────────────────
    function setSpeech(actor, message, silent) {
        const container = $(`#speech-${actor}`);
        if (!container) return;

        // Clear old speech
        container.innerHTML = "";

        if (!message) return;

        const bubble = document.createElement("div");
        bubble.className = "speech-bubble";
        bubble.textContent = truncate(message, 300);
        if (!silent) bubble.style.animation = "fadeSlideIn 0.4s ease";
        container.appendChild(bubble);
    }

    // ── Evidence board ──────────────────────────────────────────
    function addEvidenceCard(message) {
        const board = $("#evidence-board");
        if (!board) return;
        const card = document.createElement("div");
        card.className = "evidence-card bg-gray-700 rounded p-2 text-xs";
        card.textContent = truncate(message, 150);
        board.appendChild(card);
        board.scrollTop = board.scrollHeight;
    }

    // ── Judge vote badges ───────────────────────────────────────
    function mapVerdict(raw) {
        const v = (raw || "").toLowerCase().trim();
        if (v.includes("not guilty") || v === "acquit" || v === "acquitted") return {label: "Not Guilty", guilty: false};
        if (v.includes("guilty") || v === "convict" || v === "convicted") return {label: "Guilty", guilty: true};
        if (v === "review" || v.includes("further review")) return {label: "Review", guilty: false};
        return {label: raw || "Unknown", guilty: false};
    }

    function showJudgeVote(evt) {
        const actor = evt.actor || "";
        const container = $(`#vote-${actor}`);
        if (!container) return;

        const raw = (evt.metadata && evt.metadata.vote) ||
                    (evt.message || "");
        const v = mapVerdict(raw);

        container.innerHTML = `<span class="vote-badge ${v.guilty ? 'vote-guilty' : 'vote-not-guilty'}">
            ${v.label}
        </span>`;
    }

    // ── Verdict overlay ─────────────────────────────────────────
    function showVerdict(evt) {
        const msg = evt.message || "";
        const raw = (evt.metadata && evt.metadata.majority_verdict) || msg;
        const v = mapVerdict(raw);

        verdictTitle.textContent = v.label.toUpperCase();
        verdictTitle.className = `text-3xl font-bold mb-4 ${v.guilty ? 'text-red-400' : 'text-green-400'}`;
        verdictDetail.textContent = truncate(msg, 500);
        verdictGavel.className = "text-6xl mb-4 gavel-anim";
        verdictOverlay.classList.remove("hidden");
    }

    // ── Event log ───────────────────────────────────────────────
    function addLogEntry(evt, silent) {
        const log = $("#event-log");
        if (!log) return;

        const entry = document.createElement("div");
        entry.className = `timeline-item rounded p-2 ${silent ? 'past' : 'active'}`;

        const label = formatEventType(evt.event_type);
        const actor = evt.actor || "system";
        const msg   = truncate(evt.message || "", 200);

        entry.innerHTML = `
            <span class="text-gray-400 text-xs">${label}</span>
            <span class="text-cyan-400 text-xs font-bold ml-2">${capitalize(actor)}</span>
            <p class="mt-1 text-gray-200">${escapeHtml(msg)}</p>
        `;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;

        // Mark previous entries as past
        if (!silent) {
            log.querySelectorAll(".timeline-item.active").forEach((el, i, arr) => {
                if (i < arr.length - 1) {
                    el.classList.remove("active");
                    el.classList.add("past");
                }
            });
        }
    }

    // ── Full report panel ───────────────────────────────────────
    function showReport() {
        verdictOverlay.classList.add("hidden");
        reportPanel.classList.remove("hidden");

        let html = "";
        const r = (typeof CASE_RESULT !== "undefined") ? CASE_RESULT : {};

      try {

        // Uploaded Evidence Metadata
        if (Array.isArray(r.uploaded_evidence) && r.uploaded_evidence.length) {
            const rows = r.uploaded_evidence.map(file => `
                <tr class="border-b border-gray-700">
                    <td class="py-1 px-2">${esc(file.filename || '')}</td>
                    <td class="py-1 px-2">${esc(file.file_type || 'unknown')}</td>
                </tr>
            `).join('');
            html += section("Uploaded Evidence", `
                <table class="w-full text-sm">
                    <thead><tr class="text-gray-400 border-b border-gray-600">
                        <th class="text-left py-1 px-2">Filename</th>
                        <th class="text-left py-1 px-2">File Type</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            `);
        }

        // Element Status Panel
        if (r.case_analysis && r.case_analysis.evaluation_result) {
            const er = r.case_analysis.evaluation_result;
            const elements = er.element_details || [];
            let elRows = "";
            elements.forEach(el => {
                const met = (el.status === 'satisfied') || (el.satisfied === true);
                const icon = met ? '✔' : '✖';
                const color = met ? 'text-green-400' : 'text-red-400';
                const facts = (el.matching_fact_ids || []).length;
                elRows += `<tr class="border-b border-gray-700">
                    <td class="py-1 px-2">${esc(el.element_id || '').replace(/_/g, ' ')}</td>
                    <td class="py-1 px-2 text-center ${color} font-bold">${icon}</td>
                    <td class="py-1 px-2 text-center">${facts}</td>
                    <td class="py-1 px-2 text-center">${el.weight !== undefined ? el.weight.toFixed(2) : 'N/A'}</td>
                </tr>`;
            });
            html += section("Element Status — IPC " + esc(er.section || ''), `
                <table class="w-full text-sm">
                    <thead><tr class="text-gray-400 border-b border-gray-600">
                        <th class="text-left py-1 px-2">Element</th>
                        <th class="py-1 px-2">Status</th>
                        <th class="py-1 px-2">Facts</th>
                        <th class="py-1 px-2">Weight</th>
                    </tr></thead>
                    <tbody>${elRows}</tbody>
                </table>
                <p class="mt-2 text-sm"><strong>Section:</strong> ${esc(er.section)} &nbsp;|&nbsp;
                <strong>Confidence:</strong> ${esc(String(er.confidence_score || r.case_analysis.burden_result?.confidence_score || 'N/A'))}</p>
            `);
        }

        // Confidence Explanation
        if (r.case_analysis && r.case_analysis.burden_result) {
            const br = r.case_analysis.burden_result;
            html += section("Confidence & Burden Analysis", `
                <p><strong>Burden Stage:</strong> ${esc(br.burden_stage || 'N/A')}</p>
                <p><strong>Confidence Score:</strong> ${esc(String(br.confidence_score || 'N/A'))}</p>
                <p><strong>Burden Met:</strong> ${(br.burden_met || br.burden_stage === 'prima_facie_established') ? '<span class="text-green-400">Yes</span>' : '<span class="text-red-400">No</span>'}</p>
                ${(br.reasoning || (br.reasoning_flags && br.reasoning_flags.length)) ? '<p class="mt-2 text-sm text-gray-300">' + esc(br.reasoning || br.reasoning_flags.join(', ')) + '</p>' : ''}
            `);
        }
        if (r.case_analysis && r.case_analysis.evidence_weight_result) {
            const ew = r.case_analysis.evidence_weight_result;
            html += section("Evidence Weight Analysis", `
                <p><strong>Overall Evidence Score:</strong> ${esc(String(ew.overall_evidence_score || 'N/A'))}</p>
                ${(ew.per_element_scores || ew.element_scores) ? '<div class="mt-2">' + Object.entries(ew.per_element_scores || ew.element_scores).map(([k,v]) => 
                    '<span class="inline-block bg-gray-800 rounded px-2 py-1 text-xs mr-1 mb-1">' + esc(k.replace(/_/g,' ')) + ': ' + (typeof v === 'number' ? v.toFixed(2) : v) + '</span>'
                ).join('') + '</div>' : ''}
            `);
        }

        // Research Results
        if (r.research_data) {
            const rd = r.research_data;
            let resHtml = '';
            if (rd.precedents && rd.precedents.length) {
                resHtml += '<h4 class="font-semibold text-cyan-400 mb-1">Precedent Cases</h4><ul class="list-disc list-inside text-sm space-y-1">';
                rd.precedents.forEach(p => {
                    resHtml += '<li>' + esc(p.title || p.case_name || p.name || JSON.stringify(p)) + '</li>';
                });
                resHtml += '</ul>';
            }
            if ((rd.context && rd.context.length) || (rd.recent_context && rd.recent_context.length)) {
                const ctxItems = rd.recent_context || rd.context || [];
                resHtml += '<h4 class="font-semibold text-cyan-400 mt-2 mb-1">Context / Web Results</h4><ul class="list-disc list-inside text-sm space-y-1">';
                ctxItems.forEach(c => {
                    resHtml += '<li>' + esc(c.title || c.snippet || JSON.stringify(c)) + '</li>';
                });
                resHtml += '</ul>';
            }
            if (!resHtml) resHtml = '<p class="text-gray-400 text-sm">No research data available (API keys not set).</p>';
            html += section("Research Results", resHtml);
        }

        // Strategy Display
        if (r.strategy_report) {
            const sr = r.strategy_report;
            let stratHtml = `<div class="grid grid-cols-2 gap-4 text-sm">`;
            stratHtml += `<div><h4 class="font-semibold text-red-400 mb-1">Prosecution Strategy</h4><ul class="list-disc list-inside space-y-1">`;
            (sr.prosecution_strategy || []).forEach(s => { stratHtml += '<li>' + esc(s) + '</li>'; });
            stratHtml += '</ul></div>';
            stratHtml += `<div><h4 class="font-semibold text-blue-400 mb-1">Defense Strategy</h4><ul class="list-disc list-inside space-y-1">`;
            (sr.defense_strategy || []).forEach(s => { stratHtml += '<li>' + esc(s) + '</li>'; });
            stratHtml += '</ul></div></div>';
            if (sr.conviction_probability_estimate !== undefined) {
                const prob = (sr.conviction_probability_estimate * 100).toFixed(1);
                const color = sr.conviction_probability_estimate > 0.6 ? 'text-red-400' : sr.conviction_probability_estimate > 0.3 ? 'text-yellow-400' : 'text-green-400';
                stratHtml += `<p class="mt-2"><strong>Conviction Probability:</strong> <span class="${color} font-bold">${prob}%</span></p>`;
            }
            if (sr.risk_level) {
                stratHtml += `<p><strong>Risk Level:</strong> ${esc(sr.risk_level)}</p>`;
            }
            if (sr.weak_elements && sr.weak_elements.length) {
                stratHtml += '<p class="mt-1 text-yellow-400 text-sm"><strong>Weak Elements:</strong> ' + sr.weak_elements.map(e => esc(String(e.element_id || e).replace(/_/g,' '))).join(', ') + '</p>';
            }
            if (sr.strong_elements && sr.strong_elements.length) {
                stratHtml += '<p class="text-green-400 text-sm"><strong>Strong Elements:</strong> ' + sr.strong_elements.map(e => esc(String(e.element_id || e).replace(/_/g,' '))).join(', ') + '</p>';
            }
            html += section("Strategy Analysis", stratHtml);
        }

        // Panel Deliberation
        if (r.panel_result) {
            const pr = r.panel_result;
            let panelHtml = `<p><strong>Majority Verdict:</strong> ${esc(pr.majority_verdict || 'N/A').toUpperCase()}</p>`;
            panelHtml += `<p><strong>Vote Split:</strong> ${esc(pr.vote_split || 'N/A')}</p>`;
            if (pr.judges && pr.judges.length) {
                panelHtml += '<div class="mt-2 space-y-2">';
                pr.judges.forEach(j => {
                    const vColor = (j.provisional_verdict || '').toLowerCase() === 'convict' ? 'text-red-400' : 'text-green-400';
                    panelHtml += `<div class="bg-gray-800 rounded p-2"><strong>${esc(j.judge_type || 'Judge')}:</strong> <span class="${vColor}">${esc(j.provisional_verdict || 'N/A')}</span>`;
                    if (j.key_reasoning_points && j.key_reasoning_points.length) {
                        panelHtml += '<ul class="list-disc list-inside text-xs mt-1">';
                        j.key_reasoning_points.forEach(p => { panelHtml += '<li>' + esc(p) + '</li>'; });
                        panelHtml += '</ul>';
                    }
                    panelHtml += '</div>';
                });
                panelHtml += '</div>';
            }
            html += section("Panel Deliberation", panelHtml);
        }

        // Final Judgment
        if (r.final_judgment) {
            html += section("Final Judgment", `<pre class="whitespace-pre-wrap text-xs">${esc(r.final_judgment)}</pre>`);
        }

        // Explanation
        if (r.explanation) {
            html += section("Case Explanation", `<pre class="whitespace-pre-wrap text-xs">${esc(typeof r.explanation === 'string' ? r.explanation : JSON.stringify(r.explanation, null, 2))}</pre>`);
        }

        // Guardrail Report
        if (r.guardrail_report) {
            const gr = r.guardrail_report;
            const violations = gr.violations || [];
            const isSafe = violations.length === 0 && gr.lawyer_valid !== false && gr.judgment_valid !== false;
            let grHtml = `<p><strong>Safe:</strong> ${isSafe ? '<span class="text-green-400">Yes</span>' : '<span class="text-red-400">No</span>'}</p>`;
            if (violations.length) {
                grHtml += '<ul class="list-disc list-inside text-sm text-yellow-400 mt-1">';
                violations.forEach(w => { grHtml += '<li>' + esc(w) + '</li>'; });
                grHtml += '</ul>';
            }
            html += section("Guardrail Report", grHtml);
        }

        reportContent.innerHTML = html;
      } catch (err) {
        console.error("showReport error:", err);
        reportContent.innerHTML = '<p class="text-red-400 font-bold">Error rendering report: ' + err.message + '</p><pre class="text-xs text-gray-400 mt-2">' + err.stack + '</pre>';
      }
    }

    function section(title, body) {
        return `<div class="bg-gray-900 rounded-lg p-4">
            <h3 class="font-bold text-lg mb-2">${title}</h3>${body}
        </div>`;
    }

    // ── Helpers ──────────────────────────────────────────────────
    function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ") : ""; }
    function truncate(s, n) { return s.length > n ? s.slice(0, n) + "..." : s; }
    function formatEventType(t) { return (t || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()); }

    function escapeHtml(s) {
        const d = document.createElement("div");
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }
    const esc = escapeHtml;

    function resetUI() {
        setAllIdle();
        ACTORS.forEach(a => {
            const sp = $(`#speech-${a}`);
            if (sp) sp.innerHTML = "";
            const vt = $(`#vote-${a}`);
            if (vt) vt.innerHTML = "";
        });
        const log = $("#event-log");
        if (log) log.innerHTML = "";
        const board = $("#evidence-board");
        if (board) board.innerHTML = "";
        renderUploadedEvidence();
    }

    function renderUploadedEvidence() {
        const board = $("#evidence-board");
        if (!board) return;
        const r = (typeof CASE_RESULT !== "undefined") ? CASE_RESULT : {};
        const uploaded = Array.isArray(r.uploaded_evidence) ? r.uploaded_evidence : [];

        uploaded.forEach(file => {
            const card = document.createElement("div");
            card.className = "evidence-card bg-gray-700 rounded p-2 text-xs";
            const name = file.filename || "Unnamed evidence";
            const type = file.file_type || "unknown";
            card.textContent = `${name} (${type})`;
            board.appendChild(card);
        });
    }

    // ── Boot ────────────────────────────────────────────────────
    document.addEventListener("DOMContentLoaded", init);
})();

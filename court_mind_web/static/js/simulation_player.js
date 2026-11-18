/**
 * CourtMind — Simulation Player
 *
 * Steps through the simulation events produced by the backend and drives the
 * courtroom UI: actor cards, spotlight, timeline scrubber, court record,
 * evidence archive, verdict modal and the full report drawer.
 */
(function () {
    "use strict";

    const $ = (s, r) => (r || document).querySelector(s);
    const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

    const RAW_EVENTS = window.SIMULATION_EVENTS;
    const R = window.CASE_RESULT || {};
    const events = Array.isArray(RAW_EVENTS) ? RAW_EVENTS : (RAW_EVENTS && RAW_EVENTS.events) || [];

    const ACTORS = ["victim", "accused", "prosecutor", "defense", "textualist_judge", "evidence_judge", "burden_judge", "panel"];
    const ACTOR_LABEL = {
        system: "Court Clerk", victim: "Victim", accused: "Accused", prosecutor: "Prosecution",
        defense: "Defence", textualist_judge: "Textualist Judge", evidence_judge: "Evidence Judge",
        burden_judge: "Burden Judge", panel: "Panel",
    };
    const ACTOR_COLOR = {
        system: "var(--muted)", victim: "var(--red)", accused: "var(--amber)", prosecutor: "#ff8a65",
        defense: "var(--blue)", textualist_judge: "var(--gold)", evidence_judge: "var(--cyan)",
        burden_judge: "var(--violet)", panel: "var(--gold-strong)",
    };
    const EVENT_ACTOR_MAP = {
        case_start: "system", victim_statement: "victim", accused_statement: "accused",
        prosecutor_argument: "prosecutor", defense_argument: "defense", evidence_presented: "prosecutor",
        panel_deliberation: "panel", verdict_delivered: "panel", strategy_presented: "system",
        explanation_displayed: "system", hearing_feedback: "panel", hearing_update: "system",
    };
    const JUDGE_KEY = { textualist: "textualist_judge", evidence_focused: "evidence_judge", burden_strict: "burden_judge" };

    // ── State ───────────────────────────────────────────────────────
    let idx = -1;
    let playing = false;
    let timer = null;
    let typeTimer = null;
    let speed = 1900;
    let verdictShown = false;

    // ── Helpers ─────────────────────────────────────────────────────
    const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const human = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const clean = (s) => String(s || "").replace(/-{3,}/g, " ").replace(/\s+/g, " ").trim();
    const pct = (n) => (typeof n === "number" ? Math.round(n * 100) + "%" : "—");
    const actorOf = (e) => EVENT_ACTOR_MAP[e.event_type] || e.actor || "system";
    const fmtSplit = (s) => /^\d+$/.test(String(s || "")) ? `Unanimous ${s}–0` : (s || "—");
    const stripMd = (s) => String(s || "").replace(/[#*`]/g, "").replace(/\s+/g, " ").trim();

    function mapVerdict(raw) {
        const v = String(raw || "").toLowerCase().trim();
        if (v.includes("not guilty") || v.startsWith("acquit")) return { label: "Not Guilty", cls: "innocent" };
        if (v.includes("review")) return { label: "Further Review", cls: "review" };
        if (v.includes("guilty") || v.startsWith("convict")) return { label: "Guilty", cls: "guilty" };
        return { label: raw || "Undecided", cls: "review" };
    }

    function stateFor(type) {
        if (type === "judge_thinking" || type === "panel_deliberation") return "thinking";
        if (type === "judge_vote") return "voting";
        return "speaking";
    }

    // ── Header ──────────────────────────────────────────────────────
    function renderHeader() {
        const ca = R.case_analysis || {};
        const er = ca.evaluation_result || {};
        const br = ca.burden_result || {};
        const sr = R.strategy_report || {};
        const section = er.section || (R.lawyer_output && R.lawyer_output.confirmed_section) || "";
        $("#case-title").textContent = section ? `${section}${er.section_title ? " · " + er.section_title : ""}` : "Courtroom simulation";
        document.title = `CourtMind — ${section || "Courtroom"}`;

        const meta = [];
        if (br.burden_stage) meta.push(`<span class="pill">Burden: ${esc(human(br.burden_stage))}</span>`);
        if (sr.risk_level) meta.push(`<span class="pill">Risk: ${esc(human(sr.risk_level))}</span>`);
        const alts = (R.lawyer_output && R.lawyer_output.alternate_sections) || [];
        if (alts.length) meta.push(`<span class="pill">Also considered: ${esc(alts.join(", "))}</span>`);
        $("#case-meta").innerHTML = meta.join("");

        const req = (er.elements_required || []).length;
        const sat = (er.elements_satisfied || []).length;
        const stats = [
            ["Elements met", req ? `${sat}/${req}` : "—"],
            ["Confidence", pct(br.confidence_score)],
            ["Conviction est.", pct(sr.conviction_probability_estimate)],
            ["Events", String(events.length)],
        ];
        $("#case-stats").innerHTML = stats.map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${esc(v)}</div></div>`).join("");
    }

    // ── Scrubber ────────────────────────────────────────────────────
    function buildScrubber() {
        const dots = $("#scrubber-dots");
        const n = events.length;
        dots.innerHTML = "";
        events.forEach((e, i) => {
            const d = document.createElement("span");
            d.className = "scrubber-dot";
            d.style.left = n > 1 ? (i / (n - 1)) * 100 + "%" : "50%";
            d.style.setProperty("--c", ACTOR_COLOR[actorOf(e)] || "var(--muted)");
            d.dataset.i = i;
            dots.appendChild(d);
        });
        const scrub = $("#scrubber");
        const tip = $("#scrubber-tip");
        const indexAt = (x) => {
            const r = scrub.getBoundingClientRect();
            const f = Math.min(1, Math.max(0, (x - r.left) / r.width));
            return Math.round(f * (n - 1));
        };
        scrub.addEventListener("mousemove", (ev) => {
            if (!n) return;
            const i = indexAt(ev.clientX);
            tip.textContent = `${i + 1}. ${human(events[i].event_type)}`;
            tip.style.left = (n > 1 ? (i / (n - 1)) * 100 : 50) + "%";
            tip.classList.add("show");
        });
        scrub.addEventListener("mouseleave", () => tip.classList.remove("show"));
        scrub.addEventListener("click", (ev) => { if (n) { pause(); goTo(indexAt(ev.clientX), true); } });
        scrub.addEventListener("keydown", (ev) => {
            if (ev.key === "ArrowRight") { ev.preventDefault(); ev.stopPropagation(); pause(); step(1); }
            if (ev.key === "ArrowLeft") { ev.preventDefault(); ev.stopPropagation(); pause(); step(-1); }
        });
    }

    function updateProgress() {
        const n = events.length;
        const p = n ? ((idx + 1) / n) * 100 : 0;
        $("#progress-fill").style.width = (n > 1 ? Math.max(0, idx) / (n - 1) * 100 : p) + "%";
        $("#event-counter").textContent = `${idx + 1} / ${n}`;
        $("#scrubber").setAttribute("aria-valuenow", String(idx + 1));
        $("#scrubber").setAttribute("aria-valuemax", String(n));
        $$(".scrubber-dot").forEach((d, i) => {
            d.classList.toggle("past", i < idx);
            d.classList.toggle("current", i === idx);
        });
    }

    // ── Status ──────────────────────────────────────────────────────
    function setStatus(kind, text) {
        const b = $("#status-badge");
        b.className = `pill status-pill ${kind}`;
        $("#status-text").textContent = text;
    }

    // ── Rendering ───────────────────────────────────────────────────
    function resetStage() {
        ACTORS.forEach(a => {
            const c = $(`#card-${a}`);
            if (c) c.classList.remove("speaking", "thinking", "voting", "has-vote");
            const st = $(`#state-${a}`); if (st) st.textContent = "Idle";
            const sp = $(`#speech-${a}`); if (sp) sp.textContent = "";
            const vt = $(`#vote-${a}`); if (vt) vt.innerHTML = "";
        });
        $("#event-log").innerHTML = "";
        renderEvidenceBase();
    }

    function applyEvent(e, i) {
        const actor = actorOf(e);
        const sp = $(`#speech-${actor}`);
        if (sp) sp.textContent = stripMd(e.message);

        if (e.event_type === "judge_vote") {
            const slot = $(`#vote-${e.actor}`);
            const v = mapVerdict((e.metadata && e.metadata.vote) || e.message);
            if (slot) slot.innerHTML = `<span class="vote ${v.cls}">${esc(v.label)}</span>`;
            const card = $(`#card-${e.actor}`); if (card) card.classList.add("has-vote");
        }
        if (e.event_type === "evidence_presented") addEvidence("🧾", e.message);
        addLog(e, i);
    }

    function highlight(e) {
        ACTORS.forEach(a => {
            const c = $(`#card-${a}`); if (c) c.classList.remove("speaking", "thinking", "voting");
            const st = $(`#state-${a}`); if (st && st.textContent !== "Idle") st.textContent = "Done";
        });
        const actor = actorOf(e);
        const card = $(`#card-${actor}`);
        const state = stateFor(e.event_type);
        if (card) {
            card.classList.add(state);
            const st = $(`#state-${actor}`); if (st) st.textContent = human(state);
        }
    }

    function spotlight(e, animate) {
        const actor = actorOf(e);
        const spot = $("#spotlight");
        spot.style.setProperty("--c", ACTOR_COLOR[actor] || "var(--gold)");
        $("#spot-type").textContent = human(e.event_type);
        $("#spot-who").textContent = ACTOR_LABEL[actor] || human(actor);
        $("#spot-empty").classList.add("hidden");
        const el = $("#spot-text");
        const text = stripMd(e.message);
        clearInterval(typeTimer);

        if (!animate || speed <= 400) { el.textContent = text; return; }
        el.textContent = "";
        const caret = document.createElement("span"); caret.className = "caret";
        const node = document.createTextNode("");
        el.append(node, caret);
        let k = 0;
        const perChar = Math.max(6, Math.min(22, (speed * 0.6) / Math.max(1, text.length)));
        typeTimer = setInterval(() => {
            k += 2;
            node.textContent = text.slice(0, k);
            if (k >= text.length) { clearInterval(typeTimer); caret.remove(); }
        }, perChar);
    }

    function addLog(e, i) {
        const log = $("#event-log");
        const actor = actorOf(e);
        const b = document.createElement("button");
        b.type = "button";
        b.className = "log-item";
        b.dataset.i = i;
        b.style.setProperty("--c", ACTOR_COLOR[actor] || "var(--muted)");
        b.innerHTML = `<div class="log-meta"><span class="who">${esc(ACTOR_LABEL[actor] || human(actor))}</span><span class="t">${esc(human(e.event_type))}</span></div><div class="log-msg">${esc(stripMd(e.message))}</div>`;
        b.addEventListener("click", () => { pause(); goTo(i, true); });
        log.appendChild(b);
        $("#log-count").textContent = String(log.children.length);
    }

    function markCurrentLog() {
        const items = $$("#event-log .log-item");
        items.forEach(x => x.classList.remove("current"));
        const cur = items[items.length - 1];
        if (cur) {
            cur.classList.add("current");
            const box = $("#event-log");
            box.scrollTo({ top: cur.offsetTop - box.clientHeight / 2, behavior: "smooth" });
        }
    }

    function addEvidence(icon, text) {
        const board = $("#evidence-board");
        const empty = board.querySelector(".empty"); if (empty) empty.remove();
        const d = document.createElement("div");
        d.className = "evi";
        d.innerHTML = `<span class="ico">${icon}</span><span>${esc(clean(text))}</span>`;
        board.appendChild(d);
        $("#evidence-count").textContent = String(board.querySelectorAll(".evi").length);
    }

    function renderEvidenceBase() {
        const board = $("#evidence-board");
        board.innerHTML = "";
        const up = Array.isArray(R.uploaded_evidence) ? R.uploaded_evidence : [];
        up.forEach(f => {
            const t = String(f.file_type || "");
            const icon = t.startsWith("image") ? "🖼️" : t.startsWith("video") ? "🎞️" : "📄";
            addEvidence(icon, `${f.filename} (${t || "file"})`);
        });
        if (!up.length) {
            board.innerHTML = '<div class="empty">No evidence files attached.</div>';
            $("#evidence-count").textContent = "0";
        }
    }

    // Render the state for event `target` (rebuild from scratch, animate the last).
    function goTo(target, animate) {
        target = Math.max(-1, Math.min(events.length - 1, target));
        resetStage();
        for (let i = 0; i <= target; i++) applyEvent(events[i], i);
        idx = target;
        if (idx >= 0) {
            highlight(events[idx]);
            spotlight(events[idx], animate);
            markCurrentLog();
        } else {
            $("#spot-type").textContent = "Court is ready";
            $("#spot-who").textContent = "";
            $("#spot-text").textContent = "";
            $("#spot-empty").classList.remove("hidden");
            $("#log-count").textContent = "0";
            $("#event-log").innerHTML = '<div class="empty">The record is empty until the hearing starts.</div>';
        }
        updateProgress();
        if (idx === events.length - 1 && events.length) setStatus("done", "Adjourned");
    }

    function step(dir) {
        if (dir > 0 && idx >= events.length - 1) return;
        if (dir < 0 && idx <= 0) return;
        if (dir > 0) {
            // incremental forward step (no full rebuild) for smooth animation
            idx++;
            const e = events[idx];
            const empty = $("#event-log .empty"); if (empty) empty.remove();
            applyEvent(e, idx);
            highlight(e);
            spotlight(e, true);
            markCurrentLog();
            updateProgress();
            if (e.event_type === "verdict_delivered" && playing && !verdictShown) {
                verdictShown = true;
                pause();
                setTimeout(showVerdict, 700);
            }
            if (idx === events.length - 1) { pause(); setStatus("done", "Adjourned"); }
        } else {
            goTo(idx - 1, false);
        }
    }

    // ── Playback ────────────────────────────────────────────────────
    function play() {
        if (!events.length) return;
        if (idx >= events.length - 1) { goTo(-1); verdictShown = false; }
        playing = true;
        $("#btn-play").innerHTML = '❚❚ <span class="label">Pause</span>';
        setStatus("live", "In session");
        step(1);
        schedule();
    }
    function schedule() {
        clearInterval(timer);
        if (!playing) return;
        timer = setInterval(() => {
            if (idx < events.length - 1) step(1); else pause();
        }, speed);
    }
    function pause() {
        const was = playing;
        playing = false;
        clearInterval(timer);
        $("#btn-play").innerHTML = '▶ <span class="label">Play</span>';
        if (was && idx < events.length - 1) setStatus("paused", "Recess");
    }
    function toggle() { playing ? pause() : play(); }
    function restart() { pause(); verdictShown = false; closeModals(); goTo(-1); setStatus("ready", "Ready"); }
    function skipToVerdict() {
        pause();
        const vi = events.findIndex(e => e.event_type === "verdict_delivered");
        goTo(vi >= 0 ? vi : events.length - 1, false);
        verdictShown = true;
        showVerdict();
    }

    // ── Verdict ─────────────────────────────────────────────────────
    function showVerdict() {
        const pr = R.panel_result || {};
        const ve = events.find(e => e.event_type === "verdict_delivered");
        const raw = (ve && ve.metadata && ve.metadata.majority_verdict) || pr.majority_verdict || (ve && ve.message);
        const v = mapVerdict(raw);
        const title = $("#verdict-title");
        title.textContent = v.label;
        title.className = `verdict-title ${v.cls}`;
        const glow = { guilty: "rgba(240,97,109,.55)", innocent: "rgba(69,212,154,.5)", review: "rgba(245,184,74,.5)" }[v.cls];
        $(".verdict-card").style.setProperty("--vc", glow);
        $("#verdict-detail").textContent = pr.vote_split ? `Vote: ${fmtSplit(pr.vote_split)}` + (R.case_analysis && R.case_analysis.evaluation_result ? ` · ${R.case_analysis.evaluation_result.section}` : "") : stripMd(ve && ve.message);

        const judges = pr.judges || [];
        $("#verdict-votes").innerHTML = judges.map(j => {
            const jv = mapVerdict(j.provisional_verdict);
            const name = ACTOR_LABEL[JUDGE_KEY[j.judge_type]] || human(j.judge_type);
            return `<div class="jv"><div class="n">${esc(name)}</div><span class="vote ${jv.cls}">${esc(jv.label)}</span></div>`;
        }).join("");

        const p = (R.strategy_report || {}).conviction_probability_estimate;
        const gauge = $("#verdict-gauge");
        if (typeof p === "number") {
            gauge.classList.remove("hidden");
            $("#gauge-val").textContent = pct(p);
            const fill = $("#gauge-fill");
            fill.style.width = "0";
            fill.style.backgroundPosition = "0 0";
            requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = Math.round(p * 100) + "%"; }));
        } else gauge.classList.add("hidden");

        $("#verdict-overlay").classList.remove("hidden");
        const g = $("#verdict-gavel"); g.style.animation = "none"; void g.offsetWidth; g.style.animation = "";
        $("#btn-details").focus();
    }

    // ── Report ──────────────────────────────────────────────────────
    function sec(title, body) { return `<section class="rsec"><h3>${title}</h3>${body}</section>`; }
    function list(items) { return items && items.length ? `<ul class="list">${items.map(x => `<li>${esc(clean(x))}</li>`).join("")}</ul>` : '<p class="faint">None.</p>'; }
    function statBox(k, v) { return `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`; }

    function md(src) {
        const lines = String(src || "").split(/\r?\n/);
        let html = "", inList = false;
        const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
        lines.forEach(l => {
            const t = l.trim();
            if (/^[-*]\s+/.test(t)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(t.replace(/^[-*]\s+/, ""))}</li>`; return; }
            if (inList) { html += "</ul>"; inList = false; }
            if (/^#{1,6}\s/.test(t)) { const lvl = Math.min(4, t.match(/^#+/)[0].length + 1); html += `<h${lvl}>${inline(t.replace(/^#+\s*/, ""))}</h${lvl}>`; }
            else if (t) html += `<p>${inline(t)}</p>`;
        });
        if (inList) html += "</ul>";
        return html;
    }

    const REPORT_TABS = [
        ["overview", "Overview", reportOverview],
        ["elements", "Elements", reportElements],
        ["panel", "Panel", reportPanel],
        ["strategy", "Strategy", reportStrategy],
        ["research", "Research", reportResearch],
        ["judgment", "Judgment", reportJudgment],
        ["explanation", "Explanation", reportExplanation],
        ["guardrails", "Guardrails", reportGuardrails],
    ];

    function reportOverview() {
        const ca = R.case_analysis || {}, er = ca.evaluation_result || {}, br = ca.burden_result || {}, ew = ca.evidence_weight_result || {}, pr = R.panel_result || {}, sr = R.strategy_report || {};
        const v = mapVerdict(pr.majority_verdict);
        let h = sec("⚖ Summary", `<div class="kv">
            ${statBox("Section", er.section || "—")}
            ${statBox("Verdict", v.label)}
            ${statBox("Vote split", fmtSplit(pr.vote_split))}
            ${statBox("Burden stage", human(br.burden_stage || "—"))}
            ${statBox("Confidence", pct(br.confidence_score))}
            ${statBox("Evidence score", pct(ew.overall_evidence_score))}
            ${statBox("Conviction est.", pct(sr.conviction_probability_estimate))}
            ${statBox("Risk level", human(sr.risk_level || "—"))}
        </div>`);
        const ex = (ca.exception_result || {}).exceptions_detected || [];
        if (ex.length) {
            h += sec("🛡 Exceptions raised", `<table class="table"><thead><tr><th>Exception</th><th>Statement</th><th>Supported</th></tr></thead><tbody>${ex.map(x => `<tr><td>${esc(human(x.tag))}</td><td>${esc(clean(x.statement))}</td><td><span class="status-tag ${x.supported ? "ok" : "bad"}">${x.supported ? "Yes" : "No"}</span></td></tr>`).join("")}</tbody></table>`);
        }
        const up = R.uploaded_evidence || [];
        if (up.length) h += sec("📎 Uploaded evidence", `<table class="table"><thead><tr><th>File</th><th>Type</th></tr></thead><tbody>${up.map(f => `<tr><td>${esc(f.filename)}</td><td>${esc(f.file_type)}</td></tr>`).join("")}</tbody></table>`);
        return h;
    }

    function reportElements() {
        const ca = R.case_analysis || {}, er = ca.evaluation_result || {}, ew = ca.evidence_weight_result || {};
        const scores = ew.element_scores || ew.per_element_scores || {};
        const rows = (er.element_details || []).map(el => {
            const st = String(el.status || (el.satisfied ? "satisfied" : "not satisfied"));
            const cls = st === "satisfied" ? "ok" : st === "partial" || st === "conflicted" ? "mid" : "bad";
            const sc = scores[el.element_id];
            return `<tr>
                <td><strong>${esc(el.description || human(el.element_id))}</strong>${el.required === false ? ' <span class="faint">(optional)</span>' : ""}<div class="faint" style="font-size:12px">${esc((el.confidence_notes || []).join(" "))}</div></td>
                <td><span class="status-tag ${cls}">${esc(human(st))}</span></td>
                <td>${(el.matching_fact_ids || []).length}</td>
                <td>${typeof sc === "number" ? `<div class="bar"><span style="width:${Math.round(sc * 100)}%"></span></div>` : '<span class="faint">—</span>'}</td>
            </tr>`;
        }).join("");
        let h = sec(`📋 Elements of ${esc(er.section || "the offence")}`, rows ? `<div style="overflow-x:auto"><table class="table"><thead><tr><th>Element</th><th>Status</th><th>Facts</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="faint">No element data.</p>');
        const br = ca.burden_result || {};
        h += sec("⚖ Burden of proof", `<div class="kv">
            ${statBox("Stage", human(br.burden_stage || "—"))}
            ${statBox("Required met", br.required_elements_total != null ? `${br.required_elements_satisfied}/${br.required_elements_total}` : "—")}
            ${statBox("Conflicted", br.conflicted_elements != null ? String(br.conflicted_elements) : "—")}
            ${statBox("Confidence", pct(br.confidence_score))}
        </div>${(br.reasoning_flags || []).length ? `<div style="margin-top:12px">${list(br.reasoning_flags)}</div>` : ""}`);
        return h;
    }

    function reportPanel() {
        const pr = R.panel_result || {};
        const v = mapVerdict(pr.majority_verdict);
        let h = sec("🏛 Majority", `<div class="kv">${statBox("Verdict", v.label)}${statBox("Vote split", fmtSplit(pr.vote_split))}</div>`);
        (pr.judges || []).forEach(j => {
            const jv = mapVerdict(j.provisional_verdict);
            const name = ACTOR_LABEL[JUDGE_KEY[j.judge_type]] || human(j.judge_type);
            h += sec(`${esc(name)} <span class="vote ${jv.cls}" style="margin-left:auto">${esc(jv.label)}</span>`,
                `${list(j.key_reasoning_points)}${(j.concerns || []).length ? `<p class="faint" style="margin-top:10px;font-size:12px;text-transform:uppercase;letter-spacing:.08em">Concerns</p>${list(j.concerns)}` : ""}`);
        });
        const lo = R.lawyer_output || {};
        if (lo.prosecution_arguments || lo.defense_arguments) {
            h += sec("🗣 Arguments heard", `<div class="two-col"><div><p style="color:#ff8a65;font-weight:600;margin-bottom:6px">Prosecution</p>${list(lo.prosecution_arguments)}</div><div><p style="color:var(--blue);font-weight:600;margin-bottom:6px">Defence</p>${list(lo.defense_arguments)}</div></div>`);
        }
        return h;
    }

    function reportStrategy() {
        const sr = R.strategy_report || {};
        const p = sr.conviction_probability_estimate;
        let h = sec("🎯 Outlook", `<div class="kv">${statBox("Conviction est.", pct(p))}${statBox("Risk level", human(sr.risk_level || "—"))}</div>${typeof p === "number" ? `<div class="gauge-bar" style="margin-top:14px"><span style="width:${Math.round(p * 100)}%"></span></div>` : ""}`);
        h += sec("♟ Strategy", `<div class="two-col"><div><p style="color:#ff8a65;font-weight:600;margin-bottom:6px">Prosecution</p>${list(sr.prosecution_strategy)}</div><div><p style="color:var(--blue);font-weight:600;margin-bottom:6px">Defence</p>${list(sr.defense_strategy)}</div></div>`);
        const nm = (arr) => (arr || []).map(e => human(e.element_id || e));
        h += sec("📊 Element strength", `<div class="two-col"><div><p style="color:var(--green);font-weight:600;margin-bottom:6px">Strong</p>${list(nm(sr.strong_elements))}</div><div><p style="color:var(--amber);font-weight:600;margin-bottom:6px">Weak</p>${list(nm(sr.weak_elements))}</div></div>`);
        return h;
    }

    function reportResearch() {
        const rd = R.research_data || {};
        const items = (Array.isArray(rd.items) ? rd.items : []).concat(rd.precedents || [], rd.recent_context || rd.context || []);
        if (!items.length) return sec("🔎 Research", `<p class="muted">${esc(rd.message || "No precedents or recent context were found for this case. Add SERPER_API_KEY / KANOON_API_KEY to enable live research.")}</p>`);
        return sec("🔎 Precedents & context", items.map(it => {
            const title = it.title || it.case_name || it.name || "Untitled reference";
            const link = it.link || it.url || "";
            const safe = /^https?:\/\//i.test(link) ? link : "";
            const inner = `<div class="t">${esc(title)}</div><div class="s">${esc(it.source || it.court || "Research")}</div>${it.snippet || it.summary ? `<div class="x">${esc(it.snippet || it.summary)}</div>` : ""}`;
            return safe ? `<a class="ref" href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : `<div class="ref">${inner}</div>`;
        }).join(""));
    }

    function reportJudgment() {
        return R.final_judgment ? sec("📜 Final judgment", `<pre class="mono">${esc(R.final_judgment)}</pre>`) : sec("📜 Final judgment", '<p class="faint">Not available.</p>');
    }

    function reportExplanation() {
        const x = R.explanation;
        if (!x) return sec("💡 Explanation", '<p class="faint">Not available.</p>');
        return sec("💡 Explanation", typeof x === "string" ? `<div class="prose">${md(x)}</div>` : `<pre class="mono">${esc(JSON.stringify(x, null, 2))}</pre>`);
    }

    function reportGuardrails() {
        const g = R.guardrail_report || {};
        const vio = g.violations || [];
        const ok = !vio.length && g.lawyer_valid !== false && g.judgment_valid !== false;
        const yes = (b) => b === undefined ? "—" : b ? "Valid" : "Invalid";
        return sec(`🛡 Guardrails <span class="status-tag ${ok ? "ok" : "mid"}" style="margin-left:auto">${ok ? "All checks passed" : `${vio.length} issue(s)`}</span>`,
            `<div class="kv">${statBox("Lawyer output", yes(g.lawyer_valid))}${statBox("Judgment", yes(g.judgment_valid))}${statBox("Citations", yes(g.citation_valid))}</div>
             ${vio.length ? `<div style="margin-top:14px">${list(vio)}</div>` : ""}`);
    }

    function openReport(tab) {
        closeModals();
        const tabs = $("#report-tabs");
        tabs.innerHTML = REPORT_TABS.map(([id, label]) => `<button type="button" class="tab" role="tab" data-tab="${id}" aria-selected="false">${label}</button>`).join("");
        $$(".tab", tabs).forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
        $("#report-panel").classList.remove("hidden");
        document.body.style.overflow = "hidden";
        showTab(tab || "overview");
    }
    function showTab(id) {
        $$("#report-tabs .tab").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === id)));
        const t = REPORT_TABS.find(x => x[0] === id) || REPORT_TABS[0];
        let html;
        try { html = t[2](); } catch (err) { console.error(err); html = sec("Error", `<p class="muted">Could not render this section: ${esc(err.message)}</p>`); }
        const body = $("#report-content");
        body.innerHTML = html;
        body.scrollTop = 0;
    }
    function closeModals() {
        $("#verdict-overlay").classList.add("hidden");
        $("#report-panel").classList.add("hidden");
        document.body.style.overflow = "";
    }

    function printReport() {
        // Render every tab so the printout contains the full report.
        $("#report-content").innerHTML = REPORT_TABS.map(t => { try { return t[2](); } catch (e) { return ""; } }).join("");
        window.print();
    }

    function downloadJson() {
        const blob = new Blob([JSON.stringify(R, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        const sectionName = ((R.case_analysis || {}).evaluation_result || {}).section || "case";
        a.href = URL.createObjectURL(blob);
        a.download = `courtmind-${String(sectionName).replace(/\W+/g, "-").toLowerCase()}.json`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }

    // ── Wiring ──────────────────────────────────────────────────────
    function bind() {
        $("#btn-play").addEventListener("click", toggle);
        $("#btn-next").addEventListener("click", () => { pause(); step(1); });
        $("#btn-prev").addEventListener("click", () => { pause(); step(-1); });
        $("#btn-restart").addEventListener("click", restart);
        $("#btn-skip").addEventListener("click", skipToVerdict);
        $$("#speed button").forEach(b => b.addEventListener("click", () => {
            speed = parseInt(b.dataset.speed, 10);
            $$("#speed button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
            schedule();
        }));
        $("#btn-replay").addEventListener("click", () => { closeModals(); restart(); play(); });
        $("#btn-details").addEventListener("click", () => openReport("overview"));
        $("#btn-report-top").addEventListener("click", () => { pause(); openReport("overview"); });
        $("#btn-close-report").addEventListener("click", closeModals);
        $("#btn-print").addEventListener("click", printReport);
        $("#btn-download").addEventListener("click", downloadJson);
        $("#verdict-overlay").addEventListener("click", (e) => { if (e.target.id === "verdict-overlay") closeModals(); });
        $("#report-panel").addEventListener("click", (e) => { if (e.target.id === "report-panel") closeModals(); });

        document.addEventListener("keydown", (e) => {
            if (e.target.closest("input, textarea, select")) return;
            const modalOpen = !$("#verdict-overlay").classList.contains("hidden") || !$("#report-panel").classList.contains("hidden");
            if (e.key === "Escape") { closeModals(); return; }
            if (modalOpen) return;
            if (e.key === " " && !e.target.closest("button")) { e.preventDefault(); toggle(); }
            else if (e.key === "ArrowRight") { pause(); step(1); }
            else if (e.key === "ArrowLeft") { pause(); step(-1); }
            else if (e.key === "r" || e.key === "R") restart();
            else if (e.key === "v" || e.key === "V") skipToVerdict();
        });
    }

    function init() {
        renderHeader();
        buildScrubber();
        bind();
        goTo(-1);
        setStatus("ready", "Ready");
        if (!events.length) {
            $("#spot-empty").textContent = "No simulation events were produced for this case.";
        } else {
            // Start automatically after a short pause so the page feels alive.
            setTimeout(() => { if (idx === -1 && !playing) play(); }, 900);
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();

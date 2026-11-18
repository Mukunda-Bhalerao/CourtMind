/**
 * CourtMind — landing page interactions
 * Tabs, drag & drop, sample cases, evidence chips, loading overlay.
 */
(function () {
    "use strict";

    const $ = (s, r) => (r || document).querySelector(s);
    const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

    const form = $("#case-form");
    const textArea = $("#case-text-input");
    const textCount = $("#text-count");
    const fileInput = $("#case-file-input");
    const caseDrop = $("#case-drop");
    const evidenceInput = $("#evidence-files-input");
    const evidenceDrop = $("#evidence-drop");
    const chips = $("#evidence-chips");
    const loader = $("#loader");
    let activeTab = "paste";

    // ── Tabs ────────────────────────────────────────────────────────
    function selectTab(name) {
        activeTab = name;
        $$(".tab").forEach(t => t.setAttribute("aria-selected", String(t.id === "tab-" + name)));
        $("#pane-paste").classList.toggle("hidden", name !== "paste");
        $("#pane-upload").classList.toggle("hidden", name !== "upload");
        if (name === "paste") textArea.focus();
    }
    $("#tab-paste").addEventListener("click", () => selectTab("paste"));
    $("#tab-upload").addEventListener("click", () => selectTab("upload"));

    // ── Word counter ────────────────────────────────────────────────
    function updateCount() {
        const words = textArea.value.trim() ? textArea.value.trim().split(/\s+/).length : 0;
        textCount.textContent = `${words.toLocaleString()} word${words === 1 ? "" : "s"} · ${textArea.value.length.toLocaleString()} characters`;
    }
    textArea.addEventListener("input", updateCount);
    updateCount();

    // ── Case file drop zone ─────────────────────────────────────────
    function fmtSize(b) {
        if (b < 1024) return b + " B";
        if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
        return (b / 1024 / 1024).toFixed(1) + " MB";
    }

    function showChosenFile() {
        const f = fileInput.files[0];
        $("#case-drop-empty").classList.toggle("hidden", !!f);
        $("#case-drop-chosen").classList.toggle("hidden", !f);
        if (f) {
            $("#case-file-name").textContent = f.name;
            $("#case-file-size").textContent = fmtSize(f.size) + " · ready";
        }
    }
    fileInput.addEventListener("change", showChosenFile);

    $("#case-file-clear").addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        fileInput.value = "";
        showChosenFile();
    });

    function wireDrop(zone, input, onDrop) {
        ["dragenter", "dragover"].forEach(ev => zone.addEventListener(ev, (e) => {
            e.preventDefault();
            zone.classList.add("dragover");
        }));
        ["dragleave", "dragend", "drop"].forEach(ev => zone.addEventListener(ev, () => zone.classList.remove("dragover")));
        zone.addEventListener("drop", (e) => {
            e.preventDefault();
            if (e.dataTransfer && e.dataTransfer.files.length) onDrop(e.dataTransfer.files);
        });
    }

    wireDrop(caseDrop, fileInput, (files) => {
        const dt = new DataTransfer();
        dt.items.add(files[0]);
        fileInput.files = dt.files;
        showChosenFile();
    });

    // ── Evidence chips ──────────────────────────────────────────────
    let evidence = [];

    function syncEvidence() {
        const dt = new DataTransfer();
        evidence.forEach(f => dt.items.add(f));
        evidenceInput.files = dt.files;
        chips.innerHTML = "";
        evidence.forEach((f, i) => {
            const chip = document.createElement("span");
            chip.className = "chip";
            const icon = f.type.startsWith("image/") ? "🖼️" : f.type.startsWith("video/") ? "🎞️" : "📄";
            const label = document.createElement("span");
            label.textContent = `${icon} ${f.name}`;
            label.title = `${f.name} · ${fmtSize(f.size)}`;
            const rm = document.createElement("button");
            rm.type = "button";
            rm.setAttribute("aria-label", "Remove " + f.name);
            rm.textContent = "×";
            rm.addEventListener("click", () => { evidence.splice(i, 1); syncEvidence(); });
            chip.append(label, rm);
            chips.appendChild(chip);
        });
    }

    function addEvidence(fileList) {
        Array.from(fileList).forEach(f => {
            if (!evidence.some(e => e.name === f.name && e.size === f.size)) evidence.push(f);
        });
        syncEvidence();
    }

    evidenceInput.addEventListener("change", () => addEvidence(evidenceInput.files));
    wireDrop(evidenceDrop, evidenceInput, addEvidence);

    // ── Sample cases ────────────────────────────────────────────────
    function toast(msg) {
        const t = document.createElement("div");
        t.className = "toast";
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 2400);
    }

    async function loadSample(id, el) {
        if (el) el.classList.add("loading");
        try {
            const res = await fetch(`/api/samples/${encodeURIComponent(id)}`);
            if (!res.ok) throw new Error("not found");
            const data = await res.json();
            textArea.value = data.text;
            updateCount();
            selectTab("paste");
            $("#start").scrollIntoView({ behavior: "smooth", block: "start" });
            textArea.scrollTop = 0;
            toast("Sample case loaded. Edit it or begin the trial.");
        } catch (err) {
            toast("Could not load that sample.");
        } finally {
            if (el) el.classList.remove("loading");
        }
    }
    $$("[data-sample]").forEach(el => el.addEventListener("click", () => loadSample(el.dataset.sample, el)));

    // ── Submit + loading overlay ────────────────────────────────────
    let stepTimer = null;
    function startLoader() {
        loader.classList.remove("hidden");
        const steps = $$("#loader-steps li");
        let i = 0;
        steps.forEach(s => s.classList.remove("active", "done"));
        steps[0].classList.add("active");
        stepTimer = setInterval(() => {
            if (i < steps.length - 1) {
                steps[i].classList.remove("active");
                steps[i].classList.add("done");
                steps[i].querySelector(".ico").textContent = "✓";
                i++;
                steps[i].classList.add("active");
            }
        }, 900);
    }

    form.addEventListener("submit", (e) => {
        const hasFile = fileInput.files.length > 0;
        const hasText = textArea.value.trim().length > 0;
        const usingFile = activeTab === "upload" ? hasFile : (!hasText && hasFile);

        if (!usingFile && !hasText) {
            e.preventDefault();
            toast(activeTab === "upload" ? "Choose a case file first." : "Paste a case narrative or pick a sample.");
            return;
        }
        // Only send what the active tab shows.
        if (usingFile) textArea.value = "";
        else fileInput.value = "";

        startLoader();
        $("#btn-analyze").disabled = true;
    });

    // Back/forward cache: hide the overlay when returning to this page.
    window.addEventListener("pageshow", () => {
        loader.classList.add("hidden");
        clearInterval(stepTimer);
        $("#btn-analyze").disabled = false;
    });

    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    // ── Reveal on scroll ────────────────────────────────────────────
    if ("IntersectionObserver" in window) {
        const io = new IntersectionObserver((entries) => {
            entries.forEach((en, idx) => {
                if (en.isIntersecting) {
                    setTimeout(() => en.target.classList.add("in"), idx * 70);
                    io.unobserve(en.target);
                }
            });
        }, { threshold: 0.15 });
        $$(".reveal").forEach(el => io.observe(el));
    } else {
        $$(".reveal").forEach(el => el.classList.add("in"));
    }
})();

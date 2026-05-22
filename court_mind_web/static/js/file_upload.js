/**
 * CourtMind — File Upload Handler
 *
 * Uploads .txt / .pdf / .docx case files to /upload-case,
 * receives extracted text, and fills the case narrative textarea.
 */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const fileInput  = document.getElementById("case-file-input");
        const uploadBtn  = document.getElementById("btn-upload-case");
        const statusEl   = document.getElementById("upload-status");

        // The four textareas where extracted text can be placed
        const victimTA   = document.querySelector('textarea[name="victim"]');

        if (!fileInput || !uploadBtn) return;

        uploadBtn.addEventListener("click", async function () {
            const file = fileInput.files[0];
            if (!file) {
                showStatus("Please select a file first.", "text-yellow-400");
                return;
            }

            const allowed = [".txt", ".pdf", ".docx"];
            const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
            if (!allowed.includes(ext)) {
                showStatus("Unsupported file type. Use .txt, .pdf, or .docx.", "text-red-400");
                return;
            }

            showStatus("Uploading...", "text-blue-400");
            uploadBtn.disabled = true;

            try {
                const formData = new FormData();
                formData.append("file", file);

                const resp = await fetch("/upload-case", { method: "POST", body: formData });

                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ detail: "Upload failed" }));
                    showStatus(err.detail || "Upload failed", "text-red-400");
                    return;
                }

                const data = await resp.json();
                if (data.extracted_text && victimTA) {
                    victimTA.value = data.extracted_text;
                }
                showStatus("File parsed successfully! Text inserted into Victim Narrative.", "text-green-400");
            } catch (e) {
                showStatus("Network error: " + e.message, "text-red-400");
            } finally {
                uploadBtn.disabled = false;
            }
        });

        function showStatus(msg, cls) {
            if (!statusEl) return;
            statusEl.textContent = msg;
            statusEl.className = "text-sm mt-2 " + (cls || "");
        }
    });
})();

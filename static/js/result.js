// Shared AJAX submit + result renderer for the file-generation tools.
//
// Contract with the HTML:
//   <form data-async="1" data-preview="auto|image|pdf">
//     ...inputs...
//     <button type="submit" id="submitBtn">...</button>
//     <span id="busy" class="d-none"><spinner/></span>
//   </form>
//   <div id="errorBox" class="alert alert-danger mt-3 d-none"></div>
//   <div id="result" class="mt-4 d-none">
//     <div id="resultPreview"></div>
//     <code id="resultFilename"></code>
//     <span id="resultSize"></span>
//     <a id="downloadLink" download></a>
//     <a id="openLink" target="_blank" rel="noopener"></a>
//     <button id="resetBtn" type="button">...</button>
//   </div>
//
// Server contract:
//   Success: 200 + {ok: true, url, filename, size, mime}
//   Failure: 4xx/5xx + {error: "..."}   (or any JSON with an `error` field)
//
// data-preview="auto" picks image or pdf based on the response `mime`.

(function () {
  const PREVIEW_HTML = {
    image: (url, alt) =>
      `<a href="${url}" target="_blank" rel="noopener" class="d-inline-block">` +
      `<img src="${url}" alt="${escapeHtml(alt)}" ` +
      `class="img-fluid rounded border" style="max-height:160px;max-width:240px;object-fit:contain;"/>` +
      `</a>`,
    pdf: (url) =>
      `<a href="${url}" target="_blank" rel="noopener" class="d-inline-flex align-items-center justify-content-center bg-light border rounded"` +
      ` style="width:96px;height:120px;">` +
      `<i class="bi bi-file-earmark-pdf text-danger" style="font-size:48px;"></i>` +
      `</a>`,
    other: (url) =>
      `<a href="${url}" target="_blank" rel="noopener" class="d-inline-flex align-items-center justify-content-center bg-light border rounded"` +
      ` style="width:96px;height:120px;">` +
      `<i class="bi bi-file-earmark-arrow-down text-secondary" style="font-size:40px;"></i>` +
      `</a>`,
  };

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function humanSize(n) {
    if (typeof n !== "number" || !isFinite(n) || n < 0) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function pickMode(prefer, mime) {
    if (prefer === "image" || prefer === "pdf" || prefer === "other") return prefer;
    if (!mime) return "other";
    if (mime.startsWith("image/")) return "image";
    if (mime === "application/pdf") return "pdf";
    return "other";
  }

  function setup(form) {
    const errorBox = document.getElementById("errorBox");
    const result = document.getElementById("result");
    if (!result || !errorBox) return;

    const previewSlot = document.getElementById("resultPreview");
    const filenameEl = document.getElementById("resultFilename");
    const sizeEl = document.getElementById("resultSize");
    const downloadLink = document.getElementById("downloadLink");
    const openLink = document.getElementById("openLink");
    const resetBtn = document.getElementById("resetBtn");
    const submitBtn = form.querySelector('[type="submit"]') || document.getElementById("submitBtn");
    const busy = document.getElementById("busy");

    const prefer = form.dataset.preview || "auto";

    function showError(msg) {
      errorBox.textContent = msg;
      errorBox.classList.remove("d-none");
    }
    function clearError() {
      errorBox.textContent = "";
      errorBox.classList.add("d-none");
    }
    function reset() {
      clearError();
      result.classList.add("d-none");
      // try to reset the form too (file inputs need .reset() to clear value)
      try { form.reset(); } catch (_) {}
      // re-enable submit if it was disabled by validation
      if (submitBtn) submitBtn.disabled = false;
      if (busy) busy.classList.add("d-none");
      // scroll back to the form
      try { form.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) {}
    }

    if (resetBtn) resetBtn.addEventListener("click", reset);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearError();
      result.classList.add("d-none");
      if (submitBtn) submitBtn.disabled = true;
      if (busy) busy.classList.remove("d-none");

      try {
        const fd = new FormData(form);
        const resp = await fetch(form.action, {
          method: form.method || "POST",
          body: fd,
          headers: { "Accept": "application/json" },
        });

        // try JSON first
        let data = null;
        try { data = await resp.json(); } catch (_) {}

        if (!resp.ok || (data && data.error)) {
          const msg = (data && data.error) || `请求失败 (HTTP ${resp.status})`;
          showError(msg);
          return;
        }
        if (!data || !data.url || !data.filename) {
          showError("服务器返回的数据不完整，请稍后再试。");
          return;
        }

        const mode = pickMode(prefer, data.mime);
        if (previewSlot) {
          previewSlot.innerHTML = PREVIEW_HTML[mode](data.url, data.filename);
        }
        if (filenameEl) {
          filenameEl.textContent = data.filename;
          filenameEl.setAttribute("title", data.filename);
        }
        if (sizeEl) {
          sizeEl.textContent = humanSize(data.size);
        }

        // Optional: original_size + saved percentage (image compress)
        const origEl = document.getElementById("resultOriginalSize");
        const savedEl = document.getElementById("resultSaved");
        if (origEl || savedEl) {
          if (typeof data.original_size === "number" && data.original_size > 0) {
            if (origEl) origEl.textContent = humanSize(data.original_size);
            if (savedEl) {
              const pct = (1 - data.size / data.original_size) * 100;
              if (pct >= 0) {
                savedEl.textContent = `-${pct.toFixed(1)}%`;
                savedEl.className = "badge bg-success";
              } else {
                savedEl.textContent = `+${(-pct).toFixed(1)}%`;
                savedEl.className = "badge bg-warning text-dark";
              }
            }
          } else {
            if (origEl) origEl.textContent = "—";
            if (savedEl) { savedEl.textContent = "—"; savedEl.className = "badge bg-secondary"; }
          }
        }

        // Optional: dimensions
        const dimEl = document.getElementById("resultDimensions");
        if (dimEl) {
          if (data.width && data.height) {
            dimEl.textContent = `${data.width} × ${data.height}`;
          } else {
            dimEl.textContent = "—";
          }
        }

        // Optional: multiple files (e.g. PDF split into several outputs)
        const filesListEl = document.getElementById("resultFilesList");
        const filesWrap = document.getElementById("resultFilesListWrap") || filesListEl;
        if (filesListEl) {
          if (Array.isArray(data.files) && data.files.length > 1) {
            filesListEl.innerHTML = data.files.map((f) => {
              const lbl = f.label ? `<span class="text-muted small me-2">${escapeHtml(f.label)}:</span>` : "";
              const pages = f.page_count ? `<small class="text-muted">${f.page_count} 页</small>` : "";
              return `<li class="list-group-item d-flex align-items-center gap-2">` +
                `<i class="bi bi-file-earmark-pdf text-danger"></i>` +
                `<span class="flex-grow-1 text-truncate">` + lbl +
                `<code class="user-select-all">${escapeHtml(f.filename)}</code></span>` +
                `<small class="text-muted">${humanSize(f.size)}</small>` +
                (pages ? `<small class="text-muted">·</small>` + pages : "") +
                `<a href="${f.url}" class="btn btn-sm btn-outline-primary" download title="下载">` +
                `<i class="bi bi-download"></i></a></li>`;
            }).join("");
            if (filesWrap) filesWrap.classList.remove("d-none");
          } else {
            filesListEl.innerHTML = "";
            if (filesWrap) filesWrap.classList.add("d-none");
          }
        }

        if (downloadLink) {
          downloadLink.href = data.url;
          downloadLink.setAttribute("download", data.filename);
        }
        if (openLink) {
          openLink.href = data.url;
          // hide the "open" link for non-previewable things
          openLink.classList.toggle("d-none", mode === "other");
        }
        result.classList.remove("d-none");
        try { result.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) {}
      } catch (err) {
        showError("网络错误：" + (err && err.message ? err.message : err));
      } finally {
        if (submitBtn) submitBtn.disabled = false;
        if (busy) busy.classList.add("d-none");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('form[data-async="1"]').forEach(setup);
  });
})();

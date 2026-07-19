// FCST merge tool: PN mapping CRUD + drag&drop file list.
(function () {
  // ---- CSRF helper: read token from <meta name="csrf-token"> ----
  const CSRF_TOKEN = (document.querySelector('meta[name="csrf-token"]') || {})
    .getAttribute ? document.querySelector('meta[name="csrf-token"]').getAttribute("content") : "";

  function jsonHeaders() {
    return {
      "Content-Type": "application/json",
      "X-CSRFToken": CSRF_TOKEN,
    };
  }
  // fdHeaders() — for multipart/form-data uploads; Content-Type is set
  // automatically by the browser when using FormData, so we only add CSRF.
  function fdHeaders() {
    return { "X-CSRFToken": CSRF_TOKEN };
  }

  // ---------- PN mapping table ----------
  const tbody = document.getElementById("pnTableBody");
  const search = document.getElementById("pnSearch");
  const pagerInfo = document.getElementById("pnPagerInfo");
  const pagerBtns = document.getElementById("pnPagerBtns");
  const countBadge = document.getElementById("pnCountBadge");
  const statsEl = document.getElementById("pnStats");
  const API = "/tools/fcst-merge/api/pn";

  let curPage = 1;
  let curQ = "";
  let totalPages = 1;

  async function loadPage(page) {
    curPage = page;
    const url = `${API}?page=${page}&per_page=20&q=${encodeURIComponent(curQ)}`;
    const r = await fetch(url);
    const j = await r.json();
    if (!r.ok || !j.ok) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-danger py-3">${j.error || "加载失败"}</td></tr>`;
      return;
    }
    countBadge.textContent = j.total;
    statsEl.textContent = `共 ${j.total} 条`;
    if (j.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">暂无数据，点「新增」或「批量导入」开始</td></tr>`;
    } else {
      tbody.innerHTML = j.items.map((it, i) => `
        <tr>
          <td class="text-muted">${(j.page - 1) * j.per_page + i + 1}</td>
          <td><code class="user-select-all">${escapeHtml(it.part_number)}</code></td>
          <td>${escapeHtml(it.mfr_part || "—")}</td>
          <td>${escapeHtml(it.brand || "—")}</td>
          <td class="text-end">
            <button class="btn btn-sm btn-link text-primary p-0 me-2" data-edit="${it.id}" title="编辑">
              <i class="bi bi-pencil"></i>
            </button>
            <button class="btn btn-sm btn-link text-danger p-0" data-del="${it.id}" title="删除">
              <i class="bi bi-trash"></i>
            </button>
          </td>
        </tr>
      `).join("");
    }
    totalPages = j.pages;
    pagerInfo.textContent = `第 ${j.page} / ${j.pages} 页 · 共 ${j.total} 条`;
    renderPager(j.page, j.pages);
  }

  function renderPager(page, pages) {
    if (pages <= 1) { pagerBtns.innerHTML = ""; return; }
    const btns = [];
    btns.push(`<button class="btn btn-outline-secondary ${page === 1 ? "disabled" : ""}" data-page="${page - 1}">‹ 上一页</button>`);
    btns.push(`<button class="btn btn-outline-secondary ${page === pages ? "disabled" : ""}" data-page="${page + 1}">下一页 ›</button>`);
    pagerBtns.innerHTML = btns.join("");
  }

  pagerBtns.addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]");
    if (!b || b.classList.contains("disabled")) return;
    loadPage(Number(b.dataset.page));
  });

  // debounce search
  let searchTimer;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      curQ = search.value.trim();
      loadPage(1);
    }, 300);
  });

  // ---------- Edit / Create modal ----------
  const modalEl = document.getElementById("pnModal");
  const modal = new bootstrap.Modal(modalEl);
  const fId = document.getElementById("pnEditId");
  const fPn = document.getElementById("pnEditPn");
  const fMfr = document.getElementById("pnEditMfr");
  const fBrand = document.getElementById("pnEditBrand");
  const mTitle = document.getElementById("pnModalTitle");

  document.getElementById("pnNewBtn").addEventListener("click", () => {
    fId.value = "";
    fPn.value = "";
    fMfr.value = "";
    fBrand.value = "";
    mTitle.textContent = "新增料号映射";
    modal.show();
  });

  tbody.addEventListener("click", async (e) => {
    const editBtn = e.target.closest("[data-edit]");
    const delBtn = e.target.closest("[data-del]");
    if (editBtn) {
      // server has no single-row GET; look it up by part number via search
      const codeEl = editBtn.closest("tr").querySelector("code");
      const pn = codeEl ? codeEl.textContent : "";
      if (!pn) return;
      const r = await fetch(`${API}?q=${encodeURIComponent(pn)}&per_page=100`);
      const j = await r.json();
      const item = (j.items || []).find((it) => it.part_number === pn);
      if (!item) { alert("找不到该记录"); return; }
      fId.value = item.id;
      fPn.value = item.part_number;
      fMfr.value = item.mfr_part || "";
      fBrand.value = item.brand || "";
      mTitle.textContent = "编辑料号映射";
      modal.show();
    } else if (delBtn) {
      if (!confirm("确定删除这条料号映射？")) return;
      const r = await fetch(`${API}/${delBtn.dataset.del}`, { method: "DELETE", headers: fdHeaders() });
      const j = await r.json();
      if (!r.ok || !j.ok) { alert(j.error || "删除失败"); return; }
      loadPage(curPage);
    }
  });

  document.getElementById("pnSaveBtn").addEventListener("click", async () => {
    const body = {
      part_number: fPn.value.trim(),
      mfr_part: fMfr.value.trim(),
      brand: fBrand.value.trim(),
    };
    if (!body.part_number) { alert("品号不能为空"); return; }
    let r;
    if (fId.value) {
      r = await fetch(`${API}/${fId.value}`, {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify(body),
      });
    } else {
      r = await fetch(API, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(body),
      });
    }
    const j = await r.json();
    if (!r.ok || !j.ok) { alert(j.error || "保存失败"); return; }
    modal.hide();
    loadPage(curPage);
  });

  // ---------- Batch import ----------
  const importInput = document.getElementById("pnImportFile");
  document.getElementById("pnImportBtn").addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", async () => {
    const f = importInput.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const r = await fetch(`${API}/import`, { method: "POST", body: fd, headers: fdHeaders() });
    const j = await r.json();
    if (!r.ok || !j.ok) { alert(j.error || "导入失败"); return; }
    alert(`导入完成：新增 ${j.added} 条，更新 ${j.updated} 条，跳过 ${j.skipped} 条`);
    importInput.value = "";
    loadPage(1);
  });

  // ---------- File upload + reorder (FCST tab) ----------
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("files");
  const fileList = document.getElementById("fileList");
  const submitBtn = document.getElementById("submitBtn");
  let dataTransfer = new DataTransfer();

  function renderFiles() {
    fileList.innerHTML = "";
    const files = Array.from(fileInput.files || []);
    // Show as "文件1 / 文件2" to avoid leaking real filenames in the DOM
    files.forEach((f, idx) => {
      const li = document.createElement("li");
      li.className = "list-group-item d-flex align-items-center gap-2 file-item";
      li.innerHTML = `
        <i class="bi bi-file-earmark-spreadsheet text-success"></i>
        <span class="flex-grow-1">文件 ${idx + 1}</span>
        <small class="text-muted">${(f.size / 1024).toFixed(1)} KB</small>
        <button type="button" class="btn btn-sm btn-link text-danger" data-remove="${idx}">
          <i class="bi bi-x-lg"></i>
        </button>
      `;
      fileList.appendChild(li);
    });
    submitBtn.disabled = files.length === 0;
  }

  function addFiles(picked) {
    const existing = Array.from(fileInput.files || []);
    const merged = existing.concat(Array.from(picked));
    dataTransfer = new DataTransfer();
    merged.forEach((f) => dataTransfer.items.add(f));
    fileInput.files = dataTransfer.files;
    renderFiles();
  }

  fileInput.addEventListener("change", () => renderFiles());
  fileList.addEventListener("click", (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b) return;
    const idx = Number(b.dataset.remove);
    const files = Array.from(fileInput.files || []);
    files.splice(idx, 1);
    dataTransfer = new DataTransfer();
    files.forEach((f) => dataTransfer.items.add(f));
    fileInput.files = dataTransfer.files;
    renderFiles();
  });

  ["dragenter", "dragover"].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("is-drag"); });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("is-drag"); });
  });
  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
  });

  // ---------- Render result stats (extension of result.js) ----------
  // result.js populates the basics; we add the stats panel when present.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.id !== "mergeForm") return;
    // result.js handles the fetch; we hook after it via a custom event
  }, true);

  // Intercept fetch response by patching the form's submit (result.js already
  // does e.preventDefault). We instead poll the result card visibility.
  // Simpler: extend by listening to a custom event we fire from result.js? No.
  // Instead, monkey-patch fetch on this page to capture fcst-merge/process.
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await origFetch.apply(this, args);
    const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url);
    if (url && url.includes("fcst-merge/process")) {
      try {
        const clone = resp.clone();
        const j = await clone.json();
        if (j && j.ok && j.stats) renderStats(j.stats);
      } catch (_) {}
    }
    return resp;
  };

  function renderStats(stats) {
    const el = document.getElementById("resultStats");
    if (!el) return;
    const unmatched = stats.unmatched_part_numbers || 0;
    const errCount = (stats.errors || []).length;
    el.innerHTML = `
      <div class="col"><div class="border rounded p-2"><div class="h5 mb-0">${stats.files_read}</div><small class="text-muted">读取文件数</small></div></div>
      <div class="col"><div class="border rounded p-2"><div class="h5 mb-0">${stats.part_numbers}</div><small class="text-muted">品号数</small></div></div>
      <div class="col"><div class="border rounded p-2"><div class="h5 mb-0">${(stats.months || []).length}</div><small class="text-muted">月份数</small></div></div>
      <div class="col"><div class="border rounded p-2"><div class="h5 mb-0 ${unmatched ? "text-warning" : ""}">${unmatched}</div><small class="text-muted">未匹配品号</small></div></div>
      ${errCount ? `<div class="col-12"><div class="alert alert-warning small mb-0 mt-2">${stats.errors.map(escapeHtml).join("<br>")}</div></div>` : ""}
    `;
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  // initial load
  loadPage(1);
})();

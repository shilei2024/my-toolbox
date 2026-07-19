// Drag & drop + reorder for the PDF merge tool.
(function () {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("pdfs");
  const fileList = document.getElementById("fileList");
  const orderInput = document.getElementById("orderInput");
  const submitBtn = document.getElementById("submitBtn");
  if (!dropzone) return;

  /** @type {File[]} */
  let files = [];
  // We mirror the chosen files into a DataTransfer so the underlying
  // `<input type=file>` actually carries the order back to the server.
  let dataTransfer = new DataTransfer();

  function render() {
    fileList.innerHTML = "";
    files.forEach((f, idx) => {
      const li = document.createElement("li");
      li.className = "list-group-item d-flex align-items-center gap-2 file-item";
      li.draggable = true;
      li.dataset.index = String(idx);
      li.innerHTML = `
        <i class="bi bi-grip-vertical grip"></i>
        <i class="bi bi-file-earmark-pdf text-danger"></i>
        <span class="flex-grow-1 text-truncate">${f.name}</span>
        <small class="text-muted">${(f.size / 1024 / 1024).toFixed(2)} MB</small>
        <button type="button" class="btn btn-sm btn-link text-danger" data-remove="${idx}">
          <i class="bi bi-x-lg"></i>
        </button>
      `;
      fileList.appendChild(li);
    });
    submitBtn.disabled = files.length < 2;

    // Rebuild DataTransfer
    dataTransfer = new DataTransfer();
    files.forEach((f) => dataTransfer.items.add(f));
    fileInput.files = dataTransfer.files;

    // order is implicit (current DOM order) but we also write a comma-list for server convenience
    orderInput.value = files.map((_, i) => i).join(",");
  }

  function addFiles(picked) {
    for (const f of picked) {
      if (!/\.pdf$/i.test(f.name)) {
        alert(`已忽略非 PDF 文件：${f.name}`);
        continue;
      }
      files.push(f);
    }
    render();
  }

  // ---- file input change
  fileInput.addEventListener("change", (e) => {
    addFiles(Array.from(e.target.files || []));
  });

  // ---- drag & drop on dropzone
  ["dragenter", "dragover"].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-drag");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-drag");
    });
  });
  dropzone.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (dt && dt.files) addFiles(Array.from(dt.files));
  });

  // ---- remove
  fileList.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove]");
    if (!btn) return;
    const idx = Number(btn.dataset.remove);
    files.splice(idx, 1);
    render();
  });

  // ---- reorder via drag
  let dragSrc = null;
  fileList.addEventListener("dragstart", (e) => {
    const li = e.target.closest(".file-item");
    if (!li) return;
    dragSrc = Number(li.dataset.index);
    li.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  fileList.addEventListener("dragend", (e) => {
    const li = e.target.closest(".file-item");
    if (li) li.classList.remove("dragging");
  });
  fileList.addEventListener("dragover", (e) => {
    const li = e.target.closest(".file-item");
    if (!li) return;
    e.preventDefault();
    const overIdx = Number(li.dataset.index);
    if (dragSrc === null || overIdx === dragSrc) return;
    const moved = files.splice(dragSrc, 1)[0];
    files.splice(overIdx, 0, moved);
    dragSrc = overIdx;
    render();
  });

  // Submit is handled by result.js (form has data-async="1").
})();

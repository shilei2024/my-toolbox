// Client-side page-range validation for the PDF split tool + AI image polling.
(function () {
  function humanSize(n) {
    if (typeof n !== "number" || !isFinite(n) || n < 0) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }

  // Briefly swap a button's icon + text to confirm a copy action.
  function _flashCopy(btn, text) {
    const icon = btn.querySelector("i");
    const origClass = icon ? icon.className : "";
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<i class="bi bi-check2"></i> ${text}`;
    btn.classList.add("text-success");
    setTimeout(() => {
      btn.innerHTML = origHtml;
      btn.classList.remove("text-success");
    }, 1500);
  }
  // expose for the AI image block below
  window._flashCopy = _flashCopy;

  // ----- PDF split: validate range pattern on input -----
  const ranges = document.getElementById("ranges");
  const submit = document.getElementById("submitBtn");
  if (ranges && submit) {
    const re = /^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$/;
    function check() {
      const ok = re.test(ranges.value || "");
      submit.disabled = !ok;
      document.getElementById("rangesHelp").classList.toggle("text-danger", !ok);
    }
    ranges.addEventListener("input", check);
    check();
  }

  // ----- AI image: poll status, show result -----
  const aiForm = document.getElementById("aiForm");
  if (!aiForm) return;

  const result = document.getElementById("result");
  const resultLink = document.getElementById("resultLink");
  const resultImg = document.getElementById("resultImg");
  const resultFilename = document.getElementById("resultFilename");
  const resultSize = document.getElementById("resultSize");
  const downloadLink = document.getElementById("downloadLink");
  const errorBox = document.getElementById("errorBox");
  const submitBtn = document.getElementById("submitBtn");
  const busy = document.getElementById("busy");

  async function poll(taskId) {
    let tries = 0;
    while (tries < 60) {
      await new Promise((r) => setTimeout(r, 2000));
      const resp = await fetch(`/tools/ai-image/status/${taskId}`);
      if (!resp.ok) break;
      const data = await resp.json();
      if (data.status === "done") {
        resultImg.src = data.url;
        resultImg.alt = data.filename || "生成结果";
        resultLink.href = data.url;
        downloadLink.href = data.url;
        if (downloadLink && data.filename) {
          downloadLink.setAttribute("download", data.filename);
        }
        if (resultFilename) {
          resultFilename.textContent = data.filename || "";
          resultFilename.setAttribute("title", data.filename || "");
        }
        if (resultSize) {
          resultSize.textContent = humanSize(data.size);
        }
        const dimEl = document.getElementById("resultDimensions");
        if (dimEl) {
          dimEl.textContent = (data.width && data.height)
            ? `${data.width} × ${data.height}`
            : "—";
        }
        const durEl = document.getElementById("resultDuration");
        if (durEl) {
          durEl.textContent = (typeof data.duration_seconds === "number")
            ? `${data.duration_seconds} 秒`
            : "—";
        }
        // copy filename button
        const copyBtn = document.getElementById("copyFilenameBtn");
        if (copyBtn && !copyBtn.dataset.bound) {
          copyBtn.dataset.bound = "1";
          copyBtn.addEventListener("click", () => {
            const txt = (resultFilename && resultFilename.textContent) || "";
            if (!txt) return;
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(txt).then(
                () => _flashCopy(copyBtn, "已复制"),
                () => _flashCopy(copyBtn, "复制失败"),
              );
            } else {
              _flashCopy(copyBtn, "浏览器不支持");
            }
          });
        }
        result.classList.remove("d-none");
        return;
      }
      if (data.status === "failed") {
        errorBox.textContent = "生成失败：" + (data.error || "未知错误，请稍后再试");
        errorBox.classList.remove("d-none");
        return;
      }
      tries++;
    }
    errorBox.textContent = "生成超时，请稍后再试。";
    errorBox.classList.remove("d-none");
  }

  aiForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.classList.add("d-none");
    result.classList.add("d-none");
    submitBtn.disabled = true;
    busy.classList.remove("d-none");

    try {
      const fd = new FormData(aiForm);
      const resp = await fetch(aiForm.action, { method: "POST", body: fd });
      const data = await resp.json();
      if (!resp.ok) {
        errorBox.textContent = data.error || "请求失败";
        errorBox.classList.remove("d-none");
        return;
      }
      await poll(data.task_id);
    } catch (err) {
      errorBox.textContent = "网络错误：" + err.message;
      errorBox.classList.remove("d-none");
    } finally {
      submitBtn.disabled = false;
      busy.classList.add("d-none");
    }
  });
})();

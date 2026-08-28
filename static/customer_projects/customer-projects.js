(() => {
  "use strict";
  const root = document.querySelector("[data-cp-project-id][data-cp-project-version]");
  if (!root) return;
  const projectId = root.dataset.cpProjectId;
  const initialVersion = Number(root.dataset.cpProjectVersion);
  const alert = root.querySelector("[data-cp-update-alert]");
  if (!projectId || !Number.isFinite(initialVersion) || !alert) return;

  const priceForms = Array.from(root.querySelectorAll("[data-price-form]"));
  if (priceForms.length) {
    fetch("/api/exchange-rate?from=USD&to=CNY", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store",
    })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("rate"))))
      .then((payload) => {
        const rate = Number(payload.rate);
        if (!Number.isFinite(rate) || rate <= 0) return;
        priceForms.forEach((form) => {
          const amountInput = form.querySelector('[name="unit_price"]');
          const currencyInput = form.querySelector('[name="currency"]');
          const preview = form.querySelector("[data-price-preview]");
          if (!amountInput || !currencyInput || !preview) return;
          const updatePreview = () => {
            const amount = Number(amountInput.value);
            if (!Number.isFinite(amount) || amount <= 0) {
              preview.textContent = `当前 USD/CNY 汇率 ${rate.toFixed(4)}`;
              return;
            }
            const usd = currencyInput.value === "USD" ? amount : amount / 1.13 / rate;
            const cnyTax = currencyInput.value === "USD" ? amount * rate * 1.13 : amount;
            preview.textContent = `USD ${usd.toFixed(6)} · 含税人民币 ¥${cnyTax.toFixed(6)}（13% 增值税）`;
          };
          amountInput.addEventListener("input", updatePreview);
          currencyInput.addEventListener("change", updatePreview);
          updatePreview();
        });
      })
      .catch(() => {
        priceForms.forEach((form) => {
          const preview = form.querySelector("[data-price-preview]");
          if (preview) preview.textContent = "汇率暂不可用，保存时会再次校验";
        });
      });
  }

  const checkVersion = async () => {
    if (document.visibilityState !== "visible") return;
    try {
      const response = await fetch(`/api/v1/customer-projects/projects/${encodeURIComponent(projectId)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const payload = await response.json();
      if (Number(payload?.data?.version) !== initialVersion) alert.classList.remove("d-none");
    } catch (_) {
      // A failed background check must not disturb an in-progress edit.
    }
  };

  window.setInterval(checkVersion, 25000);
})();

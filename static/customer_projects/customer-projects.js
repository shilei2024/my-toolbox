(() => {
  "use strict";
  const root = document.querySelector("[data-cp-project-id][data-cp-project-version]");
  if (!root) return;
  const projectId = root.dataset.cpProjectId;
  const initialVersion = Number(root.dataset.cpProjectVersion);
  const alert = root.querySelector("[data-cp-update-alert]");
  if (!projectId || !Number.isFinite(initialVersion) || !alert) return;

  const opportunityTypes = [
    ["design_in", "Design In", "正在设计与验证推广的物料"],
    ["design_win", "Design Win", "已获得定点的推广物料"],
    ["matched_opportunity", "Evaluation", "已匹配推广型号、正在评估的机会"],
    ["competitive_opportunity", "Lost", "被竞品占据的机会，仅记录竞品信息"],
  ];
  const lostType = "competitive_opportunity";

  /**
   * 根据机会类型切换推广物料输入的必填与可见性：
   * Lost 仅记录竞品信息，推广品牌/型号与单价输入放宽并隐藏。
   */
  const applyOpportunityFormMode = (form, type) => {
    const isLost = type === lostType;
    form.querySelectorAll('input[name="promoted_brand"], input[name="promoted_mpn"]').forEach((input) => {
      input.required = !isLost;
      input.placeholder = isLost ? "Lost 机会可不填推广品牌" : input.placeholder;
    });
    form.querySelectorAll(
      'select[name="currency"], input[name="unit_price"], [data-price-preview]'
    ).forEach((node) => {
      node.hidden = isLost;
    });
    if (!form.dataset.cpLostHint) {
      const hint = document.createElement("small");
      hint.className = "text-muted cp-lost-hint";
      hint.hidden = !isLost;
      hint.textContent = "Lost 仅记录竞品信息：保存后请在物料卡片中补充竞品详情与报价（TAM 按竞品最高报价估算）。";
      form.append(hint);
      form.dataset.cpLostHint = "1";
    }
    const hintNode = form.querySelector(".cp-lost-hint");
    if (hintNode) hintNode.hidden = !isLost;
  };

  root.querySelectorAll('input[name="annual_usage"]').forEach((input) => {
    input.min = "1";
    input.step = "1";
    input.inputMode = "numeric";
    const value = Number(input.value);
    if (Number.isFinite(value)) input.value = String(Math.trunc(value));
    input.placeholder = "项目年用量（PCS，整数）";
    const fieldLabel = input.closest(".mb-3")?.querySelector("label");
    if (fieldLabel) fieldLabel.textContent = "项目年用量（PCS） *";
  });

  root.querySelectorAll('input[name="machine_quantity"]').forEach((input) => {
    input.min = "0";
    input.step = "1";
    input.inputMode = "numeric";
    const value = Number(input.value);
    if (Number.isFinite(value)) input.value = String(Math.trunc(value));
    input.placeholder = "单机数量（PCS，整数）";
  });

  root.querySelectorAll('input[name="unit_price"], input[name="quoted_price"]').forEach((input) => {
    input.step = "0.00001";
    const value = Number(input.value);
    if (Number.isFinite(value) && input.value !== "") {
      input.value = value.toFixed(5).replace(/\.?0+$/, "");
    }
  });

  const opportunitySelect = (selected = "design_in") => {
    const wrapper = document.createElement("label");
    wrapper.className = "cp-dialog-field cp-field-span";
    wrapper.textContent = "物料机会分类";
    const select = document.createElement("select");
    select.className = "form-select";
    select.name = "opportunity_type";
    opportunityTypes.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = value === selected;
      select.append(option);
    });
    wrapper.append(select);
    select.addEventListener("change", () => {
      const form = select.closest("form");
      if (form) applyOpportunityFormMode(form, select.value);
    });
    return wrapper;
  };

  const openDialog = (dialog) => {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  };

  const upgradeDetails = (details, trigger, title) => {
    if (!details || !trigger) return;
    const summary = details.querySelector(":scope > summary");
    const dialog = document.createElement("dialog");
    dialog.className = "cp-edit-dialog";
    const header = document.createElement("header");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cp-dialog-close";
    close.setAttribute("aria-label", "关闭弹窗");
    close.textContent = "×";
    close.addEventListener("click", () => dialog.close());
    header.append(heading, close);
    dialog.append(header);
    Array.from(details.children).forEach((child) => {
      if (child !== summary) dialog.append(child);
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    details.replaceWith(dialog);
    trigger.classList.add("cp-model-trigger");
    trigger.setAttribute("role", "button");
    trigger.setAttribute("tabindex", "0");
    trigger.setAttribute("aria-label", `${title}，点击打开编辑弹窗`);
    trigger.addEventListener("click", () => openDialog(dialog));
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDialog(dialog);
      }
    });
  };

  upgradeDetails(
    root.querySelector("details[data-project-edit]"),
    root.querySelector("[data-project-title]"),
    "编辑项目基础信息"
  );

  const materials = Array.from(root.querySelectorAll(".cp-material[data-opportunity-type]"));
  materials.forEach((material) => {
    const type = material.dataset.opportunityType || "design_in";
    const main = material.querySelector(".cp-material-main");
    const title = main?.querySelector("strong");
    const editDetails = Array.from(material.querySelectorAll(":scope > details")).find(
      (item) => item.querySelector(":scope > summary")?.textContent.trim() === "编辑推广物料"
    );
    const editForm = editDetails?.querySelector("form");
    if (editForm) editForm.prepend(opportunitySelect(type));
    if (editForm) applyOpportunityFormMode(editForm, type);
    upgradeDetails(editDetails, title, "编辑推广物料");

    if (main) {
      const badge = document.createElement("span");
      badge.className = `cp-opportunity-badge is-${type}`;
      badge.textContent = material.dataset.opportunityLabel || type;
      main.append(badge);
      const annualValue = material.dataset.annualValue;
      const value = document.createElement("small");
      value.className = "cp-material-value";
      value.textContent = annualValue
        ? `年度机会金额：USD ${Number(annualValue).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : type === lostType
          ? "年度机会金额：待补齐年用量、单机数量或竞品报价"
          : "年度机会金额：待补齐年用量、单机数量或美金单价";
      main.querySelector(":scope > div")?.append(value);
    }

    material.querySelectorAll(".cp-competitors .mb-2").forEach((row) => {
      const competitorTrigger = row.querySelector(":scope > p");
      const competitorDetails = Array.from(row.querySelectorAll(":scope > details")).find(
        (item) => item.querySelector(":scope > summary")?.textContent.trim() === "编辑竞争方案"
      );
      upgradeDetails(competitorDetails, competitorTrigger, "编辑竞争方案");
    });
    const addCompetitor = Array.from(material.querySelectorAll(":scope > details")).find(
      (item) => item.querySelector(":scope > summary")?.textContent.trim() === "添加竞争方案"
    );
    if (addCompetitor) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-sm btn-outline-secondary cp-add-competitor";
      button.textContent = "+ 添加竞争方案";
      material.append(button);
      upgradeDetails(addCompetitor, button, "添加竞争方案");
    }
  });

  const addBlock = root.querySelector(".cp-add-block");
  const materialPanel = addBlock?.closest(".cp-panel");
  if (materialPanel && addBlock) {
    const addForm = addBlock.querySelector("form");
    if (addForm) addForm.prepend(opportunitySelect());
    if (addForm) applyOpportunityFormMode(addForm, "design_in");
    const groups = document.createElement("div");
    groups.className = "cp-material-groups";
    opportunityTypes.forEach(([type, label, description]) => {
      const group = document.createElement("section");
      group.className = "cp-material-group";
      group.dataset.opportunityGroup = type;
      const rows = materials.filter((item) => item.dataset.opportunityType === type);
      group.innerHTML = `<header><div><h3>${label}</h3><p>${description}</p></div><span>${rows.length} 条</span></header>`;
      if (rows.length) rows.forEach((item) => group.append(item));
      else {
        const empty = document.createElement("p");
        empty.className = "cp-group-empty";
        empty.textContent = "暂无此类物料";
        group.append(empty);
      }
      groups.append(group);
    });
    materialPanel.insertBefore(groups, addBlock);
  }

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
            const displayPrice = (value) => value.toFixed(5).replace(/\.?0+$/, "");
            preview.textContent = `USD ${displayPrice(usd)} · 含税人民币 ¥${displayPrice(cnyTax)}（13% 增值税）`;
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

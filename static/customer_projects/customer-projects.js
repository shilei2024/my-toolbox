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
    // 空值保持占位符提示，不默认填 0
    if (input.value !== "") {
      const value = Number(input.value);
      if (Number.isFinite(value)) input.value = String(Math.trunc(value));
    }
    input.placeholder = "项目年用量（PCS，整数）";
    const fieldLabel = input.closest(".mb-3")?.querySelector("label");
    if (fieldLabel) fieldLabel.textContent = "项目年用量（PCS） *";
  });

  root.querySelectorAll('input[name="machine_quantity"]').forEach((input) => {
    input.min = "0";
    input.step = "1";
    input.inputMode = "numeric";
    // 空值显示“单机数量”占位符，不默认填 0
    if (input.value !== "") {
      const value = Number(input.value);
      if (Number.isFinite(value)) input.value = String(Math.trunc(value));
    }
    input.placeholder = "单机数量（PCS，整数）";
  });

  /**
   * 价格输入统一口径：使用 text 而非 number，避免部分移动浏览器把 number
   * 键盘锁定为整数、导致无法输入小数点。金额格式与精度始终由服务端 Decimal
   * 校验；失焦时仅规范化合法数值的显示。
   */
  root.querySelectorAll('input[name="unit_price"], input[name="quoted_price"]').forEach((input) => {
    input.type = "text";
    input.inputMode = "decimal";
    input.autocomplete = "off";
    const normalizeSeparator = () => {
      input.value = input.value.replace(/[，。．]/g, ".");
    };
    const normalize = () => {
      normalizeSeparator();
      if (input.value === "") return;
      const value = Number(input.value);
      if (Number.isFinite(value)) {
        input.value = value.toFixed(5).replace(/\.?0+$/, "");
      }
    };
    normalize();
    input.addEventListener("input", normalizeSeparator);
    input.addEventListener("blur", normalize);
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

  /**
   * 阶段（评估/送样/小批等）可点击徽章变更：
   * 点击页头阶段徽章弹出变更阶段表单，提交后时间线记录“阶段变化”。
   */
  const stagePanel = root.querySelector("[data-stage-panel]");
  const stageForm = stagePanel?.querySelector("form");
  const stageBadge = root.querySelector(".cp-detail-status .cp-stage");
  if (stagePanel && stageForm && stageBadge) {
    const dialog = document.createElement("dialog");
    dialog.className = "cp-edit-dialog";
    const header = document.createElement("header");
    const heading = document.createElement("h3");
    heading.textContent = "变更阶段";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cp-dialog-close";
    close.setAttribute("aria-label", "关闭弹窗");
    close.textContent = "×";
    close.addEventListener("click", () => dialog.close());
    header.append(heading, close);
    const hint = document.createElement("p");
    hint.className = "text-muted small";
    hint.textContent = "阶段变化会记录到跟进时间线；跳过阶段必须说明原因。";
    dialog.append(header, hint, stageForm);
    root.append(dialog);
    stagePanel.remove();
    stageBadge.classList.add("cp-model-trigger");
    stageBadge.setAttribute("role", "button");
    stageBadge.setAttribute("tabindex", "0");
    stageBadge.setAttribute("aria-label", "变更阶段，点击打开");
    stageBadge.setAttribute("title", "点击变更阶段");
    stageBadge.addEventListener("click", () => openDialog(dialog));
    stageBadge.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDialog(dialog);
      }
    });
  }

  /**
   * 打开机会分类快速转换弹窗：点击物料机会徽章直接转换
   * Design In / Design Win / Evaluation / Lost。
   * Lost 转出为其他三类时，按服务端规则要求补充推广品牌与型号（或勾选型号待确认）。
   */
  const openOpportunitySwitchDialog = (material, currentType) => {
    const editForm = material.querySelector('form[action*="/commercial"]');
    if (!editForm) return;
    const action = editForm.getAttribute("action") || "";
    const csrf = editForm.querySelector('input[name="csrf_token"]')?.value || "";
    const version = editForm.querySelector('input[name="material_version"]')?.value || "0";
    const appendHidden = (form, name, value) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.append(input);
    };

    const dialog = document.createElement("dialog");
    dialog.className = "cp-edit-dialog";
    const header = document.createElement("header");
    const heading = document.createElement("h3");
    heading.textContent = "转换机会分类";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cp-dialog-close";
    close.setAttribute("aria-label", "关闭弹窗");
    close.textContent = "×";
    close.addEventListener("click", () => dialog.close());
    header.append(heading, close);
    dialog.append(header);

    const form = document.createElement("form");
    form.method = "post";
    form.action = action;
    appendHidden(form, "csrf_token", csrf);
    appendHidden(form, "material_version", version);
    // 路由会按提交值重置主推/待确认状态，转换时回填当前状态避免丢失
    if (material.dataset.isPrimary === "1") appendHidden(form, "is_primary", "on");
    if (currentType !== lostType && material.dataset.mpnPending === "1") {
      appendHidden(form, "mpn_pending", "on");
    }

    const switcher = document.createElement("div");
    switcher.className = "cp-opportunity-switcher";
    const supplement = document.createElement("div");
    supplement.className = "cp-switch-supplement";
    supplement.hidden = true;
    const brandInput = document.createElement("input");
    brandInput.className = "form-control";
    brandInput.name = "promoted_brand";
    brandInput.maxLength = 120;
    brandInput.placeholder = "推广品牌 *";
    const mpnInput = document.createElement("input");
    mpnInput.className = "form-control";
    mpnInput.name = "promoted_mpn";
    mpnInput.maxLength = 160;
    mpnInput.placeholder = "推广型号";
    const pendingLabel = document.createElement("label");
    const pendingInput = document.createElement("input");
    pendingInput.type = "checkbox";
    pendingInput.name = "mpn_pending";
    pendingLabel.append(pendingInput, " 型号待确认");
    supplement.append(brandInput, mpnInput, pendingLabel);

    /**
     * 仅 Lost 转出为其他三类时要求补充推广物料信息。
     * 注意：隐藏容器内的输入仍会随表单提交，必须同时 disabled，
     * 否则空品牌/型号会覆盖物料现有值并触发服务端必填校验。
     */
    const toggleSupplement = (selected) => {
      const leaving = currentType === lostType && selected !== lostType;
      supplement.hidden = !leaving;
      brandInput.required = leaving;
      brandInput.disabled = !leaving;
      mpnInput.disabled = !leaving;
      pendingInput.disabled = !leaving;
    };
    toggleSupplement(currentType);

    opportunityTypes.forEach(([value, label]) => {
      const option = document.createElement("label");
      option.className = "cp-switch-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "opportunity_type";
      radio.value = value;
      radio.checked = value === currentType;
      radio.addEventListener("change", () => toggleSupplement(radio.value));
      option.append(radio, label);
      switcher.append(option);
    });

    const hint = document.createElement("p");
    hint.className = "text-muted small";
    hint.textContent = "转换会记录物料审计日志；Lost 转出时需补充推广品牌与型号。";

    const submit = document.createElement("button");
    submit.className = "btn btn-primary w-100";
    submit.type = "submit";
    submit.textContent = "确认转换";

    form.append(switcher, supplement, hint, submit);
    dialog.append(form);
    document.body.append(dialog);
    dialog.addEventListener("close", () => dialog.remove());
    openDialog(dialog);
  };

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
      if (root.dataset.cpCanWrite === "1") {
        // 有写权限时，点击机会徽章直接弹出四类转换弹窗
        badge.classList.add("is-switchable");
        badge.setAttribute("role", "button");
        badge.setAttribute("tabindex", "0");
        badge.setAttribute("title", "点击转换机会分类");
        badge.addEventListener("click", () => openOpportunitySwitchDialog(material, type));
        badge.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openOpportunitySwitchDialog(material, type);
          }
        });
      }
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

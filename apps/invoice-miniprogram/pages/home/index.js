const api = require("../../lib/api"),
  context = require("../../lib/context");
const KINDS = [
  { value: "invoice", label: "普通发票" },
  { value: "toll", label: "零散过路费" },
  { value: "fuel", label: "加油票" },
  { value: "toll_statement", label: "月度通行账单" },
];
Page({
  data: {
    showPrivacy: false,
    loggedIn: false,
    busy: false,
    message: "",
    periods: [],
    offices: [],
    customers: [{ id: null, display_name: "未关联客户" }],
    levels: [{ value: "", name: "未分类" }],
    periodIndex: 0,
    officeIndex: 0,
    customerIndex: 0,
    levelIndex: 0,
    kindIndex: 0,
    kinds: KINDS,
    month: "",
    queue: [],
    invoices: [],
    page: 1,
    hasMore: false,
  },
  onLoad() {
    this.privacyHandler = (resolve) => {
      this.resolvePrivacy = resolve;
      this.setData({ showPrivacy: true });
    };
    const now = new Date();
    this.setData({
      month:
        now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0"),
    });
  },
  onUnload() {
    if (this.resolvePrivacy) this.resolvePrivacy({ event: "disagree" });
    if (wx.offNeedPrivacyAuthorization)
      wx.offNeedPrivacyAuthorization(this.privacyHandler);
  },
  agreePrivacy() {
    if (this.resolvePrivacy)
      this.resolvePrivacy({
        event: "agree",
        buttonId: "invoice-privacy-agree",
      });
    this.resolvePrivacy = null;
    this.setData({ showPrivacy: false });
  },
  declinePrivacy() {
    if (this.resolvePrivacy) this.resolvePrivacy({ event: "disagree" });
    this.resolvePrivacy = null;
    this.setData({ showPrivacy: false });
  },
  onShow() {
    const epoch = context.state().authEpoch;
    if (this._epoch !== epoch) {
      this._epoch = epoch;
      this.setData({
        invoices: [], queue: [], periods: [], loggedIn: false,
        customers: [{ id: null, display_name: "未关联客户" }],
        levels: [{ value: "", name: "未分类" }],
        customerIndex: 0, levelIndex: 0,
      });
    }
    if (wx.onNeedPrivacyAuthorization)
      wx.onNeedPrivacyAuthorization(this.privacyHandler);
    if (!api.session()) {
      this.setData({
        loggedIn: false, invoices: [], queue: [], periods: [],
        customers: [{ id: null, display_name: "未关联客户" }],
        levels: [{ value: "", name: "未分类" }],
        customerIndex: 0, levelIndex: 0,
      });
      return;
    }
    if (!this.data.busy) this.bootstrap().catch((e) => this.showError(e));
  },
  onHide() {
    if (wx.offNeedPrivacyAuthorization)
      wx.offNeedPrivacyAuthorization(this.privacyHandler);
  },
  goMine() {
    wx.switchTab({ url: "/pages/mine/index" });
  },
  showError(e) {
    const update = { message: e.message || "操作未完成，请重试" };
    if (e.status === 401 || e.status === 428) update.loggedIn = false;
    this.setData(update);
  },
  async bootstrap() {
    const d = await api.request("/api/mobile/bootstrap");
    const index = context.choose(d.periods);
    const customers = [
      { id: null, display_name: "未关联客户" },
      ...(d.customers || []),
    ];
    const levels = [
      { value: "", name: "未分类" },
      ...(d.customer_levels || []).map((value) => ({ value, name: value })),
    ];
    const selectedCustomer = this.data.customers[this.data.customerIndex];
    const customerIndex = Math.max(
      0,
      customers.findIndex((item) => item.id === selectedCustomer?.id),
    );
    const selectedLevel = this.data.levels[this.data.levelIndex]?.value;
    const levelIndex = customers[customerIndex].id
      ? Math.max(0, levels.findIndex((item) => item.value === customers[customerIndex].grade))
      : Math.max(0, levels.findIndex((item) => item.value === selectedLevel));
    this.setData({
      loggedIn: true,
      periods: d.periods,
      offices: d.offices,
      customers,
      levels,
      periodIndex: index,
      officeIndex: 0,
      customerIndex,
      levelIndex,
      message: d.periods.length ? "" : "请先在网站创建报销周期，再下拉刷新",
    });
    await this.loadInvoices();
  },
  async loadInvoices(append = false) {
    const p = this.data.periods[this.data.periodIndex];
    if (!p) {
      this.setData({ invoices: [], hasMore: false });
      return;
    }
    const page = append ? this.data.page + 1 : 1;
    const d = await api.request(
      "/api/mobile/invoices?period_id=" + p.id + "&page=" + page,
    );
    if (this.data.periods[this.data.periodIndex]?.id !== p.id) return;
    const rows = d.invoices.map((i) => ({
      ...i,
      kindLabel:
        KINDS.find((k) => k.value === i.document_kind)?.label || "票据",
      stateLabel:
        i.inclusion_policy === "expense"
          ? "已确认，计入费用"
          : i.inclusion_policy === "review"
            ? i.amount_confirmed
              ? "信息已录入，暂不计费"
              : "待识别核对录入"
            : i.amount_confirmed
              ? "信息已录入，仅留存"
              : "仅保存原件，待核对",
    }));
    this.setData({
      invoices: append ? [...this.data.invoices, ...rows] : rows,
      page,
      hasMore: d.has_more,
    });
  },
  async refresh() {
    try {
      await this.bootstrap();
    } catch (e) {
      this.showError(e);
    }
  },
  async onPullDownRefresh() {
    try {
      if (this.data.loggedIn) await this.refresh();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
  async more() {
    try {
      await this.loadInvoices(true);
    } catch (e) {
      this.showError(e);
    }
  },
  onOffice(e) {
    this.setData({ officeIndex: Number(e.detail.value) });
  },
  onKind(e) {
    this.setData({ kindIndex: Number(e.detail.value) });
  },
  onMonth(e) {
    this.setData({ month: e.detail.value });
  },
  onCustomer(e) {
    const customerIndex = Number(e.detail.value);
    const customer = this.data.customers[customerIndex];
    if (!customer) return;
    this.setData({
      customerIndex,
      levelIndex: customer.id
        ? Math.max(0, this.data.levels.findIndex((item) => item.value === customer.grade))
        : 0,
    });
  },
  onLevel(e) {
    if (this.data.customers[this.data.customerIndex]?.id) return;
    this.setData({ levelIndex: Number(e.detail.value) });
  },
  intent() {
    const p = this.data.periods[this.data.periodIndex],
      o = this.data.offices[this.data.officeIndex],
      customer = this.data.customers[this.data.customerIndex],
      level = this.data.levels[this.data.levelIndex];
    if (!p || !o) throw new Error("请先选择网站报销周期及办事处");
    return {
      period_id: String(p.id),
      office_id: String(o.id),
      document_kind: KINDS[this.data.kindIndex].value,
      occurrence_month: this.data.month,
      customer_id: customer?.id || "",
      customer_level: customer?.id ? customer.grade || "" : level?.value || "",
    };
  },
  async chooseImage() {
    if (this._choosing || this.data.busy) return;
    this._choosing = true;
    try {
      await api.privacy();
      this.intent();
      const res = await new Promise((resolve, reject) =>
        wx.chooseMedia({
          count: 9,
          mediaType: ["image"],
          sizeType: ["compressed"],
          sourceType: ["camera", "album"],
          success: resolve,
          fail: () => reject(new Error("未选择图片")),
        }),
      );
      const files = await Promise.all(
        res.tempFiles.map(async (f, index) => {
          const info = await new Promise((resolve, reject) =>
            wx.getImageInfo({
              src: f.tempFilePath,
              success: resolve,
              fail: () => reject(new Error("无法读取图片，请重新选择PNG或JPG")),
            }),
          );
          const ext = { jpeg: ".jpg", jpg: ".jpg", png: ".png" }[info.type];
          if (!ext) throw new Error("请选择PNG或JPG图片");
          return {
            path: f.tempFilePath,
            size: f.size,
            name: "票据-" + Date.now() + "-" + (index + 1) + ext,
          };
        }),
      );
      this.enqueue(files);
    } catch (e) {
      this.showError(e);
    } finally {
      this._choosing = false;
    }
  },
  async choosePdf() {
    if (this._choosing || this.data.busy) return;
    this._choosing = true;
    try {
      await api.privacy();
      this.intent();
      const res = await new Promise((resolve, reject) =>
        wx.chooseMessageFile({
          count: 9,
          type: "file",
          extension: ["pdf"],
          success: resolve,
          fail: () => reject(new Error("未选择文件")),
        }),
      );
      this.enqueue(
        res.tempFiles.map((f) => ({
          path: f.path,
          size: f.size,
          name: f.name,
        })),
      );
    } catch (e) {
      this.showError(e);
    } finally {
      this._choosing = false;
    }
  },
  enqueue(files) {
    if (
      this.data.queue.filter((x) => x.state !== "success").length +
        files.length >
      30
    ) {
      this.setData({
        message: "每次最多保留 30 个待上传文件，请先完成当前批次",
      });
      return;
    }
    const intent = this.intent();
    if (files.some((f) => f.size > 20 * 1024 * 1024)) {
      this.setData({ message: "单文件最大 20MB，请重新选择" });
      return;
    }
    const label =
      this.data.periods[this.data.periodIndex].name +
      " · " +
      KINDS[this.data.kindIndex].label;
    this.setData({
      queue: [
        ...this.data.queue,
        ...files.map((f) => ({
          ...f,
          intent: { ...intent },
          label,
          key: api.key(),
          state: "pending",
          statusText: "待上传",
          progress: 0,
        })),
      ],
      message: "",
    });
    this.runQueue();
  },
  async runQueue() {
    if (this.data.busy) return;
    context.state().uploading = true;
    this.setData({ busy: true });
    try {
      for (let i = 0; i < this.data.queue.length; i++) {
        const item = this.data.queue[i];
        if (item.state !== "pending") continue;
        this.setData({
          ["queue[" + i + "].state"]: "uploading",
          ["queue[" + i + "].statusText"]: "正在上传",
        });
        try {
          const data = await api.upload(item, (p) =>
            this.setData({ ["queue[" + i + "].progress"]: p }),
          );
          this.setData({
            ["queue[" + i + "].state"]: "success",
            ["queue[" + i + "].statusText"]: data.duplicate
              ? "已保存（重复文件已合并）"
              : "已保存到网站",
            ["queue[" + i + "].progress"]: 100,
            ["queue[" + i + "].invoiceId"]: data.invoice.id,
          });
          this.setData({
            ["queue[" + i + "].statusText"]: "原件已保存，正在识别",
          });
          try {
            const recognized = await api.request(
              "/api/mobile/invoices/" + data.invoice.id + "/recognize",
              { method: "POST", data: {}, timeout: 90000 },
            );
            this.setData({
              ["queue[" + i + "].statusText"]: recognized.success
                ? "已识别，请核对并录入"
                : "未识别完整，请核对补录",
            });
          } catch (e) {
            this.setData({
              ["queue[" + i + "].statusText"]: "已保存，可打开核对并手工补录",
            });
          }
        } catch (e) {
          this.setData({
            ["queue[" + i + "].state"]: "failed",
            ["queue[" + i + "].statusText"]: e.message,
          });
          if (e.status === 401) {
            this.showError(e);
            break;
          }
        }
      }
      if (this.data.loggedIn) await this.loadInvoices();
    } catch (e) {
      this.showError(e);
    } finally {
      context.state().uploading = false;
      this.setData({ busy: false });
    }
  },
  retry(e) {
    const index = Number(e.currentTarget.dataset.index);
    if (this.data.busy || !api.session()) {
      this.setData({ message: "请先登录后重试" });
      return;
    }
    this.setData({ ["queue[" + index + "].state"]: "pending" });
    this.runQueue();
  },
  review(e) {
    const id = Number(e.currentTarget.dataset.id);
    if (id)
      wx.navigateTo({ url: "/pages/review/index?id=" + id + "&recognize=1" });
  },
  showPrivacy() {
    if (wx.openPrivacyContract)
      wx.openPrivacyContract({
        fail: () => this.setData({ message: "隐私说明暂不可用，请稍后重试" }),
      });
  },
});

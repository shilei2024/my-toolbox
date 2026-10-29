const api = require("../../lib/api");
const kinds = [
  { value: "invoice", name: "普通发票" },
  { value: "toll", name: "零散过路费" },
  { value: "fuel", name: "加油票" },
  { value: "toll_statement", name: "月度通行账单" },
];
const policies = [
  { value: "review", name: "暂不计入费用（待处理）" },
  { value: "retain", name: "仅留存打印" },
  { value: "expense", name: "计入本期费用" },
];
const fields = [
  "period_id",
  "office_id",
  "category_id",
  "product_line_id",
  "invoice_number",
  "invoice_date",
  "vendor",
  "description",
  "amount",
  "tax_amount",
  "total_amount",
  "document_kind",
  "inclusion_policy",
  "occurrence_month",
  "settlement_month",
  "print_selected",
  "remarks",
];
Page({
  data: {
    busy: false,
    message: "",
    invoice: null,
    snapshot: "",
    confirmed: false,
    kinds,
    policies,
    periods: [],
    offices: [],
    categories: [],
    product_lines: [],
    textFields: [
      { key: "invoice_number", name: "发票号码" },
      { key: "vendor", name: "商家/销售方" },
      { key: "description", name: "票面摘要" },
      { key: "remarks", name: "备注" },
    ],
    moneyFields: [
      { key: "amount", name: "未税金额" },
      { key: "tax_amount", name: "税额" },
      { key: "total_amount", name: "价税合计" },
    ],
  },
  async onLoad(options) {
    this.id = Number(options.id);
    if (!Number.isInteger(this.id) || this.id <= 0) {
      this.setData({ message: "票据不存在" });
      return;
    }
    await this.load(options.recognize === "1");
  },
  async load(recognize = false) {
    this.setData({ busy: true, confirmed: false, message: "" });
    try {
      const [refs, detail] = await Promise.all([
        api.request("/api/mobile/bootstrap"),
        api.request("/api/mobile/invoices/" + this.id),
      ]);
      this.setData({
        ...refs,
        categories: [{ id: null, name: "未选择" }, ...refs.categories],
        product_lines: [{ id: null, name: "未选择" }, ...refs.product_lines],
        invoice: detail.invoice,
        snapshot: detail.snapshot,
      });
      this.indices();
      if (recognize && !detail.invoice.amount_confirmed)
        await this.recognize(false);
    } catch (e) {
      this.setData({ message: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  indices() {
    const i = this.data.invoice;
    const allowed =
      i.document_kind === "invoice"
        ? policies
        : policies.filter((p) => p.value !== "expense");
    const update = { policies: allowed };
    if (i.document_kind !== "invoice" && i.inclusion_policy === "expense") {
      i.inclusion_policy = "retain";
      update["invoice.inclusion_policy"] = "retain";
    }
    for (const [key, items] of [
      ["period_id", "periods"],
      ["office_id", "offices"],
      ["category_id", "categories"],
      ["product_line_id", "product_lines"],
    ])
      update[key + "Index"] = Math.max(
        0,
        this.data[items].findIndex((r) => r.id === i[key]),
      );
    update.kindIndex = Math.max(
      0,
      kinds.findIndex((k) => k.value === i.document_kind),
    );
    update.policyIndex = Math.max(
      0,
      allowed.findIndex((p) => p.value === i.inclusion_policy),
    );
    this.setData(update);
  },
  input(e) {
    const key = e.currentTarget.dataset.key;
    if (!fields.includes(key)) return;
    this.setData({ ["invoice." + key]: e.detail.value, confirmed: false });
  },
  pick(e) {
    const { key, list } = e.currentTarget.dataset;
    const index = Number(e.detail.value);
    const item = this.data[list]?.[index];
    if (!item) return;
    this.setData({
      ["invoice." + key]: "id" in item ? item.id : item.value,
      [key + "Index"]: index,
      confirmed: false,
    });
    this.indices();
  },
  toggle(e) {
    this.setData({
      ["invoice." + e.currentTarget.dataset.key]: e.detail.value,
      confirmed: false,
    });
  },
  agree(e) {
    this.setData({ confirmed: e.detail.value });
  },
  async recognize(retry = true) {
    if (!this.data.invoice) return;
    this.setData({
      busy: true,
      message: "正在识别，请稍候；原件已安全保存。",
      confirmed: false,
    });
    try {
      const result = await api.request(
        "/api/mobile/invoices/" + this.id + "/recognize",
        { method: "POST", data: { retry }, timeout: 90000 },
      );
      if (result.snapshot !== this.data.snapshot) {
        this.setData({
          message: "票据已变化，请返回后重新打开，避免覆盖网站修改。",
        });
        return;
      }
      if (result.success) {
        this.setData({
          invoice: { ...this.data.invoice, ...result.draft },
          message:
            "识别为建议，请逐项核对；类别和产品线需自行选择。确认前不改变网站费用。",
        });
      } else
        this.setData({
          message: "未识别出完整信息，可手工补录后确认，或稍后重新识别。",
        });
    } catch (e) {
      this.setData({ message: e.message || "识别未完成，可重试或手动填写" });
    } finally {
      this.setData({ busy: false });
    }
  },
  retryRecognize() {
    if (!this.data.busy) this.recognize(true);
  },
  async save() {
    if (this.data.busy || !this.data.confirmed) {
      this.setData({ message: "请先核对原件、金额和归属，并勾选确认。" });
      return;
    }
    const data = { snapshot: this.data.snapshot, confirmed: true };
    for (const key of fields) data[key] = this.data.invoice[key];
    this.setData({ busy: true });
    try {
      const result = await api.request(
        "/api/mobile/invoices/" + this.id + "/confirm",
        { method: "POST", data },
      );
      this.setData({
        invoice: result.invoice,
        snapshot: result.snapshot,
        confirmed: false,
        message: "已确认录入，同步到网站；费用按所选计入口径处理。",
      });
      this.indices();
    } catch (e) {
      this.setData({ message: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  async original() {
    const current = api.session();
    if (!current) {
      this.setData({ message: "请重新登录" });
      return;
    }
    try {
      const path = await new Promise((resolve, reject) =>
        wx.downloadFile({
          url: api.apiOrigin + "/api/mobile/invoices/" + this.id + "/file",
          header: { Authorization: "Bearer " + current.access_token },
          success: (r) =>
            r.statusCode === 200
              ? resolve(r.tempFilePath)
              : reject(new Error("原件不可用")),
          fail: () => reject(new Error("原件下载失败")),
        }),
      );
      if (api.session()?.access_token !== current.access_token)
        throw new Error("登录状态已变化，请重新打开原件");
      if (/\.pdf$/i.test(this.data.invoice.file_name))
        wx.openDocument({ filePath: path, fileType: "pdf", showMenu: true });
      else wx.previewImage({ urls: [path] });
    } catch (e) {
      this.setData({ message: e.message });
    }
  },
});

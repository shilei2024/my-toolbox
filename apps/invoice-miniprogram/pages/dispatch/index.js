const api = require("../../lib/api"),
  auth = require("../../lib/auth"),
  context = require("../../lib/context");
const textFields = [
  { key: "from_location", name: "出发地" },
  { key: "to_location", name: "目的地" },
  { key: "contact", name: "联系人" },
];
const numberFields = [
  { key: "km_start", name: "起始公里" },
  { key: "km_total", name: "实际行驶公里" },
  { key: "toll_fee", name: "过桥费（元）" },
  { key: "parking_fee", name: "停车费（元）" },
];
Page({
  data: {
    authReady: false,
    loggedIn: false,
    busy: false,
    dirty: false,
    message: "",
    periodId: null,
    periodName: "",
    rows: [],
    snapshot: "",
    totals: null,
    lines: [],
    lineIndex: 0,
    editing: false,
    editIndex: -1,
    startEditable: false,
    draft: {},
    textFields,
    numberFields,
  },
  onShow() {
    auth.sync(this);
    const loggedIn = this.data.loggedIn;
    const epoch = context.state().authEpoch;
    if (this._epoch !== epoch) {
      this._epoch = epoch;
      this.setData({
        rows: [],
        editing: false,
        dirty: false,
        periodId: null,
        loggedIn,
      });
    }
    if (!loggedIn) {
      this.setData({
        loggedIn: false,
        rows: [],
        editing: false,
        dirty: false,
        periodId: null,
      });
      return;
    }
    if (!this.data.dirty && !this.data.editing) this.load();
  },
  async load() {
    if (this.data.busy) return;
    let again = false;
    this.setData({ busy: true, message: "" });
    try {
      const refs = await api.request("/api/mobile/bootstrap");
      const index = context.choose(refs.periods),
        p = refs.periods[index];
      if (!p) {
        this.setData({
          loggedIn: true,
          rows: [],
          message: "请先在网站创建报销周期",
        });
        return;
      }
      const d = await api.request("/api/mobile/dispatch/" + p.id);
      if (context.state().periodId !== p.id) {
        again = true;
        return;
      }
      this.setData({
        loggedIn: true,
        periodId: p.id,
        periodName: p.name,
        rows: d.rows,
        snapshot: d.snapshot,
        totals: d.totals,
        lines: [{ name: "请选择产品线" }, ...refs.product_lines],
        dirty: false,
        editing: false,
      });
      context.state().dispatchDirty = false;
    } catch (e) {
      this.setData({ message: e.message });
    } finally {
      this.setData({ busy: false });
      if (again) this.load();
    }
  },
  goMine() {
    wx.switchTab({ url: "/pages/mine/index" });
  },
  add() {
    if (this.data.busy) return;
    context.state().dispatchDirty = true;
    const now = new Date(),
      day =
        now.getFullYear() +
        "-" +
        String(now.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(now.getDate()).padStart(2, "0");
    this.setData({
      editing: true,
      editIndex: -1,
      lineIndex: 0,
      draft: {
        id: null,
        date: day,
        from_location: "",
        to_location: "",
        contact: "",
        km_start: "",
        km_total: "",
        toll_fee: "0",
        parking_fee: "0",
        product_line: "",
      },
      message: "",
    });
    this.syncMileage();
  },
  edit(e) {
    if (this.data.busy) return;
    const index = Number(e.currentTarget.dataset.index),
      row = this.data.rows[index];
    if (!row) return;
    if (row.allocated) {
      this.setData({ message: "此行已分摊账单，请先在网站撤销分摊再修改。" });
      return;
    }
    context.state().dispatchDirty = true;
    this.setData({
      editing: true,
      editIndex: index,
      draft: { ...row },
      lineIndex: Math.max(
        0,
        this.data.lines.findIndex((p) => p.name === row.product_line),
      ),
      message: "",
    });
    this.syncMileage();
  },
  input(e) {
    if (this.data.busy) return;
    const key = e.currentTarget.dataset.key;
    if (key === "km_start" && !this.data.startEditable) return;
    this.setData({ ["draft." + key]: e.detail.value });
    if (key === "date") this.syncMileage();
  },
  orderedDraft() {
    const rows = this.data.rows.map((row, index) => ({
      ...row,
      _editing: index === this.data.editIndex,
      ...(index === this.data.editIndex ? this.data.draft : {}),
    }));
    if (this.data.editIndex < 0) rows.push({ ...this.data.draft, _editing: true });
    return rows.sort((a, b) => String(a.date).localeCompare(String(b.date)));
  },
  syncMileage() {
    const rows = this.orderedDraft();
    const index = rows.findIndex((row) => row._editing);
    const startEditable = index === 0;
    let start = this.data.draft.km_start;
    if (startEditable && !this.data.startEditable) {
      start = this.data.rows[0]?.km_start ?? "";
    } else if (!startEditable) {
      const base = this.data.rows[0]?.km_start;
      start = base === "" || base == null ? "" : (
        (Math.round(Number(base) * 100) + rows.slice(0, index).reduce(
          (sum, row) => sum + Math.round(Number(row.km_total || 0) * 100), 0,
        )) / 100
      ).toFixed(2);
    }
    this.setData({ startEditable, "draft.km_start": start });
  },
  line(e) {
    const index = Number(e.detail.value);
    this.setData({
      lineIndex: index,
      "draft.product_line": index ? this.data.lines[index].name : "",
    });
  },
  cancel() {
    if (this.data.busy) return;
    this.setData({ editing: false, draft: {}, editIndex: -1, lineIndex: 0, message: "" });
    context.state().dispatchDirty = this.data.dirty;
  },
  editorError(message) {
    this.setData({ message });
    if (wx.pageScrollTo) wx.pageScrollTo({ selector: "#dispatch-editor-feedback", duration: 150 });
  },
  async keep() {
    if (this.data.busy) return;
    if (
      !this.data.draft.date ||
      this.data.draft.km_total == null ||
      this.data.draft.km_total === "" ||
      !this.data.draft.product_line
    ) {
      this.editorError("请填写日期、实际公里数及产品线。");
      return;
    }
    const rows = this.orderedDraft().map(({ _editing, ...row }, index) => ({
      ...row,
      km_start: index === 0
        ? (_editing ? this.data.draft.km_start : this.data.rows[0]?.km_start ?? "")
        : "",
    }));
    if (!/^\d+(\.\d{1,2})?$/.test(String(rows[0].km_start))) {
      this.editorError("请先填写首行起始公里（最多两位小数）。");
      return;
    }
    await this.save(rows);
  },
  async remove(e) {
    if (this.data.busy) return;
    const index = Number(e.currentTarget.dataset.index);
    if (this.data.rows[index].allocated) {
      this.setData({ message: "此行已分摊，需先在网站撤销。" });
      return;
    }
    const yes = await new Promise((resolve) =>
      wx.showModal({
        title: "删除派车行",
        content: "此行也会从网站删除，是否继续？",
        success: (r) => resolve(r.confirm),
        fail: () => resolve(false),
      }),
    );
    if (yes && !this.data.busy) await this.save(this.data.rows.filter((_, i) => i !== index));
  },
  async save(rows = this.data.rows) {
    if (this.data.busy) return;
    this.setData({ busy: true, message: "" });
    try {
      const d = await api.request(
        "/api/mobile/dispatch/" + this.data.periodId,
        {
          method: "PUT",
          data: { rows, snapshot: this.data.snapshot },
        },
      );
      this.setData({
        rows: d.rows,
        snapshot: d.snapshot,
        totals: d.totals,
        dirty: false,
        editing: false,
        draft: {},
        editIndex: -1,
        lineIndex: 0,
        message: "已保存并返回派车列表",
      });
      context.state().dispatchDirty = false;
      if (wx.pageScrollTo) wx.pageScrollTo({ scrollTop: 0, duration: 0 });
    } catch (e) {
      const message = e.status === 409 && this.data.editing
        ? e.message + "；请取消编辑后刷新核对。" : e.message;
      if (this.data.editing) this.editorError(message);
      else this.setData({ message });
    } finally {
      this.setData({ busy: false });
    }
  },
  async reload() {
    if (this.data.busy) return;
    if (this.data.dirty || this.data.editing) {
      const yes = await new Promise((resolve) =>
        wx.showModal({
          title: "放弃本机修改？",
          content: "刷新会读取网站最新记录，未保存修改将丢弃。",
          success: (r) => resolve(r.confirm),
          fail: () => resolve(false),
        }),
      );
      if (!yes) return;
    }
    await this.load();
  },
});

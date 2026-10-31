const api = require("../../lib/api"),
  auth = require("../../lib/auth"),
  context = require("../../lib/context");
const textFields = [
  { key: "from_location", name: "出发地" },
  { key: "to_location", name: "目的地" },
  { key: "contact", name: "联系人" },
];
const numberFields = [
  { key: "km_start", name: "首次起始公里（其余行自动承接）" },
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
  },
  edit(e) {
    if (this.data.busy) return;
    const index = Number(e.currentTarget.dataset.index),
      row = this.data.rows[index];
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
  },
  input(e) {
    this.setData({ ["draft." + e.currentTarget.dataset.key]: e.detail.value });
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
    this.setData({ editing: false });
    context.state().dispatchDirty = this.data.dirty;
  },
  keep() {
    if (this.data.busy) return;
    if (
      !this.data.draft.date ||
      this.data.draft.km_total === "" ||
      !this.data.draft.product_line
    ) {
      this.setData({ message: "请填写日期、实际公里数及产品线。" });
      return;
    }
    const rows = [...this.data.rows];
    if (this.data.editIndex < 0) rows.push({ ...this.data.draft });
    else rows[this.data.editIndex] = { ...this.data.draft };
    this.setData({
      rows,
      editing: false,
      dirty: true,
      message: "修改待保存；点击“保存派车单”同步网站。",
    });
    context.state().dispatchDirty = true;
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
        content: "保存后此行也会从网站删除，是否继续？",
        success: (r) => resolve(r.confirm),
        fail: () => resolve(false),
      }),
    );
    if (yes) {
      this.setData({
        rows: this.data.rows.filter((_, i) => i !== index),
        dirty: true,
      });
      context.state().dispatchDirty = true;
    }
  },
  async save() {
    if (this.data.busy || this.data.editing) return;
    this.setData({ busy: true, message: "" });
    try {
      const d = await api.request(
        "/api/mobile/dispatch/" + this.data.periodId,
        {
          method: "PUT",
          data: { rows: this.data.rows, snapshot: this.data.snapshot },
        },
      );
      this.setData({
        rows: d.rows,
        snapshot: d.snapshot,
        totals: d.totals,
        dirty: false,
        message: "已保存并同步网站、仪表盘及派车单导出。",
      });
      context.state().dispatchDirty = false;
    } catch (e) {
      this.setData({ message: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  async reload() {
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

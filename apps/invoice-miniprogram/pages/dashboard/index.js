const api = require("../../lib/api"),
  context = require("../../lib/context");
Page({
  data: {
    loggedIn: false,
    busy: false,
    message: "",
    periods: [],
    periodIndex: 0,
    summary: null,
    creating: false,
    newMonth: "",
  },
  onShow() {
    const epoch = context.state().authEpoch;
    if (this._epoch !== epoch) {
      this._epoch = epoch;
      this.setData({ summary: null, periods: [], loggedIn: false });
    }
    this.refresh();
  },
  async refresh() {
    if (!api.session()) {
      this.setData({
        loggedIn: false,
        summary: null,
        periods: [],
        message: "请先到“我的”登录网站账号。",
      });
      return;
    }
    if (this.data.busy) return;
    this.setData({ busy: true, message: "" });
    try {
      const refs = await api.request("/api/mobile/bootstrap");
      const index = context.choose(refs.periods);
      this.setData({
        loggedIn: true,
        periods: refs.periods,
        periodIndex: index,
      });
      await this.loadSummary();
    } catch (e) {
      this.setData({ summary: null, message: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  async loadSummary() {
    const period = this.data.periods[this.data.periodIndex];
    if (!period) {
      this.setData({ summary: null, message: "请先在网站创建报销周期" });
      return;
    }
    const summary = await api.request("/api/mobile/dashboard/" + period.id);
    if (this.data.periods[this.data.periodIndex]?.id === period.id)
      this.setData({ summary });
  },
  async period(e) {
    if (context.state().uploading || context.state().dispatchDirty) {
      this.setData({ message: "请先完成上传或保存派车修改，再切换当期。" });
      return;
    }
    this.setData({ periodIndex: Number(e.detail.value), message: "" });
    context.state().periodId = this.data.periods[this.data.periodIndex].id;
    try {
      await this.loadSummary();
    } catch (e) {
      this.setData({ summary: null, message: e.message });
    }
  },
  defaultMonth(periods) {
    const now = new Date();
    let year = now.getFullYear(),
      month = now.getMonth() + 1;
    const latest = (periods || []).reduce((best, item) => {
      if (!item || !item.end_year || !item.end_month) return best;
      const order = item.end_year * 12 + item.end_month;
      return !best || order > best.order
        ? { order, year: item.end_year, month: item.end_month }
        : best;
    }, null);
    if (latest && latest.order >= year * 12 + month) {
      year = latest.month === 12 ? latest.year + 1 : latest.year;
      month = latest.month === 12 ? 1 : latest.month + 1;
    }
    return year + "-" + String(month).padStart(2, "0");
  },
  toggleCreate() {
    if (this.data.busy) return;
    this.setData({
      creating: !this.data.creating,
      newMonth: this.data.creating ? "" : this.defaultMonth(this.data.periods),
      message: "",
    });
  },
  onNewMonth(e) {
    this.setData({ newMonth: e.detail.value });
  },
  async createPeriod() {
    if (this.data.busy) return;
    const [year, month] = String(this.data.newMonth || "")
      .split("-")
      .map(Number);
    if (!year || !month) {
      this.setData({ message: "请选择新周期的起始月份" });
      return;
    }
    this.setData({ busy: true, message: "" });
    try {
      const created = await api.request("/api/mobile/periods", {
        method: "POST",
        data: { start_year: year, start_month: month },
      });
      context.state().periodId = created.period.id;
      this.setData({ creating: false, newMonth: "", busy: false });
      await this.refresh();
      this.setData({ message: "已创建周期：" + created.period.name });
    } catch (e) {
      this.setData({ message: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  goMine() {
    wx.switchTab({ url: "/pages/mine/index" });
  },
  goInvoices() {
    wx.switchTab({ url: "/pages/home/index" });
  },
  goDispatch() {
    wx.switchTab({ url: "/pages/dispatch/index" });
  },
  async onPullDownRefresh() {
    try {
      await this.refresh();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
});

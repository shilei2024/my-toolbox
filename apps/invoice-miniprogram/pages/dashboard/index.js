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
        message: "请先到“我的”登录并绑定网站账号。",
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

const api = require("../../lib/api"),
  context = require("../../lib/context");
Page({
  data: {
    loggedIn: false,
    busy: false,
    message: "",
    bindingCode: "",
    displayName: "",
    showPrivacy: false,
  },
  onLoad() {
    this.privacyHandler = (resolve) => {
      this.resolvePrivacy = resolve;
      this.setData({ showPrivacy: true });
    };
  },
  onShow() {
    if (wx.onNeedPrivacyAuthorization)
      wx.onNeedPrivacyAuthorization(this.privacyHandler);
    this.restore();
  },
  onHide() {
    if (wx.offNeedPrivacyAuthorization)
      wx.offNeedPrivacyAuthorization(this.privacyHandler);
  },
  onUnload() {
    this.onHide();
    if (this.resolvePrivacy) this.resolvePrivacy({ event: "disagree" });
  },
  agreePrivacy() {
    if (this.resolvePrivacy)
      this.resolvePrivacy({ event: "agree", buttonId: "mine-privacy-agree" });
    this.resolvePrivacy = null;
    this.setData({ showPrivacy: false });
  },
  declinePrivacy() {
    if (this.resolvePrivacy) this.resolvePrivacy({ event: "disagree" });
    this.resolvePrivacy = null;
    this.setData({ showPrivacy: false });
  },
  async restore() {
    if (!api.session()) {
      this.setData({ loggedIn: false, displayName: "" });
      return;
    }
    try {
      const d = await api.request("/api/mobile/bootstrap");
      this.setData({
        loggedIn: true,
        displayName: d.display_name,
        message: "",
      });
    } catch (e) {
      this.setData({ loggedIn: !!api.session(), message: e.message });
    }
  },
  onBindingInput(e) {
    this.setData({ bindingCode: e.detail.value.trim() });
  },
  async signIn() {
    if (this.data.busy || context.state().uploading) return;
    this.setData({ busy: true, message: "" });
    try {
      const login = await api.login(this.data.bindingCode || undefined);
      context.clear();
      this.setData({
        loggedIn: true,
        displayName: login.display_name,
        bindingCode: "",
      });
      const d = await api.request("/api/mobile/bootstrap");
      context.choose(d.periods);
      this.setData({ message: "已登录并连接网站账号" });
      wx.switchTab({ url: "/pages/dashboard/index" });
    } catch (e) {
      this.setData({ message: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  scanBinding() {
    if (this.data.busy) return;
    wx.scanCode({
      onlyFromCamera: true,
      scanType: ["qrCode"],
      success: (r) => {
        if (!/^[A-Za-z0-9_-]{32}$/.test(r.result)) {
          this.setData({ message: "请扫描网站个人资料生成的绑定二维码" });
          return;
        }
        this.setData({ bindingCode: r.result });
        this.signIn();
      },
      fail: () => this.setData({ message: "扫码未完成，也可粘贴一次性绑定码" }),
    });
  },
  async logout() {
    if (this.data.busy) return;
    if (context.state().uploading) {
      this.setData({ message: "请等待当前上传及识别完成后退出" });
      return;
    }
    if (context.state().dispatchDirty) {
      const confirm = await new Promise((resolve) =>
        wx.showModal({
          title: "派车单尚未保存",
          content: "退出将放弃本机未保存的修改，是否继续？",
          success: (r) => resolve(r.confirm),
          fail: () => resolve(false),
        }),
      );
      if (!confirm) return;
    }
    this.setData({ busy: true });
    try {
      await api.request("/api/mobile/logout", { method: "POST" });
    } catch (e) {
    } finally {
      api.clearSession();
      context.clear();
      this.setData({
        busy: false,
        loggedIn: false,
        displayName: "",
        bindingCode: "",
        message: "已退出；网站绑定关系仍保留",
      });
    }
  },
  showPrivacy() {
    if (wx.openPrivacyContract)
      wx.openPrivacyContract({
        fail: () => this.setData({ message: "隐私指引暂不可用" }),
      });
  },
});

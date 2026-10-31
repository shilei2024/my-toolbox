const { apiOrigin } = require("../config");
const SESSION_KEY = "invoice_session_v1";
let loginAttempt = 0;

function session() {
  const stored = wx.getStorageSync(SESSION_KEY);
  return stored && Date.parse(stored.expires_at) > Date.now() ? stored : null;
}
function clearSession() {
  loginAttempt++;
  wx.removeStorageSync(SESSION_KEY);
}
function error(message, status) {
  return Object.assign(new Error(message), { status });
}
function response(status, data, clearOn401 = true) {
  if (status === 401 && clearOn401) clearSession();
  if (status < 200 || status >= 300)
    throw error(data.error || "操作失败，请稍后重试", status);
  return data;
}
function request(
  path,
  { method = "GET", data, authenticated = true, timeout = 20000 } = {},
) {
  if (!path.startsWith("/api/mobile/"))
    return Promise.reject(error("请求地址无效"));
  const current = session();
  if (authenticated && !current)
    return Promise.reject(error("请先登录小程序", 401));
  return new Promise((resolve, reject) =>
    wx.request({
      url: apiOrigin + path,
      method,
      data,
      timeout,
      header: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(authenticated
          ? { Authorization: "Bearer " + current.access_token }
          : {}),
      },
      success: (res) => {
        try {
          if (authenticated && session()?.access_token !== current.access_token)
            throw error("登录状态已变化，请刷新当前页面", 409);
          resolve(response(res.statusCode, res.data || {}, authenticated));
        } catch (e) {
          reject(e);
        }
      },
      fail: () => reject(error("网络连接失败，请检查网络后重试")),
    }),
  );
}
function login(bindingCode) {
  const attempt = ++loginAttempt,
    startingToken = session()?.access_token;
  return new Promise((resolve, reject) =>
    wx.login({
      timeout: 10000,
      success: async (res) => {
        try {
          if (!res.code) throw error("未取得微信登录凭证，请重试");
          const data = await request("/api/mobile/session", {
            method: "POST",
            authenticated: false,
            data: {
              code: res.code,
              ...(bindingCode ? { binding_code: bindingCode } : {}),
            },
          });
          saveLogin(data, attempt, startingToken, "wechat");
          resolve(data);
        } catch (e) {
          reject(e);
        }
      },
      fail: () => reject(error("微信登录未完成，请重试")),
    }),
  );
}
function saveLogin(data, attempt, startingToken, method) {
  if (attempt !== loginAttempt || session()?.access_token !== startingToken)
    throw error("登录状态已变化，请重新登录", 409);
  wx.setStorageSync(SESSION_KEY, {
    access_token: data.access_token,
    expires_at: data.expires_at,
    auth_method: method,
  });
}
async function passwordLogin(email, password) {
  const attempt = ++loginAttempt,
    startingToken = session()?.access_token;
  const data = await request("/api/mobile/session/password", {
    method: "POST",
    authenticated: false,
    data: { email, password },
  });
  saveLogin(data, attempt, startingToken, "password");
  return data;
}
function privacy() {
  return new Promise((resolve, reject) => {
    if (typeof wx.requirePrivacyAuthorize !== "function")
      return reject(error("请升级微信后使用文件上传"));
    wx.requirePrivacyAuthorize({
      success: resolve,
      fail: () => reject(error("需要同意隐私说明后才能选择票据")),
    });
  });
}
function upload(item, onProgress) {
  const current = session();
  if (!current)
    return Promise.reject(error("登录已失效，请重新登录后重新选择文件", 401));
  return new Promise((resolve, reject) => {
    const task = wx.uploadFile({
      url: apiOrigin + "/api/mobile/invoices",
      filePath: item.path,
      name: "file",
      timeout: 60000,
      header: {
        Authorization: "Bearer " + current.access_token,
        Accept: "application/json",
      },
      formData: {
        ...item.intent,
        idempotency_key: item.key,
        file_name: item.name,
      },
      success: (res) => {
        try {
          if (session()?.access_token !== current.access_token)
            throw error("登录状态已变化，请刷新当前页面", 409);
          resolve(response(res.statusCode, JSON.parse(res.data)));
        } catch (e) {
          reject(
            e instanceof SyntaxError
              ? error("服务器响应异常，可使用原文件重试")
              : e,
          );
        }
      },
      fail: () =>
        reject(error("网络中断，可点击重试；已保存的票据不会重复扣次")),
    });
    task.onProgressUpdate((res) => onProgress(res.progress));
  });
}
function key() {
  return (
    Date.now().toString(36) +
    "-" +
    Math.random().toString(36).slice(2) +
    "-" +
    Math.random().toString(36).slice(2)
  );
}
module.exports = {
  request,
  login,
  passwordLogin,
  upload,
  privacy,
  session,
  clearSession,
  key,
  apiOrigin,
};

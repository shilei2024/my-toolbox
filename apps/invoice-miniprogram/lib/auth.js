const api = require("./api");

function current() {
  return !!api.session();
}

function loadedPages() {
  try {
    return typeof getCurrentPages === "function" ? getCurrentPages() || [] : [];
  } catch (e) {
    return [];
  }
}

// Pages must not render the login entry before the local session is known.
function sync(page) {
  if (!page || typeof page.setData !== "function") return;
  page.setData({ authReady: true, loggedIn: current() });
}

// Login/logout happens on "我的"; already loaded tabs keep the previous
// account's state. Hide their gated content until onShow syncs the new session.
function invalidate(except) {
  loadedPages().forEach((page) => {
    if (page !== except && page && typeof page.setData === "function")
      page.setData({ authReady: false });
  });
}

module.exports = { current, sync, invalidate };

let fallback = {};
function state() {
  try {
    const app = getApp();
    return app.globalData || (app.globalData = {});
  } catch (e) {
    return fallback;
  }
}
function choose(periods) {
  const s = state();
  let index = periods.findIndex((p) => p.id === s.periodId);
  if (index < 0)
    index = Math.max(
      0,
      periods.findIndex((p) => p.is_active),
    );
  s.periodId = periods[index]?.id;
  return index;
}
function clear() {
  const s = state();
  delete s.periodId;
  s.uploading = false;
  s.dispatchDirty = false;
  s.authEpoch = (s.authEpoch || 0) + 1;
}
module.exports = { state, choose, clear };

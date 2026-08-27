(() => {
  "use strict";
  const root = document.querySelector("[data-cp-project-id][data-cp-project-version]");
  if (!root) return;
  const projectId = root.dataset.cpProjectId;
  const initialVersion = Number(root.dataset.cpProjectVersion);
  const alert = root.querySelector("[data-cp-update-alert]");
  if (!projectId || !Number.isFinite(initialVersion) || !alert) return;

  const checkVersion = async () => {
    if (document.visibilityState !== "visible") return;
    try {
      const response = await fetch(`/api/v1/customer-projects/projects/${encodeURIComponent(projectId)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const payload = await response.json();
      if (Number(payload?.data?.version) !== initialVersion) alert.classList.remove("d-none");
    } catch (_) {
      // A failed background check must not disturb an in-progress edit.
    }
  };

  window.setInterval(checkVersion, 25000);
})();

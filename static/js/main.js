// Tiny global helpers.
document.addEventListener("DOMContentLoaded", () => {
  // Auto-dismiss success alerts after 5s.
  document.querySelectorAll(".alert-success").forEach((el) => {
    setTimeout(() => {
      try { bootstrap.Alert.getOrCreateInstance(el).close(); } catch (_) {}
    }, 5000);
  });
});

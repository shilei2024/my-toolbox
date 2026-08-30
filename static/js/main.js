// Small global helpers shared by every server-rendered page.
document.addEventListener("DOMContentLoaded", () => {
  const validThemes = ["obsidian", "github", "bright"];
  const root = document.documentElement;
  const options = document.querySelectorAll("[data-theme-option]");

  function activeTheme() {
    return validThemes.includes(root.dataset.theme) ? root.dataset.theme : "obsidian";
  }

  function renderThemeSelection() {
    const selected = activeTheme();
    options.forEach((option) => {
      const isSelected = option.dataset.themeOption === selected;
      option.classList.toggle("is-selected", isSelected);
      option.setAttribute("aria-pressed", String(isSelected));
    });
  }

  options.forEach((option) => {
    option.addEventListener("click", () => {
      const theme = option.dataset.themeOption;
      if (!validThemes.includes(theme)) return;
      root.dataset.theme = theme;
      try { localStorage.setItem("my-toolbox-theme", theme); } catch (_) {}
      renderThemeSelection();
    });
  });
  renderThemeSelection();

  // Auto-dismiss success alerts after 5s.
  document.querySelectorAll(".alert-success").forEach((el) => {
    setTimeout(() => {
      try { bootstrap.Alert.getOrCreateInstance(el).close(); } catch (_) {}
    }, 5000);
  });
});

// Client-side page-range validation for the PDF split tool.
(function () {
  // ----- PDF split: validate range pattern on input -----
  const ranges = document.getElementById("ranges");
  const submit = document.getElementById("submitBtn");
  if (ranges && submit) {
    const re = /^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$/;
    function check() {
      const ok = re.test(ranges.value || "");
      submit.disabled = !ok;
      document.getElementById("rangesHelp").classList.toggle("text-danger", !ok);
    }
    ranges.addEventListener("input", check);
    check();
  }
})();

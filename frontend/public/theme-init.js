// Runs before first paint so dark mode does not flash. External file: the site's CSP blocks inline scripts.
(function () {
  try {
    var m = localStorage.getItem("policyc.theme") || "system";
    var dark = m === "dark" || (m === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) document.documentElement.classList.add("dark");
  } catch (e) {}
})();

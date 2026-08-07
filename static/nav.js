// The "Browse" disclosure in the header. <details> handles open/close and
// keyboard access on its own; all this adds is the two behaviours it lacks —
// closing on an outside click, and closing on Escape.
(function () {
  var more = document.querySelector(".nav-more");
  if (!more) return;

  document.addEventListener("click", function (e) {
    if (more.open && !more.contains(e.target)) more.open = false;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && more.open) {
      more.open = false;
      var summary = more.querySelector("summary");
      if (summary) summary.focus();
    }
  });

  // A menu link closes the panel before navigating, so returning via the
  // back button doesn't land on a page with the menu still hanging open.
  more.addEventListener("click", function (e) {
    if (e.target.tagName === "A") more.open = false;
  });
})();

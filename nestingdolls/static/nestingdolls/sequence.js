(() => {
  const prefix = "__prefix__";

  function activeRows(root) {
    return [...root.querySelectorAll("[data-sequence-row]")].filter(
      (row) => !row.hidden,
    );
  }

  function removeRow(row) {
    row.querySelector("[data-sequence-delete]").value = "1";
    row.hidden = true;
    row.querySelectorAll("input, select, textarea, button").forEach((control) => {
      if (!control.matches("[data-sequence-delete]")) control.disabled = true;
    });
  }

  function addRow(root) {
    const maximum = Number(root.dataset.sequenceMaximum);
    const absoluteMaximum = Number(root.dataset.sequenceAbsoluteMaximum);
    const total = root.querySelector("[data-sequence-total]");
    const index = Number(total.value);
    if (activeRows(root).length >= maximum || index >= absoluteMaximum) return;

    const fragment = root.querySelector("[data-sequence-empty-row]").content.cloneNode(true);
    for (const element of fragment.querySelectorAll("[name], [id], label[for]")) {
      for (const attribute of ["name", "id", "for"]) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll(prefix, index));
        }
      }
    }
    const row = fragment.querySelector("[data-sequence-row]");
    row.dataset.sequenceIndex = index;
    root.querySelector("[data-sequence-rows]").append(fragment);
    total.value = index + 1;
  }

  function start() {
    document.querySelectorAll("[data-sequence-widget]").forEach((root) => {
      root.addEventListener("click", (event) => {
        const add = event.target.closest("[data-sequence-add]");
        if (add && root.contains(add)) {
          addRow(root);
          return;
        }
        const remove = event.target.closest("[data-sequence-remove]");
        if (remove && root.contains(remove)) removeRow(remove.closest("[data-sequence-row]"));
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

(() => {
  const prefix = "__prefix__";

  function activeRows(root) {
    return [...root.querySelectorAll("[data-sequence-row]")].filter(
      (row) => !row.hidden,
    );
  }

  function deletedExtraRow(root, initialCount) {
    return [...root.querySelectorAll("[data-sequence-row]")].find((row) => {
      const index = Number(row.dataset.sequenceIndex);
      return row.hidden && index >= initialCount;
    });
  }

  function setRemoved(row, removed) {
    const marker = row.querySelector("[data-sequence-delete]");
    marker.value = removed ? "1" : "";
    row.hidden = removed;
    for (const control of row.querySelectorAll("input, select, textarea, button")) {
      if (control === marker) continue;
      if (!control.dataset.sequenceWasDisabled) {
        control.dataset.sequenceWasDisabled = control.disabled ? "1" : "0";
      }
      control.disabled = removed || control.dataset.sequenceWasDisabled === "1";
    }
  }

  function addRow(root) {
    const maximum = Number(root.dataset.sequenceMaximum);
    if (activeRows(root).length >= maximum) return;

    const initialCount = Number(root.dataset.sequenceInitialCount);
    const reusable = deletedExtraRow(root, initialCount);
    if (reusable) {
      setRemoved(reusable, false);
      return;
    }

    const total = root.querySelector("[data-sequence-total]");
    const index = Number(total.value);
    const template = root.querySelector("[data-sequence-empty-row]");
    const fragment = template.content.cloneNode(true);
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

  function initialize(root) {
    root.addEventListener("click", (event) => {
      const add = event.target.closest("[data-sequence-add]");
      if (add && root.contains(add)) {
        addRow(root);
        return;
      }
      const remove = event.target.closest("[data-sequence-remove]");
      if (remove && root.contains(remove)) {
        setRemoved(remove.closest("[data-sequence-row]"), true);
      }
    });
  }

  function start() {
    document.querySelectorAll("[data-sequence-widget]").forEach(initialize);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

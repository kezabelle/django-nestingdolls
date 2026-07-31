((): void => {
  const prefix = "__prefix__";

  function queryRequiredElement<E extends Element>(
    parent: ParentNode,
    selector: string,
  ): E {
    const element = parent.querySelector<E>(selector);
    if (!element) {
      throw new Error(`Missing required element: ${selector}`);
    }
    return element;
  }

  function parseRequiredInteger(
    value: string | undefined,
    description: string,
  ): number {
    if (!value) {
      throw new Error(`Missing required integer value for ${description}`);
    }
    const parsed = Number.parseInt(value, 10);
    if (!Number.isSafeInteger(parsed)) {
      throw new Error(`Invalid integer value for ${description}: ${value}`);
    }
    return parsed;
  }

  function activeRows(root: HTMLElement): HTMLElement[] {
    return Array.from(
      root.querySelectorAll<HTMLElement>("[data-sequence-row]"),
    ).filter((row) => !row.hidden);
  }

  function ensureRemoveButton(row: HTMLElement): void {
    const root = row.closest<HTMLElement>("[data-sequence-widget]");
    if (!root) {
      return;
    }
    ensureRemoveButtonInRoot(row, root);
  }

  function ensureRemoveButtonInRoot(
    row: HTMLElement,
    root: HTMLElement,
  ): void {
    if (row.querySelector("[data-sequence-remove]")) {
      return;
    }
    const template = queryRequiredElement<HTMLTemplateElement>(
      root,
      "[data-sequence-remove-button]",
    );
    row.append(template.content.cloneNode(true));
  }

  function ensureAddButton(root: HTMLElement): HTMLButtonElement {
    const existing = root.querySelector<HTMLButtonElement>("[data-sequence-add]");
    if (existing) {
      return existing;
    }
    const template = queryRequiredElement<HTMLTemplateElement>(
      root,
      "[data-sequence-add-button]",
    );
    root.append(template.content.cloneNode(true));
    return queryRequiredElement<HTMLButtonElement>(root, "[data-sequence-add]");
  }

  function syncAddButton(root: HTMLElement): void {
    const addButton = ensureAddButton(root);
    const maximum = parseRequiredInteger(
      root.dataset.sequenceMaximum,
      "data-sequence-maximum",
    );
    addButton.hidden = activeRows(root).length >= maximum;
  }

  function disableRemovedControl(
    control:
      | HTMLButtonElement
      | HTMLInputElement
      | HTMLSelectElement
      | HTMLTextAreaElement,
  ): void {
    if (!control.matches("[data-sequence-delete]")) {
      control.disabled = true;
    }
  }

  function removeRow(row: HTMLElement): void {
    const root = row.closest<HTMLElement>("[data-sequence-widget]");
    if (!root) {
      return;
    }
    const deleteInput = queryRequiredElement<HTMLInputElement>(
      row,
      "[data-sequence-delete]",
    );
    deleteInput.value = "1";
    row.hidden = true;
    row
      .querySelectorAll<
        HTMLButtonElement | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
      >("input, select, textarea, button")
      .forEach(disableRemovedControl);
    syncAddButton(root);
  }

  function replacePrefixAttributes(
    fragment: DocumentFragment,
    index: number,
  ): void {
    for (const element of fragment.querySelectorAll<HTMLElement>(
      "[name], [id], label[for]",
    )) {
      for (const attribute of ["name", "id", "for"] as const) {
        const value = element.getAttribute(attribute);
        if (value) {
          element.setAttribute(attribute, value.replaceAll(prefix, String(index)));
        }
      }
    }
  }

  function addRow(root: HTMLElement): void {
    const maximum = parseRequiredInteger(
      root.dataset.sequenceMaximum,
      "data-sequence-maximum",
    );
    const absoluteMaximum = parseRequiredInteger(
      root.dataset.sequenceAbsoluteMaximum,
      "data-sequence-absolute-maximum",
    );
    const totalInput = queryRequiredElement<HTMLInputElement>(
      root,
      "[data-sequence-total]",
    );
    const index = parseRequiredInteger(totalInput.value, "data-sequence-total");
    if (activeRows(root).length >= maximum || index >= absoluteMaximum) {
      return;
    }

    const template = queryRequiredElement<HTMLTemplateElement>(
      root,
      "[data-sequence-empty-row]",
    );
    const fragment = template.content.cloneNode(true);
    if (!(fragment instanceof DocumentFragment)) {
      throw new Error("Expected empty-row template to clone as a document fragment");
    }
    replacePrefixAttributes(fragment, index);
    const row = queryRequiredElement<HTMLElement>(fragment, "[data-sequence-row]");
    row.dataset.sequenceIndex = String(index);
    ensureRemoveButtonInRoot(row, root);
    queryRequiredElement(root, "[data-sequence-rows]").append(fragment);
    totalInput.value = String(index + 1);
    syncAddButton(root);
  }

  function enhanceWidget(root: HTMLElement): void {
    activeRows(root).forEach(ensureRemoveButton);
    syncAddButton(root);
    root.addEventListener("click", (event: MouseEvent): void => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const addButton = event.target.closest("[data-sequence-add]");
      if (addButton && root.contains(addButton)) {
        addRow(root);
        return;
      }
      const removeButton = event.target.closest("[data-sequence-remove]");
      if (!removeButton || !root.contains(removeButton)) {
        return;
      }
      const row = removeButton.closest<HTMLElement>("[data-sequence-row]");
      if (!row) {
        return;
      }
      removeRow(row);
    });
  }

  function start(): void {
    document
      .querySelectorAll<HTMLElement>("[data-sequence-widget]")
      .forEach(enhanceWidget);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
    return;
  }
  start();
})();

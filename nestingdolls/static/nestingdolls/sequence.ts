((): void => {
  const prefix = "__prefix__";
  const sequenceWidgetSelector = '[data-widget="sequence"]';
  const enhancedWidgets = new WeakSet<HTMLElement>();
  const prefixAttributes = [
    "name",
    "id",
    "for",
    "aria-describedby",
    "aria-labelledby",
    "aria-controls",
    "list",
    "form",
    "data-sequence-field",
  ] as const;
  const prefixAttributeSelector = prefixAttributes
    .map((attribute) => `[${attribute}]`)
    .join(", ");
  const focusableControlSelector = [
    'input:not([type="hidden"]):not([disabled]):not([hidden])',
    "select:not([disabled]):not([hidden])",
    "textarea:not([disabled]):not([hidden])",
    "button:not([disabled]):not([hidden])",
    '[tabindex]:not([tabindex="-1"]):not([hidden])',
  ].join(", ");

  function requiredElement<E extends Element>(
    element: E | null | undefined,
    selector: string,
  ): E {
    if (!element) {
      throw new Error(`Missing required element: ${selector}`);
    }
    return element;
  }

  function ownedElements<E extends Element>(
    root: HTMLElement,
    parent: ParentNode,
    selector: string,
  ): E[] {
    return Array.from(parent.querySelectorAll<E>(selector)).filter(
      (element) => element.closest(sequenceWidgetSelector) === root,
    );
  }

  function ownedElement<E extends Element>(
    root: HTMLElement,
    parent: ParentNode,
    selector: string,
  ): E {
    return requiredElement(
      ownedElements<E>(root, parent, selector)[0],
      selector,
    );
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
    return ownedElements<HTMLElement>(
      root,
      root,
      "[data-sequence-row]",
    ).filter((row) => !row.hidden);
  }

  function ensureRemoveButton(root: HTMLElement, row: HTMLElement): void {
    if (ownedElements(root, row, "[data-sequence-remove]").length > 0) {
      return;
    }
    const template = ownedElement<HTMLTemplateElement>(
      root,
      root,
      "[data-sequence-remove-button]",
    );
    const fragment = template.content.cloneNode(true) as DocumentFragment;
    const index = parseRequiredInteger(
      row.dataset.sequenceIndex,
      "data-sequence-index",
    );
    replacePrefixAttributes(fragment, index);
    row.append(fragment);
  }

  function ensureAddButton(root: HTMLElement): HTMLButtonElement {
    const existing = ownedElements<HTMLButtonElement>(
      root,
      root,
      "[data-sequence-add]",
    )[0];
    if (existing) {
      return existing;
    }
    const template = ownedElement<HTMLTemplateElement>(
      root,
      root,
      "[data-sequence-add-button]",
    );
    const fragment = template.content.cloneNode(true) as DocumentFragment;
    const button = requiredElement(
      fragment.querySelector<HTMLButtonElement>("[data-sequence-add]"),
      "[data-sequence-add]",
    );
    root.append(fragment);
    return button;
  }

  function canAddRow(
    root: HTMLElement,
    rowCount: number,
    nextIndex: number,
  ): boolean {
    const maximum = parseRequiredInteger(
      root.dataset.sequenceMaximum,
      "data-sequence-maximum",
    );
    const absoluteMaximum = parseRequiredInteger(
      root.dataset.sequenceAbsoluteMaximum,
      "data-sequence-absolute-maximum",
    );
    return rowCount < maximum && nextIndex < absoluteMaximum;
  }

  function minimumRows(root: HTMLElement): number {
    if (root.dataset.sequenceMinimum === undefined) {
      return 0;
    }
    return parseRequiredInteger(
      root.dataset.sequenceMinimum,
      "data-sequence-minimum",
    );
  }

  function syncButtons(root: HTMLElement): void {
    const rows = activeRows(root);
    const totalInput = ownedElement<HTMLInputElement>(
      root,
      root,
      "[data-sequence-total]",
    );
    const nextIndex = parseRequiredInteger(
      totalInput.value,
      "data-sequence-total",
    );
    ensureAddButton(root).hidden = !canAddRow(root, rows.length, nextIndex);

    const removeButtonsHidden = rows.length <= minimumRows(root);
    for (const row of rows) {
      for (const button of ownedElements<HTMLButtonElement>(
        root,
        row,
        "[data-sequence-remove]",
      )) {
        button.hidden = removeButtonsHidden;
      }
    }
  }

  function focusFirstControl(parent: ParentNode): boolean {
    const control = parent.querySelector<HTMLElement>(focusableControlSelector);
    if (!control) {
      return false;
    }
    control.focus();
    return true;
  }

  function dispatchSequenceChange(
    root: HTMLElement,
    row: HTMLElement,
    action: "add" | "remove",
  ): void {
    const index = parseRequiredInteger(
      row.dataset.sequenceIndex,
      "data-sequence-index",
    );
    root.dispatchEvent(
      new CustomEvent("nestingdolls:sequence-change", {
        bubbles: true,
        detail: { action, index },
      }),
    );
  }

  function removeRow(root: HTMLElement, row: HTMLElement): void {
    const rows = activeRows(root);
    const rowPosition = rows.indexOf(row);
    if (rowPosition < 0 || rows.length <= minimumRows(root)) {
      return;
    }
    const focusRow = rows[rowPosition + 1] ?? rows[rowPosition - 1];
    const deleteInput = ownedElement<HTMLInputElement>(
      root,
      row,
      "[data-sequence-delete]",
    );
    deleteInput.value = "1";
    row.hidden = true;
    for (const control of row.querySelectorAll<
      HTMLButtonElement | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
    >("input, select, textarea, button")) {
      // Deletion flags are the only fields the server still needs from a
      // removed row, so they keep posting while the stale values stop.
      if (!control.matches("[data-sequence-delete]")) {
        control.disabled = true;
      }
    }
    syncButtons(root);
    if (!focusRow || !focusFirstControl(focusRow)) {
      ensureAddButton(root).focus();
    }
    dispatchSequenceChange(root, row, "remove");
  }

  function replacePrefixAttributes(
    fragment: DocumentFragment,
    index: number,
  ): void {
    const replacement = String(index);
    const elements =
      fragment.querySelectorAll<HTMLElement>(prefixAttributeSelector);
    for (const element of elements) {
      for (const attribute of prefixAttributes) {
        const value = element.getAttribute(attribute);
        if (value) {
          // Replace one placeholder in each space-separated value. Later
          // placeholders belong to nested rows.
          element.setAttribute(
            attribute,
            value.replace(/\S+/g, (part) =>
              part.replace(prefix, replacement),
            ),
          );
        }
      }
    }
    for (const template of fragment.querySelectorAll<HTMLTemplateElement>(
      "template",
    )) {
      replacePrefixAttributes(template.content, index);
    }
  }

  function addRow(root: HTMLElement): void {
    const totalInput = ownedElement<HTMLInputElement>(
      root,
      root,
      "[data-sequence-total]",
    );
    const index = parseRequiredInteger(totalInput.value, "data-sequence-total");
    if (!canAddRow(root, activeRows(root).length, index)) {
      return;
    }

    const template = ownedElement<HTMLTemplateElement>(
      root,
      root,
      "[data-sequence-empty-row]",
    );
    const fragment = template.content.cloneNode(true) as DocumentFragment;
    replacePrefixAttributes(fragment, index);
    const row = requiredElement(
      fragment.querySelector<HTMLElement>("[data-sequence-row]"),
      "[data-sequence-row]",
    );
    row.dataset.sequenceIndex = String(index);
    ensureRemoveButton(root, row);
    ownedElement(root, root, "[data-sequence-rows]").append(fragment);
    totalInput.value = String(index + 1);
    row
      .querySelectorAll<HTMLElement>(sequenceWidgetSelector)
      .forEach(enhanceWidget);
    syncButtons(root);
    focusFirstControl(row);
    dispatchSequenceChange(root, row, "add");
  }

  function enhanceWidget(root: HTMLElement): void {
    if (enhancedWidgets.has(root)) {
      return;
    }
    for (const row of activeRows(root)) {
      ensureRemoveButton(root, row);
    }
    syncButtons(root);
    root.addEventListener("click", (event: MouseEvent): void => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const action = event.target.closest(
        "[data-sequence-add], [data-sequence-remove]",
      );
      if (!action || action.closest(sequenceWidgetSelector) !== root) {
        return;
      }
      if (action.matches("[data-sequence-add]")) {
        addRow(root);
        return;
      }
      const row = action.closest<HTMLElement>("[data-sequence-row]");
      if (!row) {
        return;
      }
      removeRow(root, row);
    });
    enhancedWidgets.add(root);
  }

  function start(): void {
    document
      .querySelectorAll<HTMLElement>(sequenceWidgetSelector)
      .forEach(enhanceWidget);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
    return;
  }
  start();
})();

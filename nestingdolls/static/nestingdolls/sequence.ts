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

  function ownedElements<E extends Element>(
    root: HTMLElement,
    parent: ParentNode,
    selector: string,
  ): E[] {
    return Array.from(parent.querySelectorAll<E>(selector)).filter(
      (element) => element.closest(sequenceWidgetSelector) === root,
    );
  }

  function queryRequiredOwnedElement<E extends Element>(
    root: HTMLElement,
    parent: ParentNode,
    selector: string,
  ): E {
    const element = ownedElements<E>(root, parent, selector)[0];
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
    return ownedElements<HTMLElement>(
      root,
      root,
      "[data-sequence-row]",
    ).filter((row) => !row.hidden);
  }

  function ensureRemoveButton(row: HTMLElement): void {
    const root = row.closest<HTMLElement>(sequenceWidgetSelector);
    if (!root) {
      return;
    }
    ensureRemoveButtonInRoot(row, root);
  }

  function ensureRemoveButtonInRoot(
    row: HTMLElement,
    root: HTMLElement,
  ): void {
    if (ownedElements(root, row, "[data-sequence-remove]").length > 0) {
      return;
    }
    const template = queryRequiredOwnedElement<HTMLTemplateElement>(
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
    const template = queryRequiredOwnedElement<HTMLTemplateElement>(
      root,
      root,
      "[data-sequence-add-button]",
    );
    root.append(template.content.cloneNode(true));
    return queryRequiredOwnedElement<HTMLButtonElement>(
      root,
      root,
      "[data-sequence-add]",
    );
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
    const root = row.closest<HTMLElement>(sequenceWidgetSelector);
    if (!root) {
      return;
    }
    const deleteInput = queryRequiredOwnedElement<HTMLInputElement>(
      root,
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

  function replacePrefix(value: string, index: number): string {
    const replacement = String(index);
    // Replace one placeholder in each space-separated value. Later placeholders
    // belong to nested rows.
    return value.replace(/\S+/g, (part) => part.replace(prefix, replacement));
  }

  function replacePrefixAttributes(
    fragment: DocumentFragment,
    index: number,
  ): void {
    const elements =
      fragment.querySelectorAll<HTMLElement>(prefixAttributeSelector);
    for (const element of elements) {
      for (const attribute of prefixAttributes) {
        const value = element.getAttribute(attribute);
        if (value) {
          element.setAttribute(attribute, replacePrefix(value, index));
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
    const maximum = parseRequiredInteger(
      root.dataset.sequenceMaximum,
      "data-sequence-maximum",
    );
    const absoluteMaximum = parseRequiredInteger(
      root.dataset.sequenceAbsoluteMaximum,
      "data-sequence-absolute-maximum",
    );
    const totalInput = queryRequiredOwnedElement<HTMLInputElement>(
      root,
      root,
      "[data-sequence-total]",
    );
    const index = parseRequiredInteger(totalInput.value, "data-sequence-total");
    if (activeRows(root).length >= maximum || index >= absoluteMaximum) {
      return;
    }

    const template = queryRequiredOwnedElement<HTMLTemplateElement>(
      root,
      root,
      "[data-sequence-empty-row]",
    );
    const fragment = template.content.cloneNode(true) as DocumentFragment;
    replacePrefixAttributes(fragment, index);
    const row = queryRequiredElement<HTMLElement>(fragment, "[data-sequence-row]");
    row.dataset.sequenceIndex = String(index);
    ensureRemoveButtonInRoot(row, root);
    queryRequiredOwnedElement(
      root,
      root,
      "[data-sequence-rows]",
    ).append(fragment);
    totalInput.value = String(index + 1);
    syncAddButton(root);
    row
      .querySelectorAll<HTMLElement>(sequenceWidgetSelector)
      .forEach(enhanceWidget);
  }

  function enhanceWidget(root: HTMLElement): void {
    if (enhancedWidgets.has(root)) {
      return;
    }
    activeRows(root).forEach(ensureRemoveButton);
    syncAddButton(root);
    root.addEventListener("click", (event: MouseEvent): void => {
      if (
        !(event.target instanceof Element) ||
        event.target.closest(sequenceWidgetSelector) !== root
      ) {
        return;
      }
      const addButton = event.target.closest("[data-sequence-add]");
      if (addButton) {
        addRow(root);
        return;
      }
      const removeButton = event.target.closest("[data-sequence-remove]");
      if (!removeButton) {
        return;
      }
      const row = removeButton.closest<HTMLElement>("[data-sequence-row]");
      if (!row) {
        return;
      }
      removeRow(row);
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

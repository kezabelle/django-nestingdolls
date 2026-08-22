((): void => {
  // A page can load this file more than once. Each form adds it through
  // form.media, and the browser runs each script tag. Each file load has a
  // separate scope. Without this document marker, each load adds a click
  // handler and one click adds two rows. Set the marker before waiting for
  // DOMContentLoaded because another load can run before that event.
  if (document.documentElement.dataset.nestingdollsSequence !== undefined) {
    return;
  }
  document.documentElement.dataset.nestingdollsSequence = "";

  // The server puts this value in every row-specific name, ID, and reference.
  // It builds the row with __prefix__ instead of a row number. Replace that
  // value only. Do not rebuild Django's field-index naming rule here.
  const prefix = "__prefix__";
  const sequenceWidgetSelector = '[data-widget="sequence"]';
  const enhancedWidgets = new WeakSet<HTMLElement>();

  // Hierarchical attributes embed the full prefix path in one token, so the
  // first-placeholder-per-token replacement is safe at every nesting level.
  // aria-label carries a bare placeholder that belongs to its own level only,
  // so replace it at the level being cloned, never inside nested template
  // content, or an outer add would consume an inner button's placeholder.
  const hierarchicalPrefixAttributes = [
    "name",
    "id",
    "for",
    "aria-describedby",
    "aria-labelledby",
    "aria-controls",
    "data-sequence-field",
    "data-mapping-field",
  ] as const;
  const localPrefixAttributes = ["aria-label"] as const;
  const prefixAttributes = [
    ...hierarchicalPrefixAttributes,
    ...localPrefixAttributes,
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
    // A nested sequence has the same controls. Keep only controls that belong
    // to this root so an outer sequence cannot manage an inner sequence.
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

  function cloneTemplate(root: HTMLElement, selector: string): DocumentFragment {
    const template = ownedElement<HTMLTemplateElement>(root, root, selector);
    // cloneNode is typed as returning Node. For a template's content, the DOM
    // specification returns the fragment itself, so this cast is exact.
    return template.content.cloneNode(true) as DocumentFragment;
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
    const fragment = cloneTemplate(root, "[data-sequence-remove-button]");
    const index = parseRequiredInteger(
      row.dataset.sequenceIndex,
      "data-sequence-index",
    );
    replacePrefixAttributes(fragment, index);
    // A table row can contain cells, not a button. The template has an action
    // slot for table layouts. Use it when present; other layouts use the row.
    const slot = ownedElements<HTMLElement>(
      root,
      row,
      "[data-sequence-actions]",
    )[0];
    (slot ?? row).append(fragment);
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
    const fragment = cloneTemplate(root, "[data-sequence-add-button]");
    const button = requiredElement(
      fragment.querySelector<HTMLButtonElement>("[data-sequence-add]"),
      "[data-sequence-add]",
    );
    root.append(fragment);
    return button;
  }

  // These values improve the browser interface only. The server checks all
  // limits in SequenceField.Limits and is the source of truth. Client checks
  // cannot make a submitted value safe.
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
    // Keep an unavailable button visible and disabled. Hiding it removes it
    // from the accessibility tree, so a screen reader cannot tell why it is
    // not available. See https://www.w3.org/WAI/ARIA/apg/practices/
    // keyboard-interface/#disabling-a-button
    setAvailability(
      ensureAddButton(root),
      canAddRow(root, rows.length, nextIndex),
    );

    const removeAvailable = rows.length > minimumRows(root);
    for (const row of rows) {
      for (const button of ownedElements<HTMLButtonElement>(
        root,
        row,
        "[data-sequence-remove]",
      )) {
        setAvailability(button, removeAvailable);
      }
    }
  }

  function setAvailability(button: HTMLButtonElement, available: boolean): void {
    button.disabled = !available;
    button.setAttribute("aria-disabled", available ? "false" : "true");
  }

  function focusFirstControl(parent: ParentNode): boolean {
    const control = parent.querySelector<HTMLElement>(focusableControlSelector);
    if (!control) {
      return false;
    }
    control.focus();
    return true;
  }

  interface SequenceAddDetail {
    index: number;
  }

  interface SequenceRemoveDetail {
    index: number;
    row: HTMLElement;
  }

  interface SequenceChangeDetail {
    action: "add" | "remove";
    index: number;
    row: HTMLElement;
  }

  // The host page chooses how to tell a user about a change. It may use a
  // toast, a live region, or another method. Send bubbling events instead of
  // adding one message system here. A listener can cancel an event when it
  // must stop the requested add or remove action.
  // Returns false if a listener cancels the event.
  function dispatch<Detail>(
    root: HTMLElement,
    type: string,
    detail: Detail,
    cancelable = false,
  ): boolean {
    return root.dispatchEvent(
      new CustomEvent(type, { bubbles: true, cancelable, detail }),
    );
  }

  function removeRow(root: HTMLElement, row: HTMLElement): void {
    const rows = activeRows(root);
    const rowPosition = rows.indexOf(row);
    if (rowPosition < 0 || rows.length <= minimumRows(root)) {
      return;
    }
    const index = parseRequiredInteger(
      row.dataset.sequenceIndex,
      "data-sequence-index",
    );
    if (
      !dispatch<SequenceRemoveDetail>(
        root,
        "nestingdolls:sequence-remove",
        { index, row },
        true,
      )
    ) {
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
    // A style rule can override the browser's default [hidden] display rule.
    // Set the inline display too. A removed row must not stay visible with
    // disabled controls. See https://html.spec.whatwg.org/multipage/
    //rendering.html#hidden-elements.
    row.style.display = "none";
    for (const control of row.querySelectorAll<
      HTMLButtonElement | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
    >("input, select, textarea, button")) {
      // The delete flag tells the server to remove this row. Keep it enabled.
      // Disable every other control so stale row values are not submitted.
      if (!control.matches("[data-sequence-delete]")) {
        control.disabled = true;
      }
    }
    syncButtons(root);
    if (!focusRow || !focusFirstControl(focusRow)) {
      ensureAddButton(root).focus();
    }
    dispatch<SequenceChangeDetail>(root, "nestingdolls:sequence-change", {
      action: "remove",
      index,
      row,
    });
  }

  function replacePrefixAttributes(
    fragment: DocumentFragment,
    index: number,
    nested = false,
  ): void {
    const replacement = String(index);
    const attributes = nested ? hierarchicalPrefixAttributes : prefixAttributes;
    const elements =
      fragment.querySelectorAll<HTMLElement>(prefixAttributeSelector);
    for (const element of elements) {
      for (const attribute of attributes) {
        const value = element.getAttribute(attribute);
        if (value) {
          // Attribute values can contain several tokens. Change only the first
          // placeholder in each token. Later placeholders identify nested rows
          // and must remain for their own sequence controller.
          element.setAttribute(
            attribute,
            value.replace(/\S+/g, (part) =>
              part.replace(prefix, replacement),
            ),
          );
        }
      }
    }
    // Nested row templates keep their own prefix. Walk template content too,
    // but replace only this sequence level in each token.
    for (const template of fragment.querySelectorAll<HTMLTemplateElement>(
      "template",
    )) {
      replacePrefixAttributes(template.content, index, true);
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
    if (
      !dispatch<SequenceAddDetail>(
        root,
        "nestingdolls:sequence-add",
        { index },
        true,
      )
    ) {
      return;
    }

    const fragment = cloneTemplate(root, "[data-sequence-empty-row]");
    replacePrefixAttributes(fragment, index);
    const row = requiredElement(
      fragment.querySelector<HTMLElement>("[data-sequence-row]"),
      "[data-sequence-row]",
    );
    row.dataset.sequenceIndex = String(index);
    ownedElement(root, root, "[data-sequence-rows]").append(fragment);
    // Attach the row before creating its remove button. ownedElements() uses
    // closest() to enforce widget ownership, and closest() returns null for a
    // detached row. Before attachment, the duplicate check cannot work.
    ensureRemoveButton(root, row);
    totalInput.value = String(index + 1);
    row
      .querySelectorAll<HTMLElement>(sequenceWidgetSelector)
      .forEach(enhanceWidget);
    syncButtons(root);
    focusFirstControl(row);
    dispatch<SequenceChangeDetail>(root, "nestingdolls:sequence-change", {
      action: "add",
      index,
      row,
    });
  }

  function enhanceWidget(root: HTMLElement): void {
    // SequenceWidget.get_context disables every control when the field is
    // disabled or the submission overflowed. The server ignores this widget's
    // input, so enhancement must not re-enable its buttons.
    if (root.dataset.sequenceDisabled !== undefined) {
      return;
    }
    if (enhancedWidgets.has(root)) {
      return;
    }
    for (const row of activeRows(root)) {
      ensureRemoveButton(root, row);
    }
    syncButtons(root);
    // One handler covers controls in rows added later. Check the nearest
    // sequence root so a nested sequence keeps control of its own buttons.
    root.addEventListener("click", (event) => {
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
    dispatch(root, "nestingdolls:sequence-ready", null);
  }
  function requestEnhancement(): void {
    document.dispatchEvent(new Event("nestingdolls:sequence-enhance"));
  }

  function enhanceWidgets(parent: ParentNode): void {
    if (parent instanceof HTMLElement && parent.matches(sequenceWidgetSelector)) {
      enhanceWidget(parent);
    }
    parent
      .querySelectorAll<HTMLElement>(sequenceWidgetSelector)
      .forEach(enhanceWidget);
  }

  function start(): void {
    enhanceWidgets(document);
  }

  // Framework integrations request enhancement through the public event. This
  // gives hosts and integrations one path after markup replacement.
  document.addEventListener("nestingdolls:sequence-enhance", start);
  // htmx swaps form markup without a page load.
  // https://htmx.org/events/#htmx:load
  document.addEventListener("htmx:load", requestEnhancement);
  // Unpoly emits this event after it inserts or updates a fragment.
  // https://unpoly.com/up:fragment:inserted
  document.addEventListener("up:fragment:inserted", requestEnhancement);
  // Swup emits this document event after it replaces the content containers.
  // https://swup.js.org/hooks/#triggering-dom-events
  document.addEventListener("swup:content:replace", requestEnhancement);
  // µJS emits this event after it replaces page content.
  // https://mujs.org/documentation
  document.addEventListener("mu:after-render", requestEnhancement);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
    return;
  }
  start();
})();

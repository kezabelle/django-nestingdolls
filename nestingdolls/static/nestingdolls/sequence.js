"use strict";
(() => {
    const prefix = "__prefix__";
    const sequenceWidgetSelector = '[data-widget="sequence"]';
    const enhancedWidgets = new WeakSet();
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
    ];
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
    function requiredElement(element, selector) {
        if (!element) {
            throw new Error(`Missing required element: ${selector}`);
        }
        return element;
    }
    function ownedElements(root, parent, selector) {
        return Array.from(parent.querySelectorAll(selector)).filter((element) => element.closest(sequenceWidgetSelector) === root);
    }
    function parseRequiredInteger(value, description) {
        if (!value) {
            throw new Error(`Missing required integer value for ${description}`);
        }
        const parsed = Number.parseInt(value, 10);
        if (!Number.isSafeInteger(parsed)) {
            throw new Error(`Invalid integer value for ${description}: ${value}`);
        }
        return parsed;
    }
    function activeRows(root) {
        return ownedElements(root, root, "[data-sequence-row]").filter((row) => !row.hidden);
    }
    function ensureRemoveButton(root, row) {
        if (ownedElements(root, row, "[data-sequence-remove]").length > 0) {
            return;
        }
        const template = requiredElement(ownedElements(root, root, "[data-sequence-remove-button]")[0], "[data-sequence-remove-button]");
        const fragment = template.content.cloneNode(true);
        const index = parseRequiredInteger(row.dataset.sequenceIndex, "data-sequence-index");
        replacePrefixAttributes(fragment, index);
        row.append(fragment);
    }
    function ensureAddButton(root) {
        const existing = ownedElements(root, root, "[data-sequence-add]")[0];
        if (existing) {
            return existing;
        }
        const template = requiredElement(ownedElements(root, root, "[data-sequence-add-button]")[0], "[data-sequence-add-button]");
        root.append(template.content.cloneNode(true));
        return requiredElement(ownedElements(root, root, "[data-sequence-add]")[0], "[data-sequence-add]");
    }
    function canAddRow(root, rowCount, nextIndex) {
        const maximum = parseRequiredInteger(root.dataset.sequenceMaximum, "data-sequence-maximum");
        const absoluteMaximum = parseRequiredInteger(root.dataset.sequenceAbsoluteMaximum, "data-sequence-absolute-maximum");
        return rowCount < maximum && nextIndex < absoluteMaximum;
    }
    function minimumRows(root) {
        if (root.dataset.sequenceMinimum === undefined) {
            return 0;
        }
        return parseRequiredInteger(root.dataset.sequenceMinimum, "data-sequence-minimum");
    }
    function syncButtons(root) {
        const rows = activeRows(root);
        const totalInput = requiredElement(ownedElements(root, root, "[data-sequence-total]")[0], "[data-sequence-total]");
        const nextIndex = parseRequiredInteger(totalInput.value, "data-sequence-total");
        ensureAddButton(root).hidden = !canAddRow(root, rows.length, nextIndex);
        const removeButtonsHidden = rows.length <= minimumRows(root);
        for (const row of rows) {
            for (const button of ownedElements(root, row, "[data-sequence-remove]")) {
                button.hidden = removeButtonsHidden;
            }
        }
    }
    function focusFirstControl(parent) {
        const control = parent.querySelector(focusableControlSelector);
        if (!control) {
            return false;
        }
        control.focus();
        return true;
    }
    function dispatchSequenceChange(root, row, action) {
        const index = parseRequiredInteger(row.dataset.sequenceIndex, "data-sequence-index");
        root.dispatchEvent(new CustomEvent("nestingdolls:sequence-change", {
            bubbles: true,
            detail: { action, index },
        }));
    }
    function disableRemovedControl(control) {
        if (!control.matches("[data-sequence-delete]")) {
            control.disabled = true;
        }
    }
    function removeRow(root, row) {
        const rows = activeRows(root);
        const rowPosition = rows.indexOf(row);
        if (rowPosition < 0 || rows.length <= minimumRows(root)) {
            return;
        }
        const focusRow = rows[rowPosition + 1] ?? rows[rowPosition - 1];
        const deleteInput = requiredElement(ownedElements(root, row, "[data-sequence-delete]")[0], "[data-sequence-delete]");
        deleteInput.value = "1";
        row.hidden = true;
        row
            .querySelectorAll("input, select, textarea, button")
            .forEach(disableRemovedControl);
        syncButtons(root);
        if (!focusRow || !focusFirstControl(focusRow)) {
            ensureAddButton(root).focus();
        }
        dispatchSequenceChange(root, row, "remove");
    }
    function replacePrefixAttributes(fragment, index) {
        const replacement = String(index);
        const elements = fragment.querySelectorAll(prefixAttributeSelector);
        for (const element of elements) {
            for (const attribute of prefixAttributes) {
                const value = element.getAttribute(attribute);
                if (value) {
                    // Replace one placeholder in each space-separated value. Later
                    // placeholders belong to nested rows.
                    element.setAttribute(attribute, value.replace(/\S+/g, (part) => part.replace(prefix, replacement)));
                }
            }
        }
        for (const template of fragment.querySelectorAll("template")) {
            replacePrefixAttributes(template.content, index);
        }
    }
    function addRow(root) {
        const totalInput = requiredElement(ownedElements(root, root, "[data-sequence-total]")[0], "[data-sequence-total]");
        const index = parseRequiredInteger(totalInput.value, "data-sequence-total");
        if (!canAddRow(root, activeRows(root).length, index)) {
            return;
        }
        const template = requiredElement(ownedElements(root, root, "[data-sequence-empty-row]")[0], "[data-sequence-empty-row]");
        const fragment = template.content.cloneNode(true);
        replacePrefixAttributes(fragment, index);
        const row = requiredElement(fragment.querySelector("[data-sequence-row]"), "[data-sequence-row]");
        row.dataset.sequenceIndex = String(index);
        ensureRemoveButton(root, row);
        requiredElement(ownedElements(root, root, "[data-sequence-rows]")[0], "[data-sequence-rows]").append(fragment);
        totalInput.value = String(index + 1);
        row
            .querySelectorAll(sequenceWidgetSelector)
            .forEach(enhanceWidget);
        syncButtons(root);
        focusFirstControl(row);
        dispatchSequenceChange(root, row, "add");
    }
    function enhanceWidget(root) {
        if (enhancedWidgets.has(root)) {
            return;
        }
        for (const row of activeRows(root)) {
            ensureRemoveButton(root, row);
        }
        syncButtons(root);
        root.addEventListener("click", (event) => {
            if (!(event.target instanceof Element)) {
                return;
            }
            const action = event.target.closest("[data-sequence-add], [data-sequence-remove]");
            if (!action || action.closest(sequenceWidgetSelector) !== root) {
                return;
            }
            if (action.matches("[data-sequence-add]")) {
                addRow(root);
                return;
            }
            const row = action.closest("[data-sequence-row]");
            if (!row) {
                return;
            }
            removeRow(root, row);
        });
        enhancedWidgets.add(root);
    }
    function start() {
        document
            .querySelectorAll(sequenceWidgetSelector)
            .forEach(enhanceWidget);
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
        return;
    }
    start();
})();

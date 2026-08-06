"use strict";
(() => {
    const prefix = "__prefix__";
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
    function queryRequiredElement(parent, selector) {
        const element = parent.querySelector(selector);
        if (!element) {
            throw new Error(`Missing required element: ${selector}`);
        }
        return element;
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
        return Array.from(root.querySelectorAll("[data-sequence-row]")).filter((row) => !row.hidden);
    }
    function ensureRemoveButton(row) {
        const root = row.closest('[data-widget="sequence"]');
        if (!root) {
            return;
        }
        ensureRemoveButtonInRoot(row, root);
    }
    function ensureRemoveButtonInRoot(row, root) {
        if (row.querySelector("[data-sequence-remove]")) {
            return;
        }
        const template = queryRequiredElement(root, "[data-sequence-remove-button]");
        const fragment = template.content.cloneNode(true);
        const index = parseRequiredInteger(row.dataset.sequenceIndex, "data-sequence-index");
        replacePrefixAttributes(fragment, index);
        row.append(fragment);
    }
    function ensureAddButton(root) {
        const existing = root.querySelector("[data-sequence-add]");
        if (existing) {
            return existing;
        }
        const template = queryRequiredElement(root, "[data-sequence-add-button]");
        root.append(template.content.cloneNode(true));
        return queryRequiredElement(root, "[data-sequence-add]");
    }
    function syncAddButton(root) {
        const addButton = ensureAddButton(root);
        const maximum = parseRequiredInteger(root.dataset.sequenceMaximum, "data-sequence-maximum");
        addButton.hidden = activeRows(root).length >= maximum;
    }
    function disableRemovedControl(control) {
        if (!control.matches("[data-sequence-delete]")) {
            control.disabled = true;
        }
    }
    function removeRow(row) {
        const root = row.closest('[data-widget="sequence"]');
        if (!root) {
            return;
        }
        const deleteInput = queryRequiredElement(row, "[data-sequence-delete]");
        deleteInput.value = "1";
        row.hidden = true;
        row
            .querySelectorAll("input, select, textarea, button")
            .forEach(disableRemovedControl);
        syncAddButton(root);
    }
    function replacePrefix(value, index) {
        const replacement = String(index);
        // Replace one placeholder in each space-separated value. Later placeholders
        // belong to nested rows.
        return value.replace(/\S+/g, (part) => part.replace(prefix, replacement));
    }
    function replacePrefixAttributes(fragment, index) {
        const elements = fragment.querySelectorAll(prefixAttributeSelector);
        for (const element of elements) {
            for (const attribute of prefixAttributes) {
                const value = element.getAttribute(attribute);
                if (value) {
                    element.setAttribute(attribute, replacePrefix(value, index));
                }
            }
        }
        for (const template of fragment.querySelectorAll("template")) {
            replacePrefixAttributes(template.content, index);
        }
    }
    function addRow(root) {
        const maximum = parseRequiredInteger(root.dataset.sequenceMaximum, "data-sequence-maximum");
        const absoluteMaximum = parseRequiredInteger(root.dataset.sequenceAbsoluteMaximum, "data-sequence-absolute-maximum");
        const totalInput = queryRequiredElement(root, "[data-sequence-total]");
        const index = parseRequiredInteger(totalInput.value, "data-sequence-total");
        if (activeRows(root).length >= maximum || index >= absoluteMaximum) {
            return;
        }
        const template = queryRequiredElement(root, "[data-sequence-empty-row]");
        const fragment = template.content.cloneNode(true);
        replacePrefixAttributes(fragment, index);
        const row = queryRequiredElement(fragment, "[data-sequence-row]");
        row.dataset.sequenceIndex = String(index);
        ensureRemoveButtonInRoot(row, root);
        queryRequiredElement(root, "[data-sequence-rows]").append(fragment);
        totalInput.value = String(index + 1);
        syncAddButton(root);
    }
    function enhanceWidget(root) {
        activeRows(root).forEach(ensureRemoveButton);
        syncAddButton(root);
        root.addEventListener("click", (event) => {
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
            const row = removeButton.closest("[data-sequence-row]");
            if (!row) {
                return;
            }
            removeRow(row);
        });
    }
    function start() {
        document
            .querySelectorAll('[data-widget="sequence"]')
            .forEach(enhanceWidget);
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
        return;
    }
    start();
})();

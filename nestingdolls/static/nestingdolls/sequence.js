"use strict";
(() => {
    const prefix = "__prefix__";
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
        row.append(template.content.cloneNode(true));
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
    function replacePrefixAttributes(fragment, index) {
        for (const element of fragment.querySelectorAll("[name], [id], label[for]")) {
            for (const attribute of ["name", "id", "for"]) {
                const value = element.getAttribute(attribute);
                if (value) {
                    element.setAttribute(attribute, value.replaceAll(prefix, String(index)));
                }
            }
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
        if (!(fragment instanceof DocumentFragment)) {
            throw new Error("Expected empty-row template to clone as a document fragment");
        }
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

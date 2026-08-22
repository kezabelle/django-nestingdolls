import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { JSDOM } from "jsdom";

const controller = await readFile(
  new URL(
    "../nestingdolls/static/nestingdolls/sequence.js",
    import.meta.url,
  ),
  "utf8",
);

// The four shipped layouts, with the tags each of their templates emits. jsdom
// does not implement the table content model, so these fixtures cannot prove
// the markup is valid; they prove the script puts every control in the slot
// the template gave it, which is what makes the markup valid.
const DIV_LAYOUT = {
  name: "div",
  rootTag: "div",
  rowsTag: "div",
  rowTag: "div",
  bodyTag: null,
};
const P_LAYOUT = {
  name: "p",
  rootTag: "span",
  rowsTag: "span",
  rowTag: "span",
  bodyTag: null,
};
const UL_LAYOUT = {
  name: "ul",
  rootTag: "div",
  rowsTag: "ul",
  rowTag: "li",
  bodyTag: null,
};
const TABLE_LAYOUT = {
  name: "table",
  rootTag: "div",
  rowsTag: "tbody",
  rowTag: "tr",
  bodyTag: "td",
  rowsWrapper: "table",
};

function row(layout, attributes, content) {
  const open = layout.bodyTag ? `<${layout.bodyTag}>` : "";
  const close = layout.bodyTag ? `</${layout.bodyTag}>` : "";
  return `
    <${layout.rowTag} data-sequence-row ${attributes}>
      ${open}
      ${content}
      <span data-sequence-actions></span>
      ${close}
    </${layout.rowTag}>
  `;
}

function rowsContainer(layout, content) {
  const rows = `<${layout.rowsTag} data-sequence-rows>${content}</${layout.rowsTag}>`;
  return layout.rowsWrapper
    ? `<${layout.rowsWrapper} role="presentation">${rows}</${layout.rowsWrapper}>`
    : rows;
}

function build(html) {
  const dom = new JSDOM(html, { runScripts: "outside-only" });
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  return dom;
}

test("an added row substitutes its index into per-row attributes only", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="2"
        data-sequence-absolute-maximum="2"
      >
        <input type="hidden" value="0" data-sequence-total>
        <div data-sequence-rows></div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <label for="input-__prefix__">Value</label>
            <input
              name="values-__prefix__"
              id="input-__prefix__"
              aria-describedby="description-__prefix__ error-__prefix__"
              aria-labelledby="label-__prefix__"
              aria-controls="details-__prefix__"
              aria-label="Value __prefix__"
              list="choices-__prefix__"
              form="form-__prefix__"
              data-sequence-field="groups-__prefix__-values"
            >
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <template data-sequence-add-button>
          <button type="button" data-sequence-add>Add</button>
        </template>
      </div>
    `,
  );
  assert.equal(dom.window.document.querySelectorAll("[data-sequence-add]").length, 1);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  assert.equal(dom.window.document.querySelectorAll("[data-sequence-add]").length, 1);

  const addButton = dom.window.document.querySelector("[data-sequence-add]");
  assert.ok(addButton);
  addButton.click();

  const input = dom.window.document.querySelector('[name="values-0"]');
  assert.ok(input);
  assert.equal(
    input.getAttribute("aria-describedby"),
    "description-0 error-0",
  );
  assert.equal(input.getAttribute("aria-labelledby"), "label-0");
  assert.equal(input.getAttribute("aria-controls"), "details-0");
  assert.equal(input.getAttribute("aria-label"), "Value 0");
  // `list` points at a <datalist> id and `form` at a <form> id. Neither is ever
  // per-row, so neither is in the substitution allowlist.
  assert.equal(input.getAttribute("list"), "choices-__prefix__");
  assert.equal(input.getAttribute("form"), "form-__prefix__");
  assert.equal(input.getAttribute("data-sequence-field"), "groups-0-values");
  assert.equal(input.id, "input-0");
  const label = dom.window.document.querySelector("label");
  assert.ok(label);
  assert.equal(label.getAttribute("for"), "input-0");

  // The row template has no actions slot, so the injected remove button
  // lands on the row element itself.
  const removeButton = dom.window.document.querySelector("[data-sequence-remove]");
  assert.ok(removeButton);
  assert.equal(
    removeButton.parentElement,
    dom.window.document.querySelector("[data-sequence-row]"),
  );
});

test("the added row keeps the placeholder for the inner row", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows></div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <div
              data-widget="sequence"
              data-sequence-field="values-__prefix__"
              data-sequence-maximum="2"
              data-sequence-absolute-maximum="2"
            >
              <input
                type="hidden"
                name="values-__prefix__-TOTAL_FORMS"
                value="0"
                data-sequence-total
              >
              <div data-sequence-rows></div>
              <template
                data-sequence-empty-row
                data-sequence-field="values-__prefix__"
              >
                <div data-sequence-row>
                  <input
                    name="values-__prefix__-__prefix__"
                    id="input-__prefix__-__prefix__"
                    aria-describedby="description-__prefix__-__prefix__ error-__prefix__-__prefix__"
                  >
                </div>
              </template>
              <template data-sequence-remove-button>
                <button type="button" data-sequence-remove>Remove</button>
              </template>
              <button type="button" data-sequence-add>Add</button>
            </div>
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
  );

  const addButton = dom.window.document.querySelector("[data-sequence-add]");
  assert.ok(addButton);
  addButton.click();

  const innerTemplate = dom.window.document.querySelector(
    '[data-sequence-field="values-1"] [data-sequence-empty-row]',
  );
  assert.ok(innerTemplate instanceof dom.window.HTMLTemplateElement);
  const input = innerTemplate.content.querySelector("input");
  assert.ok(input);
  assert.equal(input.name, "values-1-__prefix__");
  assert.equal(input.id, "input-1-__prefix__");
  assert.equal(
    input.getAttribute("aria-describedby"),
    "description-1-__prefix__ error-1-__prefix__",
  );
});

test("mapping and nested sequence actions stay with their owning sequence", () => {
  const dom = build(
    `
      <form>
      <div
        data-widget="sequence"
        data-sequence-maximum="5"
        data-sequence-absolute-maximum="5"
      >
        <input id="outer-total" type="hidden" name="values-TOTAL_FORMS" value="1" data-sequence-total>
        <div id="outer-rows" data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <div data-widget="mapping">
              <div
                data-widget="sequence"
                data-sequence-field="values-0"
                data-sequence-maximum="5"
                data-sequence-absolute-maximum="5"
              >
              <input
                id="inner-total"
                type="hidden"
                name="values-0-TOTAL_FORMS"
                value="1"
                data-sequence-total
              >
              <div id="inner-rows" data-sequence-rows>
                <div data-sequence-row data-sequence-index="0">
                  <input name="values-0-0">
                </div>
              </div>
              <template data-sequence-empty-row>
                <div data-sequence-row>
                  <input name="values-0-__prefix__">
                </div>
              </template>
              <template data-sequence-remove-button>
                <button type="button" data-sequence-remove>Remove</button>
              </template>
                <button id="inner-add" type="button" data-sequence-add>Add</button>
              </div>
            </div>
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <div data-widget="mapping">
              <div
                data-widget="sequence"
                data-sequence-field="values-__prefix__"
                data-sequence-maximum="5"
                data-sequence-absolute-maximum="5"
              >
              <input
                type="hidden"
                name="values-__prefix__-TOTAL_FORMS"
                value="0"
                data-sequence-total
              >
              <div data-sequence-rows></div>
              <template data-sequence-empty-row>
                <div data-sequence-row>
                  <input name="values-__prefix__-__prefix__">
                </div>
              </template>
              <template data-sequence-remove-button>
                <button type="button" data-sequence-remove>Remove</button>
              </template>
                <button type="button" data-sequence-add>Add</button>
              </div>
            </div>
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button id="outer-add" type="button" data-sequence-add>Add</button>
      </div>
      </form>
    `,
  );

  const form = dom.window.document.querySelector("form");
  const outerTotal = dom.window.document.querySelector("#outer-total");
  const innerTotal = dom.window.document.querySelector("#inner-total");
  const outerRows = dom.window.document.querySelector("#outer-rows");
  const innerRows = dom.window.document.querySelector("#inner-rows");
  const innerAdd = dom.window.document.querySelector("#inner-add");
  const outerAdd = dom.window.document.querySelector("#outer-add");
  assert.ok(form instanceof dom.window.HTMLFormElement);
  assert.ok(outerTotal instanceof dom.window.HTMLInputElement);
  assert.ok(innerTotal instanceof dom.window.HTMLInputElement);
  assert.ok(outerRows);
  assert.ok(innerRows);
  assert.ok(innerAdd);
  assert.ok(outerAdd);

  innerAdd.click();

  assert.equal(innerTotal.value, "2");
  assert.equal(innerRows.children.length, 2);
  assert.equal(outerTotal.value, "1");
  assert.equal(outerRows.children.length, 1);

  outerAdd.click();

  assert.equal(outerTotal.value, "2");
  assert.equal(outerRows.children.length, 2);
  const newInner = outerRows.children[1].querySelector(
    '[data-sequence-field="values-1"]',
  );
  assert.ok(newInner);
  assert.equal(innerTotal.value, "2");
  assert.equal(innerRows.children.length, 2);

  const newInnerTotal = newInner.querySelector("[data-sequence-total]");
  const newInnerRows = newInner.querySelector("[data-sequence-rows]");
  const newInnerAdd = newInner.querySelector("[data-sequence-add]");
  assert.ok(newInnerTotal instanceof dom.window.HTMLInputElement);
  assert.ok(newInnerRows);
  assert.ok(newInnerAdd);

  newInnerAdd.click();

  assert.equal(newInnerTotal.value, "1");
  assert.equal(newInnerRows.children.length, 1);
  assert.equal(outerTotal.value, "2");
  assert.equal(outerRows.children.length, 2);

  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  newInnerAdd.click();

  assert.equal(newInnerTotal.value, "2");
  assert.equal(newInnerRows.children.length, 2);
  assert.equal(outerTotal.value, "2");
  assert.equal(outerRows.children.length, 2);
  const submission = new dom.window.FormData(form);
  assert.equal(submission.get("values-TOTAL_FORMS"), "2");
  assert.equal(submission.get("values-0-TOTAL_FORMS"), "2");
  assert.equal(submission.get("values-1-TOTAL_FORMS"), "2");
  assert.equal(submission.get("values-1-0"), "");
  assert.equal(submission.get("values-1-1"), "");
});

function assertAddAndRemoveManageLimitsFocusAndEvents(layout) {
  const dom = build(
    `
      <${layout.rootTag}
        data-widget="sequence"
        data-sequence-minimum="1"
        data-sequence-maximum="2"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total>
        ${rowsContainer(
          layout,
          row(
            layout,
            'data-sequence-index="0"',
            `
              <input type="hidden" name="values-0-DELETE" data-sequence-delete>
              <input id="value-0" name="values-0">
            `,
          ),
        )}
        <template data-sequence-empty-row>
          ${row(
            layout,
            "",
            `
              <input
                type="hidden"
                name="values-__prefix__-DELETE"
                data-sequence-delete
              >
              <input id="value-__prefix__" name="values-__prefix__">
            `,
          )}
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </${layout.rootTag}>
    `,
  );

  const { document } = dom.window;
  const root = document.querySelector('[data-widget="sequence"]');
  const addButton = document.querySelector("[data-sequence-add]");
  const totalInput = document.querySelector("[data-sequence-total]");
  const firstRow = document.querySelector('[data-sequence-index="0"]');
  const firstRemove = firstRow?.querySelector("[data-sequence-remove]");
  assert.ok(root);
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);
  assert.ok(firstRow instanceof dom.window.HTMLElement);
  assert.ok(firstRemove instanceof dom.window.HTMLButtonElement);

  // The button lands in the row's action slot, never as a bare child of the
  // row element. In the table layout that slot lives inside the <td>.
  assert.equal(
    firstRemove.parentElement?.getAttribute("data-sequence-actions"),
    "",
  );
  if (layout.bodyTag) {
    assert.equal(
      firstRemove.closest(layout.bodyTag)?.tagName.toLowerCase(),
      layout.bodyTag,
    );
  }

  // At the minimum, removing is unavailable but still discoverable: disabled
  // and announced, not removed from the accessibility tree.
  assert.equal(firstRemove.disabled, true);
  assert.equal(firstRemove.getAttribute("aria-disabled"), "true");
  assert.equal(firstRemove.hidden, false);

  const changes = [];
  document.addEventListener("nestingdolls:sequence-change", (event) => {
    assert.ok(event instanceof dom.window.CustomEvent);
    assert.equal(event.bubbles, true);
    assert.equal(event.target, root);
    assert.ok(event.detail.row instanceof dom.window.HTMLElement);
    changes.push({
      action: event.detail.action,
      index: event.detail.index,
      rowIndex: event.detail.row.dataset.sequenceIndex,
    });
  });

  addButton.click();

  const secondRow = document.querySelector('[data-sequence-index="1"]');
  const secondInput = document.querySelector("#value-1");
  const secondRemove = secondRow?.querySelector("[data-sequence-remove]");
  assert.ok(secondRow instanceof dom.window.HTMLElement);
  assert.ok(secondInput instanceof dom.window.HTMLInputElement);
  assert.ok(secondRemove instanceof dom.window.HTMLButtonElement);
  assert.equal(document.activeElement, secondInput);
  assert.equal(addButton.disabled, true);
  assert.equal(firstRemove.disabled, false);
  assert.equal(secondRemove.disabled, false);

  firstRemove.click();

  assert.equal(firstRow.hidden, true);
  // [hidden] alone loses to any framework rule of higher specificity.
  assert.equal(firstRow.style.display, "none");
  assert.equal(document.activeElement, secondInput);
  assert.equal(addButton.disabled, false);
  assert.equal(secondRemove.disabled, true);

  addButton.click();

  const thirdRow = document.querySelector('[data-sequence-index="2"]');
  const thirdInput = document.querySelector("#value-2");
  const thirdRemove = thirdRow?.querySelector("[data-sequence-remove]");
  assert.ok(thirdRow instanceof dom.window.HTMLElement);
  assert.ok(thirdInput instanceof dom.window.HTMLInputElement);
  assert.ok(thirdRemove instanceof dom.window.HTMLButtonElement);
  assert.equal(document.activeElement, thirdInput);
  assert.equal(totalInput.value, "3");

  thirdRemove.click();

  assert.equal(thirdRow.hidden, true);
  assert.equal(document.activeElement, secondInput);
  assert.equal(addButton.disabled, true);
  assert.equal(secondRemove.disabled, true);

  secondRemove.click();

  assert.equal(secondRow.hidden, false);
  assert.equal(document.activeElement, secondInput);
  assert.deepEqual(changes, [
    { action: "add", index: 1, rowIndex: "1" },
    { action: "remove", index: 0, rowIndex: "0" },
    { action: "add", index: 2, rowIndex: "2" },
    { action: "remove", index: 2, rowIndex: "2" },
  ]);
}

function assertRemovingRowMarksDeletionAndDisablesStaleControls(layout) {
  const dom = build(
    `
      <form>
      <${layout.rootTag}
        data-widget="sequence"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="4"
      >
        <input type="hidden" name="values-TOTAL_FORMS" value="2" data-sequence-total>
        ${rowsContainer(
          layout,
          row(
            layout,
            'data-sequence-index="0"',
            `
              <input type="hidden" name="values-0-DELETE" value="" data-sequence-delete>
              <input id="value-0" name="values-0" value="first">
              <select id="choice-0" name="choices-0"><option>a</option></select>
              <textarea id="note-0" name="notes-0"></textarea>
            `,
          ) +
            row(
              layout,
              'data-sequence-index="1"',
              `
              <input type="hidden" name="values-1-DELETE" value="" data-sequence-delete>
              <input id="value-1" name="values-1" value="second">
            `,
            ),
        )}
        <input
          type="hidden"
          name="values-9-DELETE"
          value="1"
          data-sequence-deleted-row
        >
        <template data-sequence-empty-row>
          ${row(
            layout,
            "",
            `
              <input
                type="hidden"
                name="values-__prefix__-DELETE"
                value=""
                data-sequence-delete
              >
              <input id="value-__prefix__" name="values-__prefix__">
            `,
          )}
        </template>
        <template data-sequence-remove-button>
          <button
            type="button"
            data-sequence-remove
            id="values___prefix___remove"
            aria-label="Remove row __prefix__"
          >Remove</button>
        </template>
        <template data-sequence-add-button>
          <button type="button" data-sequence-add id="values_add">Add</button>
        </template>
      </${layout.rootTag}>
      </form>
    `,
  );

  const { document } = dom.window;
  const form = document.querySelector("form");
  const totalInput = document.querySelector("[data-sequence-total]");
  const deletedRow = document.querySelector("[data-sequence-deleted-row]");
  const firstRow = document.querySelector('[data-sequence-index="0"]');
  const secondRow = document.querySelector('[data-sequence-index="1"]');
  const addButton = document.querySelector("[data-sequence-add]");
  assert.ok(form instanceof dom.window.HTMLFormElement);
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);
  assert.ok(deletedRow instanceof dom.window.HTMLInputElement);
  assert.ok(firstRow instanceof dom.window.HTMLElement);
  assert.ok(secondRow instanceof dom.window.HTMLElement);
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);

  // Each hoisted remove button carries the index of its own row, so ids stay
  // unique, the accessible names differ, and the markup keeps matching the
  // server-rendered row ids.
  const removeButtons = [...document.querySelectorAll("[data-sequence-remove]")];
  assert.deepEqual(
    removeButtons.map((button) => button.id),
    ["values_0_remove", "values_1_remove"],
  );
  assert.deepEqual(
    removeButtons.map((button) => button.getAttribute("aria-label")),
    ["Remove row 0", "Remove row 1"],
  );

  // A row deleted on a previous request is not a row: it must not count
  // toward the limits and must keep posting its deletion flag.
  assert.equal(addButton.disabled, false);
  assert.equal(deletedRow.value, "1");
  assert.equal(deletedRow.disabled, false);

  const firstRemove = firstRow.querySelector("[data-sequence-remove]");
  const firstDelete = firstRow.querySelector("[data-sequence-delete]");
  assert.ok(firstRemove instanceof dom.window.HTMLButtonElement);
  assert.ok(firstDelete instanceof dom.window.HTMLInputElement);

  firstRemove.click();

  // The deletion flag is the only thing the server sees, so it must be set
  // and must stay enabled; every other control in the row must stop posting.
  assert.equal(firstDelete.value, "1");
  assert.equal(firstDelete.disabled, false);
  assert.equal(firstRow.hidden, true);
  assert.equal(firstRow.style.display, "none");
  for (const id of ["value-0", "choice-0", "note-0"]) {
    const control = document.querySelector(`#${id}`);
    assert.ok(control);
    assert.equal(control.disabled, true, `${id} should be disabled`);
  }
  assert.equal(firstRemove.disabled, true);
  assert.equal(document.activeElement, document.querySelector("#value-1"));
  // Removing never renumbers: the total form count stays the high-water mark.
  assert.equal(totalInput.value, "2");
  const submission = new dom.window.FormData(form);
  assert.deepEqual([...submission.entries()], [
    ["values-TOTAL_FORMS", "2"],
    ["values-0-DELETE", "1"],
    ["values-1-DELETE", ""],
    ["values-1", "second"],
    ["values-9-DELETE", "1"],
  ]);
  const secondRemove = secondRow.querySelector("[data-sequence-remove]");
  assert.ok(secondRemove instanceof dom.window.HTMLButtonElement);

  // Without data-sequence-minimum the minimum is zero, so the last row goes
  // too, and focus lands on the add button instead of being lost to the body.
  secondRemove.click();

  assert.equal(secondRow.hidden, true);
  assert.equal(document.activeElement, addButton);
  assert.equal(addButton.disabled, false);
  assert.equal(totalInput.value, "2");
}

test("div layout add and remove manage limits focus and change events", () => {
  assertAddAndRemoveManageLimitsFocusAndEvents(DIV_LAYOUT);
});

test("p layout add and remove manage limits focus and change events", () => {
  assertAddAndRemoveManageLimitsFocusAndEvents(P_LAYOUT);
});

test("ul layout add and remove manage limits focus and change events", () => {
  assertAddAndRemoveManageLimitsFocusAndEvents(UL_LAYOUT);
});

test("table layout add and remove manage limits focus and change events", () => {
  assertAddAndRemoveManageLimitsFocusAndEvents(TABLE_LAYOUT);
});

test("div layout removing a row marks deletion and disables stale controls", () => {
  assertRemovingRowMarksDeletionAndDisablesStaleControls(DIV_LAYOUT);
});

test("p layout removing a row marks deletion and disables stale controls", () => {
  assertRemovingRowMarksDeletionAndDisablesStaleControls(P_LAYOUT);
});

test("ul layout removing a row marks deletion and disables stale controls", () => {
  assertRemovingRowMarksDeletionAndDisablesStaleControls(UL_LAYOUT);
});

test("table layout removing a row marks deletion and disables stale controls", () => {
  assertRemovingRowMarksDeletionAndDisablesStaleControls(TABLE_LAYOUT);
});

test("canceling the add event prevents the clone", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="2"
        data-sequence-absolute-maximum="2"
      >
        <input type="hidden" value="0" data-sequence-total>
        <div data-sequence-rows></div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input name="values-__prefix__">
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
  );

  const { document } = dom.window;
  const addButton = document.querySelector("[data-sequence-add]");
  const totalInput = document.querySelector("[data-sequence-total]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);

  let addDetail;
  document.addEventListener(
    "nestingdolls:sequence-add",
    (event) => {
      addDetail = {
        index: event.detail.index,
        cancelable: event.cancelable,
        rowsInDom: document.querySelectorAll("[data-sequence-row]").length,
      };
      event.preventDefault();
    },
    { once: true },
  );
  const changes = [];
  document.addEventListener("nestingdolls:sequence-change", (event) => {
    changes.push(event.detail.action);
  });

  addButton.click();

  // The listener saw the event before any clone existed, and the veto left
  // the widget untouched.
  assert.deepEqual(addDetail, { index: 0, cancelable: true, rowsInDom: 0 });
  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 0);
  assert.equal(totalInput.value, "0");
  assert.deepEqual(changes, []);

  addButton.click();

  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 1);
  assert.equal(totalInput.value, "1");
  assert.deepEqual(changes, ["add"]);
});

test("canceling the remove event keeps the row", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="2"
        data-sequence-absolute-maximum="2"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <input type="hidden" name="values-0-DELETE" value="" data-sequence-delete>
            <input id="value-0" name="values-0">
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input
              type="hidden"
              name="values-__prefix__-DELETE"
              value=""
              data-sequence-delete
            >
            <input name="values-__prefix__">
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
  );

  const { document } = dom.window;
  const firstRow = document.querySelector('[data-sequence-index="0"]');
  const removeButton = document.querySelector("[data-sequence-remove]");
  const deleteInput = document.querySelector("[data-sequence-delete]");
  const valueInput = document.querySelector("#value-0");
  assert.ok(firstRow instanceof dom.window.HTMLElement);
  assert.ok(removeButton instanceof dom.window.HTMLButtonElement);
  assert.ok(deleteInput instanceof dom.window.HTMLInputElement);
  assert.ok(valueInput instanceof dom.window.HTMLInputElement);

  let removeDetail;
  document.addEventListener(
    "nestingdolls:sequence-remove",
    (event) => {
      removeDetail = {
        index: event.detail.index,
        row: event.detail.row,
        cancelable: event.cancelable,
        rowHidden: event.detail.row.hidden,
      };
      event.preventDefault();
    },
    { once: true },
  );
  const changes = [];
  document.addEventListener("nestingdolls:sequence-change", (event) => {
    changes.push(event.detail.action);
  });

  removeButton.click();

  // The listener saw the row before any mutation, and the veto kept the
  // row visible, undeleted, and enabled.
  assert.ok(removeDetail);
  assert.equal(removeDetail.index, 0);
  assert.equal(removeDetail.row, firstRow);
  assert.equal(removeDetail.cancelable, true);
  assert.equal(removeDetail.rowHidden, false);
  assert.equal(firstRow.hidden, false);
  assert.equal(deleteInput.value, "");
  assert.equal(valueInput.disabled, false);
  assert.deepEqual(changes, []);

  removeButton.click();

  assert.equal(firstRow.hidden, true);
  assert.equal(deleteInput.value, "1");
  assert.deepEqual(changes, ["remove"]);
});

test("enhancement emits one ready event per widget", () => {
  const dom = new JSDOM(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows></div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <div
              data-widget="sequence"
              data-sequence-field="values-__prefix__"
              data-sequence-maximum="2"
              data-sequence-absolute-maximum="2"
            >
              <input
                type="hidden"
                name="values-__prefix__-TOTAL_FORMS"
                value="0"
                data-sequence-total
              >
              <div data-sequence-rows></div>
              <template data-sequence-empty-row>
                <div data-sequence-row>
                  <input name="values-__prefix__-__prefix__">
                </div>
              </template>
              <template data-sequence-remove-button>
                <button type="button" data-sequence-remove>Remove</button>
              </template>
              <button type="button" data-sequence-add>Add</button>
            </div>
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
    { runScripts: "outside-only" },
  );

  const { document } = dom.window;
  const readyTargets = [];
  document.addEventListener("nestingdolls:sequence-ready", (event) => {
    readyTargets.push(event.target);
  });

  dom.window.eval(controller);
  document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  // The inner widget is inert template content, so only the outer widget
  // is enhanced at start.
  const outerRoot = document.querySelector('[data-widget="sequence"]');
  assert.ok(outerRoot);
  assert.deepEqual(readyTargets, [outerRoot]);

  document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  assert.deepEqual(readyTargets, [outerRoot]);

  const addButton = document.querySelector("[data-sequence-add]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  addButton.click();

  const nestedRoot = document.querySelector(
    '[data-sequence-field="values-1"]',
  );
  assert.ok(nestedRoot);
  assert.deepEqual(readyTargets, [outerRoot, nestedRoot]);
});

function assertFragmentEventEnhancesSequence(dispatch) {
  const dom = build("<main></main>");
  const { document } = dom.window;
  const target = document.querySelector("main");
  assert.ok(target);
  target.innerHTML = `
    <div
      data-widget="sequence"
      data-sequence-maximum="2"
      data-sequence-absolute-maximum="2"
    >
      <input type="hidden" value="1" data-sequence-total>
      <div data-sequence-rows>
        <div data-sequence-row data-sequence-index="0">
          <input name="values-0">
        </div>
      </div>
      <template data-sequence-empty-row>
        <div data-sequence-row>
          <input name="values-__prefix__">
        </div>
      </template>
      <template data-sequence-remove-button>
        <button type="button" data-sequence-remove>Remove</button>
      </template>
      <template data-sequence-add-button>
        <button type="button" data-sequence-add>Add</button>
      </template>
    </div>
  `;

  let enhancementRequests = 0;
  document.addEventListener("nestingdolls:sequence-enhance", () => {
    enhancementRequests += 1;
  });
  dispatch(dom, target);
  assert.equal(enhancementRequests, 1);

  const root = target.querySelector('[data-widget="sequence"]');
  assert.ok(root);
  const addButton = root.querySelector("[data-sequence-add]");
  assert.ok(addButton);
  assert.equal(root.querySelectorAll("[data-sequence-remove]").length, 1);

  addButton.click();
  assert.equal(root.querySelectorAll("[data-sequence-row]").length, 2);
}

test("htmx load enhances sequence widgets in swapped content", () => {
  assertFragmentEventEnhancesSequence((dom, target) => {
    dom.window.document.dispatchEvent(
      new dom.window.CustomEvent("htmx:load", { detail: { elt: target } }),
    );
  });
});

test("Unpoly insertion enhances sequence widgets in swapped content", () => {
  assertFragmentEventEnhancesSequence((dom, target) => {
    target.dispatchEvent(
      new dom.window.Event("up:fragment:inserted", { bubbles: true }),
    );
  });
});

test("a host enhancement signal enhances swapped sequence widgets", () => {
  assertFragmentEventEnhancesSequence((dom) => {
    dom.window.document.dispatchEvent(
      new dom.window.Event("nestingdolls:sequence-enhance"),
    );
  });
});

test("mu navigation enhances sequence widgets in swapped content", () => {
  assertFragmentEventEnhancesSequence((dom) => {
    dom.window.document.dispatchEvent(new dom.window.Event("mu:after-render"));
  });
});

test("Swup navigation enhances sequence widgets in replaced content", () => {
  assertFragmentEventEnhancesSequence((dom) => {
    dom.window.document.dispatchEvent(
      new dom.window.CustomEvent("swup:content:replace"),
    );
  });
});

test("a forced click past the limit adds nothing", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="1"
        data-sequence-absolute-maximum="1"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <input name="values-0">
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input name="values-__prefix__">
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
  );

  const { document } = dom.window;
  const addButton = document.querySelector("[data-sequence-add]");
  const totalInput = document.querySelector("[data-sequence-total]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);
  assert.equal(addButton.disabled, true);

  let addEvents = 0;
  document.addEventListener("nestingdolls:sequence-add", () => {
    addEvents += 1;
  });

  // A DevTools user can re-enable the button; the script must still refuse,
  // and the limit guard must refuse before the add event fires.
  addButton.disabled = false;
  addButton.click();

  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 1);
  assert.equal(totalInput.value, "1");
  assert.equal(addEvents, 0);
});

// jsdom parses `new JSDOM()` markup with the document still in the "loading"
// state, so the controller defers start() to DOMContentLoaded and a throw
// surfaces as a window error event, exactly as it would for a real deferred
// script.
function enhancementFailure(html) {
  const dom = new JSDOM(html, { runScripts: "outside-only" });
  const errors = [];
  dom.window.addEventListener("error", (event) => {
    event.preventDefault();
    errors.push(String(event.error ?? event.message));
  });
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  assert.equal(errors.length, 1);
  return errors[0];
}

test("a malformed widget fails loudly at enhancement", () => {
  assert.match(
    enhancementFailure(`
      <div
        data-widget="sequence"
        data-sequence-maximum="banana"
        data-sequence-absolute-maximum="5"
      >
        <input type="hidden" value="0" data-sequence-total>
        <div data-sequence-rows></div>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `),
    /Invalid integer value for data-sequence-maximum: banana/,
  );

  assert.match(
    enhancementFailure(`
      <div data-widget="sequence">
        <div data-sequence-rows></div>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `),
    /Missing required element: \[data-sequence-total\]/,
  );
});

test("removal focuses the add button when the next row has no focusable control", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-minimum="1"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="4"
      >
        <input type="hidden" value="2" data-sequence-total>
        <div data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <input type="hidden" name="values-0-DELETE" value="" data-sequence-delete>
            <input id="value-0" name="values-0">
            <span data-sequence-actions></span>
          </div>
          <div data-sequence-row data-sequence-index="1">
            <input type="hidden" name="values-1-DELETE" value="" data-sequence-delete>
            <span data-sequence-actions></span>
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input
              type="hidden"
              name="values-__prefix__-DELETE"
              value=""
              data-sequence-delete
            >
            <input name="values-__prefix__">
            <span data-sequence-actions></span>
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
  );

  const { document } = dom.window;
  const addButton = document.querySelector("[data-sequence-add]");
  const firstRow = document.querySelector('[data-sequence-index="0"]');
  const secondRow = document.querySelector('[data-sequence-index="1"]');
  const firstRemove = firstRow?.querySelector("[data-sequence-remove]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  assert.ok(firstRow instanceof dom.window.HTMLElement);
  assert.ok(secondRow instanceof dom.window.HTMLElement);
  assert.ok(firstRemove instanceof dom.window.HTMLButtonElement);
  assert.equal(firstRemove.disabled, false);

  firstRemove.click();

  // The next row survives, but at the minimum its remove button is disabled
  // and it holds no other focusable control, so focus falls back to add.
  assert.equal(firstRow.hidden, true);
  assert.equal(secondRow.hidden, false);
  assert.equal(document.activeElement, addButton);
});

test("a second copy of the script leaves the first copy in charge", () => {
  const dom = new JSDOM(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="5"
        data-sequence-absolute-maximum="5"
      >
        <input type="hidden" value="0" data-sequence-total>
        <div data-sequence-rows></div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input name="values-__prefix__">
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
    { runScripts: "outside-only" },
  );

  const { document } = dom.window;
  let ready = 0;
  let adds = 0;
  const changes = [];
  document.addEventListener("nestingdolls:sequence-ready", () => {
    ready += 1;
  });
  document.addEventListener("nestingdolls:sequence-add", () => {
    adds += 1;
  });
  document.addEventListener("nestingdolls:sequence-change", (event) => {
    changes.push(event.detail.action);
  });

  // Two forms each render their own form.media, so the page holds two
  // <script> tags with one URL, and a browser executes both.
  dom.window.eval(controller);
  dom.window.eval(controller);
  document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  assert.equal(ready, 1);

  const addButton = document.querySelector("[data-sequence-add]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  addButton.click();

  // Without the document marker each copy attaches its own click listener,
  // and one click adds two rows and fires every hook twice.
  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 1);
  assert.equal(
    document.querySelector("[data-sequence-total]").value,
    "1",
  );
  assert.equal(adds, 1);
  assert.deepEqual(changes, ["add"]);
});

test("an added multipart row serializes its data and file", () => {
  const dom = build(
    `
      <form>
        <div
          data-widget="sequence"
          data-sequence-maximum="2"
          data-sequence-absolute-maximum="2"
        >
          <input type="hidden" name="rows-TOTAL_FORMS" value="0" data-sequence-total>
          <div data-sequence-rows></div>
          <template data-sequence-empty-row>
            <div data-sequence-row>
              <input name="rows-__prefix__-label">
              <input type="file" name="rows-__prefix__-upload">
            </div>
          </template>
          <template data-sequence-remove-button>
            <button type="button" data-sequence-remove>Remove</button>
          </template>
          <button type="button" data-sequence-add>Add</button>
        </div>
      </form>
    `,
  );

  const { document } = dom.window;
  const addButton = document.querySelector("[data-sequence-add]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  addButton.click();

  const label = document.querySelector('input[name="rows-0-label"]');
  const upload = document.querySelector('input[name="rows-0-upload"]');
  assert.ok(label instanceof dom.window.HTMLInputElement);
  assert.ok(upload instanceof dom.window.HTMLInputElement);
  label.value = "report";
  const submission = new dom.window.FormData(document.querySelector("form"));
  assert.equal(submission.get("rows-0-label"), "report");
  assert.equal(upload.type, "file");
  assert.equal(upload.name, "rows-0-upload");
});

test("a p-layout row error keeps the widget intact and enhanceable", () => {
  // as_p puts the widget inside Django's <p>. The row error markup must stay
  // phrasing content: a <ul> start tag would close the open <p> during
  // parsing and reparent the rest of the widget outside its root.
  const errorSpan =
    '<span class="errorlist" id="error-0">Enter a whole number.</span>';
  const widget = (errorMarkup) => `
    <form>
      <p>
        <span
          data-widget="sequence"
          data-sequence-maximum="2"
          data-sequence-absolute-maximum="2"
        >
          <input type="hidden" value="1" data-sequence-total>
          <span data-sequence-rows>
            <span data-sequence-row data-sequence-index="0">
              <input name="values-0" value="bad" aria-describedby="error-0">
              ${errorMarkup}
            </span>
          </span>
          <template data-sequence-empty-row>
            <span data-sequence-row>
              <input name="values-__prefix__">
            </span>
          </template>
          <template data-sequence-remove-button>
            <button type="button" data-sequence-remove>Remove</button>
          </template>
          <template data-sequence-add-button>
            <button type="button" data-sequence-add>Add</button>
          </template>
        </span>
      </p>
    </form>
  `;

  const dom = new JSDOM(widget(errorSpan), { runScripts: "outside-only" });
  const { document } = dom.window;
  const readyTargets = [];
  document.addEventListener("nestingdolls:sequence-ready", (event) => {
    readyTargets.push(event.target);
  });
  dom.window.eval(controller);
  document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  const root = document.querySelector('[data-widget="sequence"]');
  assert.ok(root);
  assert.deepEqual(readyTargets, [root]);
  // The error span and the templates all stay inside the widget root.
  assert.ok(root.querySelector(".errorlist"));
  assert.ok(root.querySelector("[data-sequence-empty-row]"));

  // The pre-fix <ul> markup shows why: the parser moves everything after the
  // error outside the widget, and enhancement fails loudly.
  const failure = enhancementFailure(
    widget('<ul class="errorlist" id="error-0"><li>Enter a whole number.</li></ul>'),
  );
  assert.match(failure, /Missing required element/u);
});

test("an outer add keeps the inner remove button's own aria-label", () => {
  const dom = build(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows></div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <div
              data-widget="sequence"
              data-sequence-field="values-__prefix__"
              data-sequence-maximum="2"
              data-sequence-absolute-maximum="2"
            >
              <input
                type="hidden"
                name="values-__prefix__-TOTAL_FORMS"
                value="0"
                data-sequence-total
              >
              <div data-sequence-rows></div>
              <template data-sequence-empty-row>
                <div data-sequence-row>
                  <input name="values-__prefix__-__prefix__">
                </div>
              </template>
              <template data-sequence-remove-button>
                <button
                  type="button"
                  data-sequence-remove
                  aria-label="Remove row __prefix__"
                >Remove</button>
              </template>
              <button type="button" data-sequence-add>Add</button>
            </div>
          </div>
        </template>
        <template data-sequence-remove-button>
          <button
            type="button"
            data-sequence-remove
            aria-label="Remove row __prefix__"
          >Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `,
  );

  const { document } = dom.window;
  const outerRoot = document.querySelector('[data-widget="sequence"]');
  assert.ok(outerRoot);
  const outerAdd = document.querySelector("[data-sequence-add]");
  assert.ok(outerAdd instanceof dom.window.HTMLButtonElement);
  outerAdd.click();

  // The outer clone replaced only its own level: the inner remove-button
  // template keeps its bare placeholder for the inner controller.
  const innerRoot = document.querySelector('[data-sequence-field="values-1"]');
  assert.ok(innerRoot);
  const innerTemplate = innerRoot.querySelector(
    "template[data-sequence-remove-button]",
  );
  assert.ok(innerTemplate instanceof dom.window.HTMLTemplateElement);
  assert.equal(
    innerTemplate.content.querySelector("button").getAttribute("aria-label"),
    "Remove row __prefix__",
  );

  const outerRemove = Array.from(
    document.querySelectorAll("[data-sequence-remove]"),
  ).find((button) => button.closest('[data-widget="sequence"]') === outerRoot);
  assert.ok(outerRemove);
  assert.equal(outerRemove.getAttribute("aria-label"), "Remove row 1");

  const innerAdd = Array.from(
    document.querySelectorAll("[data-sequence-add]"),
  ).find((button) => button.closest('[data-widget="sequence"]') === innerRoot);
  assert.ok(innerAdd instanceof dom.window.HTMLButtonElement);
  innerAdd.click();

  const innerRemove = innerRoot.querySelector("[data-sequence-remove]");
  assert.ok(innerRemove);
  assert.equal(innerRemove.getAttribute("aria-label"), "Remove row 0");
});

test("a disabled widget is not enhanced and keeps its controls disabled", () => {
  const dom = new JSDOM(
    `
      <div
        data-widget="sequence"
        data-sequence-disabled
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total disabled>
        <div data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <input name="values-0" disabled>
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input name="values-__prefix__" disabled>
          </div>
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove disabled>Remove</button>
        </template>
        <button type="button" data-sequence-add disabled>Add</button>
      </div>
    `,
    { runScripts: "outside-only" },
  );

  const { document } = dom.window;
  const readyTargets = [];
  document.addEventListener("nestingdolls:sequence-ready", (event) => {
    readyTargets.push(event.target);
  });
  dom.window.eval(controller);
  document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  // The server disabled every control and ignores this widget's input.
  // Enhancement must not run: no ready event, no injected remove button,
  // and a forced click must add nothing.
  assert.equal(readyTargets.length, 0);
  assert.equal(document.querySelectorAll("[data-sequence-remove]").length, 0);
  const addButton = document.querySelector("[data-sequence-add]");
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  assert.equal(addButton.disabled, true);
  addButton.disabled = false;
  addButton.click();
  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 1);
  const totalInput = document.querySelector("[data-sequence-total]");
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);
  assert.equal(totalInput.value, "1");
});

function assertMappingFieldPrefixIsSubstituted(layout) {
  const dom = build(
    `
      <${layout.rootTag}
        data-widget="sequence"
        data-sequence-field="values"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total>
        ${rowsContainer(layout, "")}
        <template data-sequence-empty-row>
          ${row(
            layout,
            "",
            `
              <div
                data-widget="mapping"
                data-mapping-field="values-__prefix__"
              >
                <input name="values-__prefix__-a">
              </div>
              <template data-sequence-empty-row>
                <div
                  data-widget="mapping"
                  data-mapping-field="values-__prefix__-__prefix__"
                ></div>
              </template>
            `,
          )}
        </template>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </${layout.rootTag}>
    `,
  );

  const addButton = dom.window.document.querySelector("[data-sequence-add]");
  assert.ok(addButton);
  addButton.click();

  // The value is the mapping's full prefixed name, so one placeholder per
  // token is the correct replacement at every nesting level.
  const wrapper = dom.window.document.querySelector("[data-mapping-field]");
  assert.ok(wrapper);
  assert.equal(wrapper.getAttribute("data-mapping-field"), "values-1");

  // A nested template's content is a separate fragment, so reach it through
  // the template element. The script walks into it, and the inner row keeps
  // its own placeholder for its own add.
  const nestedTemplate = dom.window.document.querySelector(
    "[data-sequence-row] [data-sequence-empty-row]",
  );
  assert.ok(nestedTemplate instanceof dom.window.HTMLTemplateElement);
  const nested = nestedTemplate.content.querySelector("[data-mapping-field]");
  assert.ok(nested);
  assert.equal(
    nested.getAttribute("data-mapping-field"),
    "values-1-__prefix__",
  );
}

test("div layout substitutes the row index into data-mapping-field", () => {
  assertMappingFieldPrefixIsSubstituted(DIV_LAYOUT);
});

test("p layout substitutes the row index into data-mapping-field", () => {
  assertMappingFieldPrefixIsSubstituted(P_LAYOUT);
});

test("ul layout substitutes the row index into data-mapping-field", () => {
  assertMappingFieldPrefixIsSubstituted(UL_LAYOUT);
});

test("table layout substitutes the row index into data-mapping-field", () => {
  assertMappingFieldPrefixIsSubstituted(TABLE_LAYOUT);
});
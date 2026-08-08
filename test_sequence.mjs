import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { JSDOM } from "jsdom";

const controller = await readFile(
  new URL(
    "./nestingdolls/static/nestingdolls/sequence.js",
    import.meta.url,
  ),
  "utf8",
);

test("the added row has the correct attribute values", () => {
  const dom = new JSDOM(
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
    { runScripts: "outside-only" },
  );
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
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
  assert.equal(input.getAttribute("list"), "choices-0");
  assert.equal(input.getAttribute("form"), "form-0");
  assert.equal(input.getAttribute("data-sequence-field"), "groups-0-values");
  assert.equal(input.id, "input-0");
  const label = dom.window.document.querySelector("label");
  assert.ok(label);
  assert.equal(label.getAttribute("for"), "input-0");
});

test("the added row keeps the placeholder for the inner row", () => {
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
    { runScripts: "outside-only" },
  );
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

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
  const dom = new JSDOM(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="5"
        data-sequence-absolute-maximum="5"
      >
        <input id="outer-total" type="hidden" value="1" data-sequence-total>
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
    `,
    { runScripts: "outside-only" },
  );
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  const outerTotal = dom.window.document.querySelector("#outer-total");
  const innerTotal = dom.window.document.querySelector("#inner-total");
  const outerRows = dom.window.document.querySelector("#outer-rows");
  const innerRows = dom.window.document.querySelector("#inner-rows");
  const innerAdd = dom.window.document.querySelector("#inner-add");
  const outerAdd = dom.window.document.querySelector("#outer-add");
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
});

test("add and remove manage limits, focus, and change events", () => {
  const dom = new JSDOM(
    `
      <div
        data-widget="sequence"
        data-sequence-minimum="1"
        data-sequence-maximum="2"
        data-sequence-absolute-maximum="3"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <input type="hidden" name="values-0-DELETE" data-sequence-delete>
            <input id="value-0" name="values-0">
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input
              type="hidden"
              name="values-__prefix__-DELETE"
              data-sequence-delete
            >
            <input id="value-__prefix__" name="values-__prefix__">
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
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  const root = dom.window.document.querySelector('[data-widget="sequence"]');
  const addButton = dom.window.document.querySelector("[data-sequence-add]");
  const totalInput = dom.window.document.querySelector("[data-sequence-total]");
  const firstRow = dom.window.document.querySelector('[data-sequence-index="0"]');
  const firstRemove = firstRow?.querySelector("[data-sequence-remove]");
  assert.ok(root);
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);
  assert.ok(firstRow instanceof dom.window.HTMLElement);
  assert.ok(firstRemove instanceof dom.window.HTMLButtonElement);
  assert.equal(firstRemove.hidden, true);
  const changes = [];
  dom.window.document.addEventListener("nestingdolls:sequence-change", (event) => {
    assert.ok(event instanceof dom.window.CustomEvent);
    assert.equal(event.bubbles, true);
    assert.equal(event.target, root);
    changes.push({ action: event.detail.action, index: event.detail.index });
  });

  addButton.click();

  const secondRow = dom.window.document.querySelector('[data-sequence-index="1"]');
  const secondInput = dom.window.document.querySelector("#value-1");
  const secondRemove = secondRow?.querySelector("[data-sequence-remove]");
  assert.ok(secondRow instanceof dom.window.HTMLElement);
  assert.ok(secondInput instanceof dom.window.HTMLInputElement);
  assert.ok(secondRemove instanceof dom.window.HTMLButtonElement);
  assert.equal(dom.window.document.activeElement, secondInput);
  assert.equal(addButton.hidden, true);
  assert.equal(firstRemove.hidden, false);
  assert.equal(secondRemove.hidden, false);

  firstRemove.click();

  assert.equal(firstRow.hidden, true);
  assert.equal(dom.window.document.activeElement, secondInput);
  assert.equal(addButton.hidden, false);
  assert.equal(secondRemove.hidden, true);

  addButton.click();

  const thirdRow = dom.window.document.querySelector('[data-sequence-index="2"]');
  const thirdInput = dom.window.document.querySelector("#value-2");
  const thirdRemove = thirdRow?.querySelector("[data-sequence-remove]");
  assert.ok(thirdRow instanceof dom.window.HTMLElement);
  assert.ok(thirdInput instanceof dom.window.HTMLInputElement);
  assert.ok(thirdRemove instanceof dom.window.HTMLButtonElement);
  assert.equal(dom.window.document.activeElement, thirdInput);
  assert.equal(totalInput.value, "3");

  thirdRemove.click();

  assert.equal(thirdRow.hidden, true);
  assert.equal(dom.window.document.activeElement, secondInput);
  assert.equal(addButton.hidden, true);
  assert.equal(secondRemove.hidden, true);

  secondRemove.click();

  assert.equal(secondRow.hidden, false);
  assert.equal(dom.window.document.activeElement, secondInput);
  assert.deepEqual(changes, [
    { action: "add", index: 1 },
    { action: "remove", index: 0 },
    { action: "add", index: 2 },
    { action: "remove", index: 2 },
  ]);
});

test("removing a row marks deletion, disables stale controls, and keeps focus", () => {
  const dom = new JSDOM(
    `
      <div
        data-widget="sequence"
        data-sequence-maximum="3"
        data-sequence-absolute-maximum="4"
      >
        <input type="hidden" value="2" data-sequence-total>
        <div data-sequence-rows>
          <div data-sequence-row data-sequence-index="0">
            <input type="hidden" name="values-0-DELETE" value="" data-sequence-delete>
            <input id="value-0" name="values-0" value="first">
            <select id="choice-0" name="choices-0"><option>a</option></select>
            <textarea id="note-0" name="notes-0"></textarea>
          </div>
          <div data-sequence-row data-sequence-index="1">
            <input type="hidden" name="values-1-DELETE" value="" data-sequence-delete>
            <input id="value-1" name="values-1" value="second">
          </div>
        </div>
        <input
          type="hidden"
          name="values-9-DELETE"
          value="1"
          data-sequence-deleted-row
        >
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input
              type="hidden"
              name="values-__prefix__-DELETE"
              value=""
              data-sequence-delete
            >
            <input id="value-__prefix__" name="values-__prefix__">
          </div>
        </template>
        <template data-sequence-remove-button>
          <button
            type="button"
            data-sequence-remove
            id="values___prefix___remove"
          >Remove</button>
        </template>
        <template data-sequence-add-button>
          <button type="button" data-sequence-add id="values_add">Add</button>
        </template>
      </div>
    `,
    { runScripts: "outside-only" },
  );
  dom.window.eval(controller);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));

  const { document } = dom.window;
  const totalInput = document.querySelector("[data-sequence-total]");
  const deletedRow = document.querySelector("[data-sequence-deleted-row]");
  const firstRow = document.querySelector('[data-sequence-index="0"]');
  const secondRow = document.querySelector('[data-sequence-index="1"]');
  const addButton = document.querySelector("[data-sequence-add]");
  assert.ok(totalInput instanceof dom.window.HTMLInputElement);
  assert.ok(deletedRow instanceof dom.window.HTMLInputElement);
  assert.ok(firstRow instanceof dom.window.HTMLElement);
  assert.ok(secondRow instanceof dom.window.HTMLElement);
  assert.ok(addButton instanceof dom.window.HTMLButtonElement);

  // Each hoisted remove button carries the index of its own row, so ids stay
  // unique and the markup keeps matching the server-rendered row ids.
  const removeIds = [...document.querySelectorAll("[data-sequence-remove]")].map(
    (button) => button.id,
  );
  assert.deepEqual(removeIds, ["values_0_remove", "values_1_remove"]);

  // A row deleted on a previous request is not a row: it must not count toward
  // the limits and must keep posting its deletion flag.
  assert.equal(addButton.hidden, false);
  assert.equal(deletedRow.value, "1");
  assert.equal(deletedRow.disabled, false);

  const firstRemove = firstRow.querySelector("[data-sequence-remove]");
  const firstDelete = firstRow.querySelector("[data-sequence-delete]");
  assert.ok(firstRemove instanceof dom.window.HTMLButtonElement);
  assert.ok(firstDelete instanceof dom.window.HTMLInputElement);

  firstRemove.click();

  // The deletion flag is the only thing the server sees, so it must be set and
  // must stay enabled; every other control in the row must stop posting.
  assert.equal(firstDelete.value, "1");
  assert.equal(firstDelete.disabled, false);
  assert.equal(firstRow.hidden, true);
  for (const id of ["value-0", "choice-0", "note-0"]) {
    const control = document.querySelector(`#${id}`);
    assert.ok(control);
    assert.equal(control.disabled, true, `${id} should be disabled`);
  }
  assert.equal(firstRemove.disabled, true);
  assert.equal(document.activeElement, document.querySelector("#value-1"));
  // Removing never renumbers: the total form count stays the high-water mark.
  assert.equal(totalInput.value, "2");

  const secondRemove = secondRow.querySelector("[data-sequence-remove]");
  assert.ok(secondRemove instanceof dom.window.HTMLButtonElement);

  // Without data-sequence-minimum the minimum is zero, so the last row goes
  // too, and focus lands on the add button instead of being lost to the body.
  secondRemove.click();

  assert.equal(secondRow.hidden, true);
  assert.equal(document.activeElement, addButton);
  assert.equal(addButton.hidden, false);
  assert.equal(totalInput.value, "2");
});

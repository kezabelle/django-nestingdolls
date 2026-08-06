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

test("each add button changes only its sequence", () => {
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
        <template data-sequence-empty-row>
          <div data-sequence-row>
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

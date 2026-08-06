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

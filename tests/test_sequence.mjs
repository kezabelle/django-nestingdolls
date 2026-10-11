import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

import { JSDOM } from "jsdom";

// Compile the committed script once, named by its absolute path, so node's
// coverage maps it to `sequence.js`. Code run by `dom.window.eval` is anonymous.
const controllerPath = fileURLToPath(
  new URL(
    "../nestingdolls/static/nestingdolls/sequence.js",
    import.meta.url,
  ),
);
const controller = new vm.Script(await readFile(controllerPath, "utf8"), {
  filename: controllerPath,
});

function runController(dom) {
  controller.runInContext(dom.getInternalVMContext());
}

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
const LAYOUTS = [DIV_LAYOUT, P_LAYOUT, UL_LAYOUT, TABLE_LAYOUT];

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

function defaultRowContent(index) {
  return `
    <input
      type="hidden"
      name="values-${index}-DELETE"
      value=""
      data-sequence-delete
    >
    <input id="value-${index}" name="values-${index}-value" value="v${index}">
  `;
}

const PLAIN_REMOVE_BUTTON = `
  <button type="button" data-sequence-remove>Remove</button>
`;

// A widget inside a form with server-rendered rows at the given indexes. The
// empty-row template is `content("__prefix__")`, as the server renders it.
// Omit `minimum` to render no `data-sequence-minimum` attribute.
function sequence(
  layout,
  {
    minimum,
    maximum = 3,
    absoluteMaximum = maximum,
    rows = [0],
    total = rows.length,
    content = defaultRowContent,
    removeButton = PLAIN_REMOVE_BUTTON,
    after = "",
  } = {},
) {
  const minimumAttribute =
    minimum === undefined ? "" : `data-sequence-minimum="${minimum}"`;
  return `
    <form>
      <${layout.rootTag}
        data-widget="sequence"
        ${minimumAttribute}
        data-sequence-maximum="${maximum}"
        data-sequence-absolute-maximum="${absoluteMaximum}"
      >
        <input
          type="hidden"
          name="values-TOTAL_FORMS"
          value="${total}"
          data-sequence-total
        >
        ${rowsContainer(
          layout,
          rows
            .map((index) =>
              row(layout, `data-sequence-index="${index}"`, content(index)),
            )
            .join(""),
        )}
        ${after}
        <template data-sequence-empty-row>
          ${row(layout, "", content("__prefix__"))}
        </template>
        <template data-sequence-remove-button>${removeButton}</template>
        <button type="button" data-sequence-add>Add</button>
      </${layout.rootTag}>
    </form>
  `;
}

function build(html) {
  const dom = new JSDOM(html, { runScripts: "outside-only" });
  runController(dom);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  return dom;
}

function button(dom, selector) {
  const element = dom.window.document.querySelector(selector);
  assert.ok(
    element instanceof dom.window.HTMLButtonElement,
    `no button matches ${selector}`,
  );
  return element;
}

function addButtonOf(dom) {
  return button(dom, "[data-sequence-add]");
}

function removeButtonOf(dom, index) {
  return button(
    dom,
    `[data-sequence-index="${index}"] [data-sequence-remove]`,
  );
}

function rowAt(dom, index) {
  const element = dom.window.document.querySelector(
    `[data-sequence-index="${index}"]`,
  );
  assert.ok(
    element instanceof dom.window.HTMLElement,
    `no row has index ${index}`,
  );
  return element;
}

function inputWithId(dom, id) {
  const element = dom.window.document.getElementById(id);
  assert.ok(element instanceof dom.window.HTMLInputElement, `no input #${id}`);
  return element;
}

function submissionOf(dom) {
  const form = dom.window.document.querySelector("form");
  assert.ok(form instanceof dom.window.HTMLFormElement);
  return [...new dom.window.FormData(form).entries()];
}

// Names the add, remove, and change events in the order they fired.
function logSequenceEvents(document) {
  const log = [];
  for (const type of ["add", "remove", "change"]) {
    document.addEventListener(`nestingdolls:sequence-${type}`, () => {
      log.push(type);
    });
  }
  return log;
}

function recordChangeEvents(document) {
  const changes = [];
  document.addEventListener("nestingdolls:sequence-change", (event) => {
    changes.push({
      action: event.detail.action,
      index: event.detail.index,
      row: event.detail.row,
      target: event.target,
      bubbles: event.bubbles,
    });
  });
  return changes;
}

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
  runController(dom);
  dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  assert.equal(errors.length, 1);
  return errors[0];
}

// --- Row markup in every layout ---------------------------------------------

for (const layout of LAYOUTS) {
  test(`${layout.name} layout puts remove controls in the action slot`, () => {
    const dom = build(sequence(layout, { minimum: 1, maximum: 2 }));

    addButtonOf(dom).click();

    // The button lands in the row's action slot, never as a bare child of the
    // row element. In the table layout that slot lives inside the <td>.
    for (const index of [0, 1]) {
      const remove = removeButtonOf(dom, index);
      assert.equal(
        remove.parentElement?.getAttribute("data-sequence-actions"),
        "",
      );
      if (layout.bodyTag) {
        assert.equal(
          remove.closest(layout.bodyTag)?.tagName.toLowerCase(),
          layout.bodyTag,
        );
      }
    }
  });
}

for (const layout of LAYOUTS) {
  test(`an added row substitutes hierarchical attributes in the ${layout.name} layout`, () => {
    const dom = build(
      sequence(layout, {
        maximum: 2,
        rows: [],
        content: () => `
          <label for="input-__prefix__">Value</label>
          <input
            name="values-__prefix__-value"
            id="input-__prefix__"
            aria-describedby="description-__prefix__ error-__prefix__"
            aria-labelledby="label-__prefix__"
            aria-controls="details-__prefix__"
            list="choices-__prefix__"
            data-sequence-field="groups-__prefix__-value-values"
          >
          <datalist id="choices-__prefix__"><option value="a"></option></datalist>
        `,
      }),
    );
    const { document } = dom.window;

    addButtonOf(dom).click();

    const input = document.querySelector('[name="values-0-value"]');
    assert.ok(input instanceof dom.window.HTMLInputElement);
    assert.equal(input.id, "input-0");
    assert.equal(
      input.getAttribute("aria-describedby"),
      "description-0 error-0",
    );
    assert.equal(input.getAttribute("aria-labelledby"), "label-0");
    assert.equal(input.getAttribute("aria-controls"), "details-0");
    assert.equal(
      input.getAttribute("data-sequence-field"),
      "groups-0-value-values",
    );
    assert.equal(document.querySelector("label")?.getAttribute("for"), "input-0");
    // A child widget can render its own <datalist> in the row, so `list` is a
    // per-row ID reference like `aria-controls`.
    assert.equal(input.getAttribute("list"), "choices-0");
    assert.equal(input.list, document.querySelector("#choices-0"));
  });

  test(`an added row leaves form references unchanged in the ${layout.name} layout`, () => {
    const dom = build(
      sequence(layout, {
        maximum: 2,
        rows: [],
        content: () => `
          <input name="values-__prefix__-value" form="form-__prefix__">
        `,
      }),
    );

    addButtonOf(dom).click();

    // `form` points at a <form> id. A row never owns a form, so `form` is not
    // in the substitution allowlist.
    assert.equal(
      dom.window.document
        .querySelector('[name="values-0-value"]')
        ?.getAttribute("form"),
      "form-__prefix__",
    );
  });
}

for (const layout of LAYOUTS) {
  test(`${layout.name} layout substitutes the row index into data-mapping-field`, () => {
    const dom = build(
      sequence(layout, {
        rows: [],
        total: 1,
        content: () => `
          <div
            data-widget="mapping"
            data-mapping-field="values-__prefix__-value"
          >
            <input name="values-__prefix__-value-a">
          </div>
          <template data-sequence-empty-row>
            <div
              data-widget="mapping"
              data-mapping-field="values-__prefix__-value-__prefix__"
            ></div>
          </template>
        `,
      }),
    );
    const { document } = dom.window;

    addButtonOf(dom).click();

    // The value is the mapping's full prefixed name, so one placeholder per
    // token is the correct replacement at every nesting level.
    const wrapper = document.querySelector("[data-mapping-field]");
    assert.ok(wrapper);
    assert.equal(wrapper.getAttribute("data-mapping-field"), "values-1-value");

    // A nested template's content is a separate fragment, so reach it through
    // the template element. The script walks into it, and the inner row keeps
    // its own placeholder for its own add.
    const nestedTemplate = document.querySelector(
      "[data-sequence-row] [data-sequence-empty-row]",
    );
    assert.ok(nestedTemplate instanceof dom.window.HTMLTemplateElement);
    assert.equal(
      nestedTemplate.content
        .querySelector("[data-mapping-field]")
        ?.getAttribute("data-mapping-field"),
      "values-1-value-__prefix__",
    );
  });
}

// An outer widget whose row holds an inner widget; the inner widget's
// remove-button template carries a bare placeholder for its own level.
function outerSequenceWithInner(layout) {
  const innerRemoveButton = `
    <button
      type="button"
      data-sequence-remove
      aria-label="Remove row __prefix__"
    >Remove</button>
  `;
  return sequence(layout, {
    maximum: 3,
    rows: [],
    total: 1,
    removeButton: innerRemoveButton,
    content: () => `
      <${layout.rootTag}
        data-widget="sequence"
        data-sequence-field="values-__prefix__-value"
        data-sequence-maximum="2"
        data-sequence-absolute-maximum="2"
      >
        <input
          type="hidden"
          name="values-__prefix__-TOTAL_FORMS"
          value="0"
          data-sequence-total
        >
        ${rowsContainer(layout, "")}
        <template data-sequence-empty-row>
          ${row(
            layout,
            "",
            `
              <input
                name="values-__prefix__-value-__prefix__-value"
                id="input-__prefix__-__prefix__"
                aria-describedby="description-__prefix__-__prefix__ error-__prefix__-__prefix__"
              >
            `,
          )}
        </template>
        <template data-sequence-remove-button>${innerRemoveButton}</template>
        <button type="button" data-sequence-add>Add</button>
      </${layout.rootTag}>
    `,
  });
}

for (const layout of LAYOUTS) {
  test(`the added row keeps the placeholder for the inner row in the ${layout.name} layout`, () => {
    const dom = build(outerSequenceWithInner(layout));
    const { document } = dom.window;

    addButtonOf(dom).click();

    const innerTemplate = document.querySelector(
      '[data-sequence-field="values-1-value"] [data-sequence-empty-row]',
    );
    assert.ok(innerTemplate instanceof dom.window.HTMLTemplateElement);
    const input = innerTemplate.content.querySelector("input");
    assert.ok(input);
    assert.equal(input.name, "values-1-value-__prefix__-value");
    assert.equal(input.id, "input-1-__prefix__");
    assert.equal(
      input.getAttribute("aria-describedby"),
      "description-1-__prefix__ error-1-__prefix__",
    );
  });

  test(`an outer add keeps the inner remove button's own aria-label in the ${layout.name} layout`, () => {
    const dom = build(outerSequenceWithInner(layout));
    const { document } = dom.window;

    addButtonOf(dom).click();

    // The outer clone replaced only its own level: the inner remove-button
    // template keeps its bare placeholder for the inner controller.
    const innerTemplate = document.querySelector(
      '[data-sequence-field="values-1-value"] template[data-sequence-remove-button]',
    );
    assert.ok(innerTemplate instanceof dom.window.HTMLTemplateElement);
    assert.equal(
      innerTemplate.content.querySelector("button")?.getAttribute("aria-label"),
      "Remove row __prefix__",
    );
  });
}

test("a row without an action slot receives its remove control", () => {
  const dom = build(
    sequence(DIV_LAYOUT, {
      rows: [],
      total: 0,
      content: () => '<input name="values-__prefix__-value">',
    }).replace("<span data-sequence-actions></span>", ""),
  );

  addButtonOf(dom).click();

  assert.equal(
    dom.window.document.querySelector("[data-sequence-remove]")?.parentElement,
    dom.window.document.querySelector("[data-sequence-row]"),
  );
});

for (const layout of LAYOUTS) {
  test(`a remove control carries the index of its own row in the ${layout.name} layout`, () => {
    const dom = build(
      sequence(layout, {
        rows: [0, 1],
        removeButton: `
          <button
            type="button"
            data-sequence-remove
            id="values___prefix___remove"
            aria-label="Remove row __prefix__"
          >Remove</button>
        `,
      }),
    );

    const removeButtons = [
      ...dom.window.document.querySelectorAll("[data-sequence-remove]"),
    ];

    // Ids stay unique and the accessible names differ, so the markup keeps
    // matching the server-rendered row ids.
    assert.deepEqual(
      removeButtons.map((remove) => remove.id),
      ["values_0_remove", "values_1_remove"],
    );
    assert.deepEqual(
      removeButtons.map((remove) => remove.getAttribute("aria-label")),
      ["Remove row 0", "Remove row 1"],
    );
  });
}

// --- Limits and button availability -----------------------------------------

test("maximum disables adding an active row", () => {
  const dom = build(sequence(DIV_LAYOUT, { maximum: 2, absoluteMaximum: 5 }));
  const addButton = addButtonOf(dom);
  assert.equal(addButton.disabled, false);

  addButton.click();

  assert.equal(addButton.disabled, true);
  assert.equal(addButton.getAttribute("aria-disabled"), "true");
});

test("absolute maximum blocks the next row index", () => {
  // Two server rows use indexes 0 and 1, so the next index 2 is not below an
  // absolute maximum of 2 even though the active-row maximum allows a third.
  const dom = build(
    sequence(DIV_LAYOUT, { maximum: 3, absoluteMaximum: 2, rows: [0, 1] }),
  );
  const addButton = addButtonOf(dom);
  assert.equal(addButton.disabled, true);

  // Removing a row lowers the active count but never reuses an index.
  removeButtonOf(dom, 0).click();

  assert.equal(addButton.disabled, true);
});

test("removing a row below the maximum enables adding again", () => {
  const dom = build(
    sequence(DIV_LAYOUT, { maximum: 2, absoluteMaximum: 5, rows: [0, 1] }),
  );
  const addButton = addButtonOf(dom);
  assert.equal(addButton.disabled, true);

  removeButtonOf(dom, 0).click();

  assert.equal(addButton.disabled, false);
  assert.equal(addButton.getAttribute("aria-disabled"), "false");
});

test("a remove control at the minimum is disabled but not hidden", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 1 }));

  // Unavailable stays discoverable: disabled and announced, not removed from
  // the accessibility tree.
  const remove = removeButtonOf(dom, 0);
  assert.equal(remove.disabled, true);
  assert.equal(remove.getAttribute("aria-disabled"), "true");
  assert.equal(remove.hidden, false);
});

test("adding above the minimum enables every remove control", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 1, maximum: 2 }));

  addButtonOf(dom).click();

  for (const index of [0, 1]) {
    const remove = removeButtonOf(dom, index);
    assert.equal(remove.disabled, false);
    assert.equal(remove.getAttribute("aria-disabled"), "false");
  }
});

test("removal down to the minimum disables the surviving remove control", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 1, rows: [0, 1] }));

  removeButtonOf(dom, 0).click();

  const survivor = removeButtonOf(dom, 1);
  assert.equal(survivor.disabled, true);
  assert.equal(survivor.getAttribute("aria-disabled"), "true");
});

test("a required sequence keeps min_length as its removal floor", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 1 }));
  const { document } = dom.window;
  const log = logSequenceEvents(document);
  const remove = removeButtonOf(dom, 0);

  // A DevTools user can re-enable the button. The floor check must refuse
  // before the remove event fires.
  remove.disabled = false;
  remove.click();

  assert.equal(rowAt(dom, 0).hidden, false);
  assert.deepEqual(log, []);
  assert.equal(document.querySelector('[name="values-0-DELETE"]')?.value, "");
});

test("a forced click past the limit adds nothing", () => {
  const dom = build(sequence(DIV_LAYOUT, { maximum: 1 }));
  const { document } = dom.window;
  const addButton = addButtonOf(dom);
  const log = logSequenceEvents(document);

  // A DevTools user can re-enable the button; the script must still refuse,
  // and the limit guard must refuse before the add event fires.
  addButton.disabled = false;
  addButton.click();

  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 1);
  assert.equal(
    document.querySelector("[data-sequence-total]")?.value,
    "1",
  );
  assert.deepEqual(log, []);
});

// --- Add and remove state machine -------------------------------------------

test("an added row receives focus", () => {
  const dom = build(sequence(DIV_LAYOUT, { maximum: 2 }));

  addButtonOf(dom).click();

  assert.equal(dom.window.document.activeElement, inputWithId(dom, "value-1"));
});

test("removal focuses the next active row", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 1, rows: [0, 1, 2] }));

  removeButtonOf(dom, 1).click();

  // The next row wins over the previous one.
  assert.equal(dom.window.document.activeElement, inputWithId(dom, "value-2"));
});

test("removal focuses the previous active row after the last row", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 1, rows: [0, 1] }));

  removeButtonOf(dom, 1).click();

  assert.equal(dom.window.document.activeElement, inputWithId(dom, "value-0"));
});

test("removal focuses the add button when the next row has no focusable control", () => {
  const dom = build(
    sequence(DIV_LAYOUT, {
      minimum: 1,
      rows: [0, 1],
      content: (index) =>
        index === 1
          ? `<input type="hidden" name="values-1-DELETE" value="" data-sequence-delete>`
          : defaultRowContent(index),
    }),
  );

  removeButtonOf(dom, 0).click();

  // The next row survives, but at the minimum its remove button is disabled
  // and it holds no other focusable control, so focus falls back to add.
  assert.equal(rowAt(dom, 1).hidden, false);
  assert.equal(dom.window.document.activeElement, addButtonOf(dom));
});

test("removal skips a disabled tabindex control", () => {
  const dom = build(
    sequence(DIV_LAYOUT, {
      minimum: 1,
      rows: [0, 1],
      content: (index) =>
        index === 1
          ? `
            <input type="hidden" name="values-1-DELETE" value="" data-sequence-delete>
            <input disabled tabindex="0">
          `
          : defaultRowContent(index),
    }),
  );

  removeButtonOf(dom, 0).click();

  // A disabled control cannot take focus, so focus falls back to add.
  assert.equal(dom.window.document.activeElement, addButtonOf(dom));
});

test("removal focuses an enabled tabindex control", () => {
  const dom = build(
    sequence(DIV_LAYOUT, {
      minimum: 1,
      rows: [0, 1],
      content: (index) =>
        index === 1
          ? `
            <input type="hidden" name="values-1-DELETE" value="" data-sequence-delete>
            <span id="custom-control" tabindex="0">Custom control</span>
          `
          : defaultRowContent(index),
    }),
  );

  removeButtonOf(dom, 0).click();

  assert.equal(
    dom.window.document.activeElement,
    dom.window.document.getElementById("custom-control"),
  );
});

test("removing the last row focuses the add button", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 0 }));

  removeButtonOf(dom, 0).click();

  assert.equal(dom.window.document.activeElement, addButtonOf(dom));
});

test("a widget without a minimum removes its last row", () => {
  // Without data-sequence-minimum the removal floor is zero.
  const dom = build(sequence(DIV_LAYOUT));

  removeButtonOf(dom, 0).click();

  assert.equal(rowAt(dom, 0).hidden, true);
});

test("a removed row is hidden with the hidden attribute and inline display", () => {
  const dom = build(sequence(DIV_LAYOUT, { rows: [0, 1] }));

  removeButtonOf(dom, 0).click();

  assert.equal(rowAt(dom, 0).hidden, true);
  // [hidden] alone loses to any framework rule of higher specificity.
  assert.equal(rowAt(dom, 0).style.display, "none");
});

test("a removed row submits only its delete flag", () => {
  const dom = build(
    sequence(DIV_LAYOUT, {
      rows: [0, 1],
      content: (index) => `
        ${defaultRowContent(index)}
        <select name="values-${index}-choice"><option>a</option></select>
        <textarea name="values-${index}-note"></textarea>
      `,
    }),
  );

  removeButtonOf(dom, 0).click();

  // Every other control in the removed row stops posting.
  assert.deepEqual(
    submissionOf(dom).filter(([name]) => name.startsWith("values-0-")),
    [["values-0-DELETE", "1"]],
  );
});

test("a removed row disables its own remove control", () => {
  const dom = build(sequence(DIV_LAYOUT, { rows: [0, 1] }));
  const remove = removeButtonOf(dom, 0);

  remove.click();

  assert.equal(remove.disabled, true);
});

test("removal keeps the total form count at the high-water mark", () => {
  const dom = build(sequence(DIV_LAYOUT, { rows: [0, 1] }));

  removeButtonOf(dom, 0).click();

  // Removing never renumbers: the total form count stays at 2.
  assert.equal(
    dom.window.document.querySelector("[data-sequence-total]")?.value,
    "2",
  );
});

test("an add dispatches a change event for the new row", () => {
  const dom = build(sequence(DIV_LAYOUT, { maximum: 2 }));
  const { document } = dom.window;
  const changes = recordChangeEvents(document);

  addButtonOf(dom).click();

  assert.equal(changes.length, 1);
  const [change] = changes;
  assert.equal(change.action, "add");
  assert.equal(change.index, 1);
  assert.equal(change.row, rowAt(dom, 1));
  assert.equal(change.target, document.querySelector('[data-widget="sequence"]'));
  assert.equal(change.bubbles, true);
});

test("a remove dispatches a change event for the removed row", () => {
  const dom = build(sequence(DIV_LAYOUT, { rows: [0, 1] }));
  const { document } = dom.window;
  const changes = recordChangeEvents(document);

  removeButtonOf(dom, 0).click();

  assert.equal(changes.length, 1);
  const [change] = changes;
  assert.equal(change.action, "remove");
  assert.equal(change.index, 0);
  assert.equal(change.row, rowAt(dom, 0));
  assert.equal(change.target, document.querySelector('[data-widget="sequence"]'));
  assert.equal(change.bubbles, true);
});

test("an optional sequence removes its last row", () => {
  // The server renders a floor of 0 for an optional field.
  const dom = build(sequence(DIV_LAYOUT, { minimum: 0 }));
  const remove = removeButtonOf(dom, 0);
  assert.equal(remove.disabled, false);

  remove.click();

  assert.equal(rowAt(dom, 0).hidden, true);
});

test("a removed row ignores a second removal", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 0, rows: [0, 1] }));
  const log = logSequenceEvents(dom.window.document);
  const remove = removeButtonOf(dom, 0);
  remove.click();

  // The removed row is no longer an active row. A forced click on its
  // re-enabled button must not remove it a second time.
  remove.disabled = false;
  remove.click();

  assert.deepEqual(log, ["remove", "change"]);
});

test("canceling the add event prevents the clone", () => {
  const dom = build(sequence(DIV_LAYOUT, { maximum: 2, rows: [] }));
  const { document } = dom.window;
  let addDetail;
  document.addEventListener("nestingdolls:sequence-add", (event) => {
    addDetail = {
      index: event.detail.index,
      cancelable: event.cancelable,
      rowsInDom: document.querySelectorAll("[data-sequence-row]").length,
    };
    event.preventDefault();
  });
  const changes = recordChangeEvents(document);

  addButtonOf(dom).click();

  // The listener saw the event before any clone existed, and the veto left
  // the widget untouched.
  assert.deepEqual(addDetail, { index: 0, cancelable: true, rowsInDom: 0 });
  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 0);
  assert.equal(
    document.querySelector("[data-sequence-total]")?.value,
    "0",
  );
  assert.deepEqual(changes, []);
});

test("canceling the remove event keeps the row", () => {
  const dom = build(sequence(DIV_LAYOUT, { maximum: 2 }));
  const { document } = dom.window;
  const firstRow = rowAt(dom, 0);
  let removeDetail;
  document.addEventListener("nestingdolls:sequence-remove", (event) => {
    removeDetail = {
      index: event.detail.index,
      row: event.detail.row,
      cancelable: event.cancelable,
      rowHidden: event.detail.row.hidden,
    };
    event.preventDefault();
  });
  const changes = recordChangeEvents(document);

  removeButtonOf(dom, 0).click();

  // The listener saw the row before any mutation, and the veto kept the
  // row visible, undeleted, and enabled.
  assert.deepEqual(removeDetail, {
    index: 0,
    row: firstRow,
    cancelable: true,
    rowHidden: false,
  });
  assert.equal(firstRow.hidden, false);
  assert.equal(document.querySelector("[data-sequence-delete]")?.value, "");
  assert.equal(inputWithId(dom, "value-0").disabled, false);
  assert.deepEqual(changes, []);
});

// --- Nested sequences -------------------------------------------------------

// An outer sequence whose only row holds a mapping that holds an inner
// sequence with one row. Both levels have a room for more rows.
function buildNestedSequences() {
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
                data-sequence-field="values-0-value"
                data-sequence-maximum="5"
                data-sequence-absolute-maximum="5"
              >
              <input
                id="inner-total"
                type="hidden"
                name="values-0-value-TOTAL_FORMS"
                value="1"
                data-sequence-total
              >
              <div id="inner-rows" data-sequence-rows>
                <div data-sequence-row data-sequence-index="0">
                  <input name="values-0-value-0-value">
                </div>
              </div>
              <template data-sequence-empty-row>
                <div data-sequence-row>
                  <input name="values-0-value-__prefix__-value">
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
                data-sequence-field="values-__prefix__-value"
                data-sequence-maximum="5"
                data-sequence-absolute-maximum="5"
              >
              <input
                type="hidden"
                name="values-__prefix__-value-TOTAL_FORMS"
                value="0"
                data-sequence-total
              >
              <div data-sequence-rows></div>
              <template data-sequence-empty-row>
                <div data-sequence-row>
                  <input name="values-__prefix__-value-__prefix__-value">
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
  const { document } = dom.window;
  return {
    dom,
    document,
    outerTotal: document.querySelector("#outer-total"),
    innerTotal: document.querySelector("#inner-total"),
    outerRows: document.querySelector("#outer-rows"),
    innerRows: document.querySelector("#inner-rows"),
    innerAdd: document.querySelector("#inner-add"),
    outerAdd: document.querySelector("#outer-add"),
  };
}

test("an inner add changes only its owning sequence", () => {
  const { innerAdd, innerTotal, innerRows, outerTotal, outerRows } =
    buildNestedSequences();

  innerAdd.click();

  assert.equal(innerTotal.value, "2");
  assert.equal(innerRows.children.length, 2);
  assert.equal(outerTotal.value, "1");
  assert.equal(outerRows.children.length, 1);
});

test("an added row enhances its nested sequence", () => {
  const { outerAdd, outerRows } = buildNestedSequences();

  outerAdd.click();

  const newInner = outerRows.children[1]?.querySelector(
    '[data-sequence-field="values-1-value"]',
  );
  assert.ok(newInner);
  const newInnerTotal = newInner.querySelector("[data-sequence-total]");
  const newInnerRows = newInner.querySelector("[data-sequence-rows]");
  newInner.querySelector("[data-sequence-add]")?.click();

  assert.equal(newInnerTotal?.value, "1");
  assert.equal(newInnerRows?.children.length, 1);
});

test("nested added rows submit under their owning prefixes", () => {
  const { dom, outerAdd, outerRows } = buildNestedSequences();
  outerAdd.click();
  const newInnerAdd = outerRows.children[1]?.querySelector(
    '[data-sequence-field="values-1-value"] [data-sequence-add]',
  );
  assert.ok(newInnerAdd instanceof dom.window.HTMLButtonElement);
  newInnerAdd.click();
  newInnerAdd.click();

  assert.deepEqual(submissionOf(dom), [
    ["values-TOTAL_FORMS", "2"],
    ["values-0-value-TOTAL_FORMS", "1"],
    ["values-0-value-0-value", ""],
    ["values-1-value-TOTAL_FORMS", "2"],
    ["values-1-value-0-value", ""],
    ["values-1-value-1-value", ""],
  ]);
});

test("removing an outer row stops its nested rows from submitting", () => {
  const dom = build(
    `
      <form>
        <div
          data-widget="sequence"
          data-sequence-field="outer"
          data-sequence-maximum="2"
          data-sequence-absolute-maximum="2"
        >
          <input type="hidden" name="outer-TOTAL_FORMS" value="1" data-sequence-total>
          <div data-sequence-rows>
            <div data-sequence-row data-sequence-index="0">
              <input type="hidden" name="outer-0-DELETE" value="" data-sequence-delete>
              <div
                data-widget="sequence"
                data-sequence-field="outer-0-value-inner"
                data-sequence-maximum="2"
                data-sequence-absolute-maximum="2"
              >
                <input
                  type="hidden"
                  name="outer-0-value-inner-TOTAL_FORMS"
                  value="1"
                  data-sequence-total
                >
                <div data-sequence-rows>
                  <div data-sequence-row data-sequence-index="0">
                    <input
                      type="hidden"
                      name="outer-0-value-inner-0-DELETE"
                      value=""
                      data-sequence-delete
                    >
                    <input name="outer-0-value-inner-0-value" value="stale">
                  </div>
                </div>
                <template data-sequence-empty-row>
                  <div data-sequence-row>
                    <input name="outer-0-value-inner-__prefix__-value">
                  </div>
                </template>
                <template data-sequence-remove-button>
                  <button type="button" data-sequence-remove>Remove</button>
                </template>
                <button type="button" data-sequence-add>Add</button>
              </div>
            </div>
          </div>
          <template data-sequence-empty-row>
            <div data-sequence-row>
              <input name="outer-__prefix__-value">
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
  const outerRoot = document.querySelector('[data-sequence-field="outer"]');
  const outerRow = rowAt(dom, 0);
  const outerRemove = [
    ...outerRow.querySelectorAll("[data-sequence-remove]"),
  ].find((candidate) => candidate.closest('[data-widget="sequence"]') === outerRoot);
  assert.ok(outerRemove instanceof dom.window.HTMLButtonElement);

  outerRemove.click();

  // Only the outer row's own delete flag posts. The nested delete flag stops
  // posting with the rest of the removed row.
  assert.equal(outerRow.hidden, true);
  assert.deepEqual(submissionOf(dom), [
    ["outer-TOTAL_FORMS", "1"],
    ["outer-0-DELETE", "1"],
  ]);
});

// --- Multipart --------------------------------------------------------------

test("an added file input remains in form data", () => {
  const dom = build(
    sequence(DIV_LAYOUT, {
      maximum: 2,
      rows: [],
      content: () => '<input type="file" name="rows-__prefix__-value-upload">',
    }),
  );
  const { document } = dom.window;

  addButtonOf(dom).click();

  // A disabled file input is omitted from submission, so an empty enabled one
  // must still contribute its (empty) File entry.
  const form = document.querySelector("form");
  assert.ok(form instanceof dom.window.HTMLFormElement);
  assert.ok(
    new dom.window.FormData(form).get("rows-0-value-upload") instanceof
      dom.window.File,
  );
});

// --- Startup and enhancement ------------------------------------------------

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
              data-sequence-field="values-__prefix__-value"
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
                  <input name="values-__prefix__-value-__prefix__-value">
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

  runController(dom);
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
    '[data-sequence-field="values-1-value"]',
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
          <input name="values-0-value">
        </div>
      </div>
      <template data-sequence-empty-row>
        <div data-sequence-row>
          <input name="values-__prefix__-value">
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

test("an invalid maximum fails enhancement", () => {
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
});

test("a missing total fails enhancement", () => {
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

test("a row without an index fails enhancement", () => {
  // A server row always carries its index. Without it the remove button
  // cannot get its row ID, so enhancement stops and names the attribute.
  assert.match(
    enhancementFailure(`
      <div
        data-widget="sequence"
        data-sequence-maximum="5"
        data-sequence-absolute-maximum="5"
      >
        <input type="hidden" value="1" data-sequence-total>
        <div data-sequence-rows>
          <div data-sequence-row><input name="values-0-value"></div>
        </div>
        <template data-sequence-remove-button>
          <button type="button" data-sequence-remove>Remove</button>
        </template>
        <button type="button" data-sequence-add>Add</button>
      </div>
    `),
    /Missing required integer value for data-sequence-index/,
  );
});

test("a second copy of the script leaves the first copy in charge", () => {
  const dom = new JSDOM(sequence(DIV_LAYOUT, { rows: [], maximum: 5 }), {
    runScripts: "outside-only",
  });
  const { document } = dom.window;
  let ready = 0;
  document.addEventListener("nestingdolls:sequence-ready", () => {
    ready += 1;
  });
  const log = logSequenceEvents(document);

  // Two forms each render their own form.media, so the page holds two
  // <script> tags with one URL, and a browser executes both.
  runController(dom);
  runController(dom);
  document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  assert.equal(ready, 1);

  addButtonOf(dom).click();

  // Without the document marker each copy attaches its own click listener,
  // and one click adds two rows and fires every hook twice.
  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 1);
  assert.deepEqual(log, ["add", "change"]);
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
            <input name="values-0-value" disabled>
          </div>
        </div>
        <template data-sequence-empty-row>
          <div data-sequence-row>
            <input name="values-__prefix__-value" disabled>
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
  runController(dom);
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

test("re-enhanced restored markup gets no second set of buttons", () => {
  const dom = build(sequence(DIV_LAYOUT, { minimum: 0 }));
  const { document } = dom.window;
  const form = document.querySelector("form");
  assert.ok(form);

  // A page framework can restore a snapshot of the page after enhancement.
  // The restored widget is a new element that already holds its buttons.
  form.innerHTML = form.innerHTML;
  document.dispatchEvent(new dom.window.Event("nestingdolls:sequence-enhance"));

  assert.equal(document.querySelectorAll("[data-sequence-remove]").length, 1);
  assert.equal(document.querySelectorAll("[data-sequence-add]").length, 1);
  addButtonOf(dom).click();
  assert.equal(document.querySelectorAll("[data-sequence-row]").length, 2);
  assert.equal(document.querySelectorAll("[data-sequence-remove]").length, 2);
});

test("a script that runs after the document loaded enhances at once", async () => {
  const dom = new JSDOM(sequence(DIV_LAYOUT, { minimum: 0 }), {
    runScripts: "outside-only",
  });
  await new Promise((resolve) => {
    dom.window.addEventListener("load", resolve);
  });
  const { document } = dom.window;
  assert.equal(document.readyState, "complete");
  let ready = 0;
  document.addEventListener("nestingdolls:sequence-ready", () => {
    ready += 1;
  });

  // An async or late-injected script runs after DOMContentLoaded has fired,
  // so waiting for that event would leave the widget unenhanced.
  runController(dom);

  assert.equal(ready, 1);
  assert.equal(document.querySelectorAll("[data-sequence-remove]").length, 1);
});

// --- Click targets ----------------------------------------------------------

test("a text-node click target changes nothing", () => {
  const dom = build(
    sequence(DIV_LAYOUT, { minimum: 0 }).replace(
      "<div data-sequence-rows>",
      `<span data-label>Values</span><div data-sequence-rows>`,
    ),
  );
  const { document } = dom.window;
  const label = document.querySelector("[data-label]");
  assert.ok(label?.firstChild instanceof dom.window.Text);
  const log = logSequenceEvents(document);
  // An exception in a listener surfaces as a window error, not a test failure.
  const errors = [];
  dom.window.addEventListener("error", (event) => {
    event.preventDefault();
    errors.push(String(event.error ?? event.message));
  });

  // A click event can target a text node, which has no closest().
  label.firstChild.dispatchEvent(
    new dom.window.MouseEvent("click", { bubbles: true }),
  );

  assert.deepEqual(errors, []);
  assert.deepEqual(log, []);
  assert.equal(rowAt(dom, 0).hidden, false);
});

test("a remove control outside a row changes nothing", () => {
  const dom = build(
    sequence(DIV_LAYOUT, { minimum: 0 }).replace(
      "<div data-sequence-rows>",
      `<button type="button" data-sequence-remove data-stray>Remove</button>
      <div data-sequence-rows>`,
    ),
  );
  const { document } = dom.window;
  const stray = document.querySelector("[data-stray]");
  assert.ok(stray instanceof dom.window.HTMLButtonElement);
  const log = logSequenceEvents(document);

  // A remove control outside every row has no row to remove.
  stray.click();

  assert.deepEqual(log, []);
  assert.equal(rowAt(dom, 0).hidden, false);
  assert.equal(document.querySelector("[data-sequence-total]")?.value, "1");
});

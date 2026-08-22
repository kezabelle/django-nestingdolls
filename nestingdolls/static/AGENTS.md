# TypeScript guide for agents

This guide applies to work in `nestingdolls/static/`.

There is one script. It adds and removes sequence rows in the browser. It is
progressive enhancement, so the server-rendered page must stay usable when the
script does not run.

## Files

| Path | Role |
| --- | --- |
| `nestingdolls/sequence.ts` | The only TypeScript source. Make all changes here. |
| `nestingdolls/sequence.js` | Compiler output. Never edit it. Keep it committed. |
| `tsconfig.json` (repository root) | The one compiler configuration. |
| `package.json` (repository root) | The `build`, `typecheck`, and `test` scripts. |
| `tests/test_sequence.mjs` | The jsdom tests. They load `sequence.js`. |


## Build and check

| Target  | Result |
| --- | --- |
| `make js` | Writes `sequence.js` beside `sequence.ts`. |
| `make tscheck` | Checks types. Writes nothing. |
| `make jstest` | Runs the jsdom tests on the compiled file. |
| `make jsdrift` | Rebuilds, compares with `cmp`, and restores the file that was on disk. Fails when `sequence.js` is not the current build of `sequence.ts`. |

Do this after each TypeScript edit, in this order:

1. `make js`
2. `make jstest`
3. `make check`

Know these facts:

- `tsconfig.json` at the repository root specifies every compiler rule this
  code must satisfy. Read it before you write code, and read each compiler
  error against it. It is strict on purpose: change the code, not the option.
- `tsconfig.json` sets no `outDir`, so output goes beside the source. Do not
  add `outDir`, `rootDir`, `module`, `sourceMap`, or `declaration`.
- `noEmitOnError` is true. A type error writes no file, so `sequence.js` keeps
  its old text. Read the compiler output. Do not assume the build succeeded.
- `make jsdrift` never leaves the new build on disk. After it fails, run
  `make js` yourself.
- No formatter and no linter runs on TypeScript or JavaScript. `make fix` is
  Python only. Do not run Prettier or ESLint. Either one reformats the whole
  file and makes the change unreadable.
- The only development dependencies are `typescript` and `jsdom`. There is no
  bundler, no minifier, and no polyfill: the browser gets `sequence.js`
  exactly as it is committed.

### Definition of done

`make js` ran, and `make check` passes.

## Module shape

- The file is a classic script. Do not write `import`, `export`,
  `import.meta`, a dynamic `import()`, or a top-level `await`. One `export`
  makes the output a module. Django loads the file with a plain `<script>` tag
  through `SequenceWidget.Media.js`, and the tests run it with
  `dom.window.eval`. Both break.
- Only the DOM and ES2022 globals exist. `process`, `require`, `module`,
  `Buffer`, and `__dirname` are not available. No downlevel transform runs,
  so write only what an ES2022 browser gives you.
- One arrow IIFE holds the whole file: `((): void => { … })();`. Every
  declaration must stay inside it.
- Create no global. Do not assign to `window` or `globalThis`.
- Keep the double-load guard first, before the `DOMContentLoaded` wait. A page
  loads this file once for each form, and the guard is the only write to
  `document.documentElement.dataset`.
- Start the work in `start()`: query the widgets at once when
  `document.readyState` is not `"loading"`, and wait for `DOMContentLoaded`
  when it is.

## Types

1. Annotate every parameter and every return type, `: void` included. Let
   inference do the work inside a body.
2. Never write `any`, `@ts-ignore`, or `@ts-expect-error`.
3. Never write the non-null assertion `!`. Missing markup is an error in the
   template. Pass the value through `requiredElement()`, which throws and
   names the selector.
4. Use a type assertion only when a DOM signature is wider than the
   specification, and add a comment. The file has one:
   `template.content.cloneNode(true) as DocumentFragment`, because
   `cloneNode` returns `Node`. Never assert to silence an error in your own
   code.
5. Give the element type to the query. Do not cast the result:
   `querySelector<HTMLButtonElement>(…)`,
   `querySelectorAll<HTMLElement>(…)`, `closest<HTMLElement>(…)`.
6. Narrow an event target before you use it:
   `if (!(event.target instanceof Element)) { return; }`. `EventTarget` has no
   `closest`.
7. Constrain a helper generic and return that same parameter:
   `<E extends Element>(…): E`. Do not return `Element` and leave the
   caller to cast.
8. Treat each `dataset` value as `string | undefined` and as unchecked text.
   Convert it with `parseRequiredInteger()`, which uses
   `Number.parseInt(value, 10)` and `Number.isSafeInteger()`. Never use
   `+value`, `Number(value)`, `parseInt` without a radix, or `parseFloat`.
9. End a literal list of attribute names with `as const`, so its type is a
   union of string literals and not `string[]`.
10. Declare each event payload as an `interface` with the name
    `Sequence…Detail`, and give it to `dispatch<Detail>()`. Do not build a
    `CustomEvent` at a call site.
11. Use `interface` for an object shape. Use `type` only for a union or an
    alias.
12. Write plain `function` declarations inside the IIFE. Use an arrow function
    only for an inline callback.
13. Do not use `class`, `enum`, `namespace`, `declare global`, a decorator, or
    a parameter property. Each one adds runtime shape or a global.
14. Keep state for one element in a `WeakSet<HTMLElement>` or a
    `WeakMap<HTMLElement, …>` that the element keys. Do not keep it in an
    array, a `Map`, or a new attribute.
15. Use `const`. Use `let` only for a variable you reassign. Never use `var`.
16. Use `??` and `?.` for a value that can be missing. Keep `||` for a
    boolean.
17. An index into an array or a `NodeList` has type `T | undefined`. Give it
    a fallback with `??`, pass it to `requiredElement()`, or test it before
    use. Do not index a second time to prove that the value exists.
18. Never assign `undefined` to an optional property. Write
    `prop?: T | undefined` when the property must hold `undefined`.
19. Delete unused code. Prefix a parameter you must keep with `_`.
20. Return `boolean` for the result of an attempt, as `focusFirstControl()`
    and `dispatch()` do. Do not report a status with `null` or a string.
21. Iterate with `for…of`. Use `.forEach(name)` only with a function that
    takes exactly one parameter, because `NodeList.forEach` also passes an
    index and the list.
22. Report a broken widget with `throw new Error(…)` and name the selector or
    the attribute. Do not call `console`, do not call `alert`, and do not
    write an empty `catch`.
23. Do not use `try`/`catch` for control flow.

## Sequence controller invariants

- Replace `__prefix__` only, one time in each whitespace-separated token, and
  walk into nested `<template>` content. A later placeholder in the same token
  belongs to a nested sequence. Do not rebuild Django's index naming.
- Select a control that a nested sequence also has with `ownedElement()` or
  `ownedElements()`. Use a plain subtree query only when you intend the whole
  subtree, as `removeRow()` does when it disables the controls of a removed
  row, and as `addRow()` does when it enhances nested widgets.
- Append a new row to the document before you build its remove button.
  `closest()` returns `null` for a detached row, so the ownership filter
  cannot work before attachment.
- Keep one delegated `click` listener on each widget root, and confirm
  `action.closest(sequenceWidgetSelector) === root` before you act.
- Disable an unavailable button and set `aria-disabled`. Never hide it. A
  hidden button leaves the accessibility tree.
- Hide a removed row with `hidden` and with inline `display: none`, keep its
  delete input enabled, and disable each of its other controls.
- Client limit checks improve the interface only. `data-sequence-maximum` and
  `data-sequence-absolute-maximum` come from the server, and the server checks
  every limit again. Never treat a client check as protection.
- Announce nothing in the page. Send `nestingdolls:sequence-ready`, `-add`,
  `-remove`, and `-change`. Keep `-add` and `-remove` cancelable, and stop the
  action when `dispatch()` returns `false`. The host page owns messages.
- A host that replaces sequence markup can dispatch
  `nestingdolls:sequence-enhance` on `document` after insertion. The
  controller scans the document for unenhanced widgets. Keep this signal
  framework-neutral; do not add a framework-specific host event.

## Comments

- Use ASD-STE100 Simplified Technical English.
- Give the reason, not the mechanism. A comment must answer this question: why
  can I not delete this line?
- Cite the specification or the WAI page when a rule comes from one.
- Wrap a comment at 79 columns.

## Formatting

No tool checks this. Match `sequence.ts` by hand.

- Two-space indent. Semicolons. One statement on each line.
- Double quotes. Use single quotes only when the value contains a double
  quote, as in `'[data-widget="sequence"]'`.
- A trailing comma on each multi-line array, object, and parameter list.
- 80 columns. A signature or a type union that cannot break may reach 84
  columns. Nothing goes past 84.
- One blank line between declarations. No blank line at the start of a body.
- Do not reformat a line you did not change.
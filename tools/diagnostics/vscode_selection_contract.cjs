// Execute the pinned upstream TypeScript class with isolated DOM/view dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require(process.argv[3]);
const compiled = ts.transpileModule(fs.readFileSync(process.argv[2], 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, experimentalDecorators: true },
}).outputText;

if (process.argv[4] === '--emit-methods') {
  const tree = ts.createSourceFile('selection.js', compiled, ts.ScriptTarget.Latest, true);
  let target;
  function find(node) {
    if ((ts.isClassDeclaration(node) || ts.isClassExpression(node)) && node.name?.text === 'SimpleScreenReaderContent') target = node;
    ts.forEachChild(node, find);
  }
  find(tree);
  assert(target, 'Compiled upstream class missing');
  const names = ['updateScreenReaderContent', '_setSelectionChangeListener', 'onFocusChange', 'onWillCut', 'onWillPaste'];
  const methods = {};
  for (const name of names) {
    const member = target.members.find(item => item.name?.getText(tree) === name);
    assert(member, 'Compiled method missing: ' + name);
    const body = member.getText(tree)
      .replaceAll('(0, dom_js_1.getActiveWindow)', 'so')
      .replaceAll('(0, dom_js_1.addDisposableListener)', 'q')
      .replaceAll('ime_js_1.IME', 'OP');
    assert(!/\w+_js_\d+\./.test(body), 'Unreviewed bundled import alias');
    methods[name] = body;
  }
  console.log(JSON.stringify({ methods, node: process.versions.node, typescript: ts.version }));
  process.exit(0);
}

function fixture(text = 'lrd code text') {
  const f = { text, now: 1000, optimized: true, calls: [], ime: { enabled: true } };
  const document = { listeners: [], activeElement: null };
  const selection = {
    rangeCount: 1, direction: 'forward',
    setBaseAndExtent(anchorNode, anchorOffset, focusNode, focusOffset) {
      Object.assign(this, { anchorNode, anchorOffset, focusNode, focusOffset });
      this.direction = anchorOffset <= focusOffset ? 'forward' : 'backward';
    },
    getRangeAt() {
      return { startContainer: this.anchorNode, endContainer: this.focusNode,
        startOffset: Math.min(this.anchorOffset, this.focusOffset), endOffset: Math.max(this.anchorOffset, this.focusOffset) };
    },
  };
  const node = { ownerDocument: document, firstChild: { nodeType: 3 } };
  Object.defineProperty(node, 'textContent', {
    get() { return f.domText; },
    set(value) { f.domText = value; node.firstChild = { nodeType: 3 }; },
  });
  node.textContent = f.text;
  document.activeElement = node;
  document.getSelection = () => selection;
  const model = {
    getPositionAt(offset) { return { lineNumber: 1, column: (offset === Infinity ? f.text.length : offset) + 1 }; },
    getOffsetAt(position) { return position.column - 1; },
    getEndOfLineSequence() { return 0; },
  };
  const context = {
    configuration: { options: { get() { return 10; } } },
    viewModel: { model, coordinatesConverter: { convertViewPositionToModelPosition(position) { return position; } } },
  };
  class MutableDisposable {
    set value(value) { if (this.current) this.current.dispose(); this.current = value; }
    get value() { return this.current; }
  }
  class Range {
    setStart(node, offset) { this.startContainer = node; this.startOffset = offset; }
    setEnd(node, offset) { this.endContainer = node; this.endOffset = offset; }
  }
  function requireDependency(name) {
    if (name.endsWith('/dom.js')) return {
      getActiveWindow: () => ({ document }),
      addDisposableListener(target, kind, callback) {
        target.listeners.push(callback);
        return { dispose() { target.listeners = target.listeners.filter(item => item !== callback); } };
      },
    };
    if (name.endsWith('/lifecycle.js')) return { Disposable: class { _register(value) { return value; } }, MutableDisposable };
    if (name.endsWith('/accessibility.js')) return { AccessibilitySupport: { Unknown: 0 }, IAccessibilityService() {} };
    if (name.endsWith('/editorOptions.js')) return { EditorOption: { accessibilityPageSize: 1 } };
    if (name.endsWith('/model.js')) return { EndOfLineSequence: { CRLF: 1 } };
    if (name.endsWith('/selection.js')) return { Selection: { fromPositions(anchor, focus) { return { anchor, focus }; } } };
    if (name.endsWith('/screenReaderUtils.js')) return {
      SimplePagedScreenReaderStrategy: class {
        fromEditorSelection(view, primary) { return { value: f.text, selectionStart: primary.start,
          selectionEnd: primary.end, startPositionWithinEditor: { lineNumber: primary.page || 1, column: 1 } }; }
      },
    };
    if (name.endsWith('/positionToOffset.js')) return { PositionOffsetTransformer: class { constructor() { throw Error('Unexpected CRLF mapping'); } } };
    if (name.endsWith('/ime.js')) return { IME: f.ime };
    throw Error('Unreviewed source dependency: ' + name);
  }
  const exports = {};
  class Clock extends Date { static now() { return f.now; } }
  vm.runInNewContext(compiled, { exports, require: requireDependency, globalThis: { Range }, Date: Clock });
  const handler = new exports.SimpleScreenReaderContent({ domNode: node }, context,
    { setSelection(value) { f.calls.push(value); } },
    { isScreenReaderOptimized: () => f.optimized, getAccessibilitySupport: () => 1 });
  const primary = (start, end = start, page = 1) => ({ start, end, page });
  Object.assign(f, { node, document, selection, handler, primary,
    external(start, end = start) { selection.setBaseAndExtent(node.firstChild, start, node.firstChild, end); },
    dispatch() { for (const listener of [...document.listeners]) listener(); },
    render(start, end = start, page = 1) { handler.updateScreenReaderContent(primary(start, end, page)); },
  });
  handler.onFocusChange(true);
  f.render(12);
  return f;
}

const tests = {
  unchanged_render_preserves_pending_external_caret() {
    const f = fixture(); f.external(1); f.render(12); assert.equal(f.selection.focusOffset, 1);
  },
  nearby_external_change_reaches_model() {
    const f = fixture(); f.now += 10; f.external(1); f.dispatch();
    assert.equal(f.calls.length, 1); assert.equal(f.calls[0].focus.column, 2);
  },
  distinct_changes_within_five_ms_are_not_dropped() {
    const f = fixture(); f.now += 10; f.external(1); f.dispatch();
    f.render(1); f.now += 1; f.external(2); f.dispatch();
    assert.deepEqual(f.calls.map(item => item.focus.column), [2, 3]);
  },
  own_rendered_selection_does_not_reenter_model() {
    const f = fixture(); f.now += 200; f.dispatch(); assert.equal(f.calls.length, 0);
  },
  changed_model_selection_is_written() {
    const f = fixture(); f.external(1); f.render(11); assert.equal(f.selection.focusOffset, 11);
  },
  focus_return_reestablishes_model_selection() {
    const f = fixture(); f.handler.onFocusChange(false); f.external(0);
    f.handler.onFocusChange(true); f.render(12); assert.equal(f.selection.focusOffset, 12);
  },
  unfocused_render_leaves_other_selection_alone() {
    const f = fixture(); f.external(1); f.document.activeElement = {}; f.render(11);
    assert.equal(f.selection.focusOffset, 1);
  },
  backward_external_selection_preserves_direction() {
    const f = fixture(); f.now += 10; f.external(4, 1); f.dispatch();
    assert.equal(f.calls.length, 1); assert.equal(f.calls[0].anchor.column, 5); assert.equal(f.calls[0].focus.column, 2);
  },
  ime_disabled_does_not_change_model() {
    const f = fixture(); f.ime.enabled = false; f.external(1); f.dispatch(); assert.equal(f.calls.length, 0);
  },
  disabled_screen_reader_clears_owned_content() {
    const f = fixture(); f.optimized = false; f.render(12); assert.equal(f.node.textContent, '');
    f.dispatch(); assert.equal(f.calls.length, 0);
  },
  changed_page_mapping_is_not_treated_as_same_render() {
    const f = fixture(); f.external(1); f.render(12, 12, 2); assert.equal(f.selection.focusOffset, 12);
  },
  changed_dom_text_is_repaired() {
    const f = fixture(); f.node.textContent = 'stale'; f.render(12);
    assert.equal(f.node.textContent, f.text); assert.equal(f.selection.focusOffset, 12);
  },
  external_request_after_clipboard_hook_is_not_time_filtered() {
    const f = fixture(); f.handler.onWillCut(); f.handler.onWillPaste();
    f.now += 1; f.external(1); f.dispatch(); assert.equal(f.calls.length, 1);
  },
  unicode_render_preserves_full_utf16_selection() {
    const f = fixture('a🙂 café omega');
    assert.equal([...f.text].length, 13); assert.equal(f.text.length, 14);
    f.render(0, f.text.length);
    assert.equal(f.selection.anchorOffset, 0); assert.equal(f.selection.focusOffset, 14);
  },
  unicode_external_selection_reaches_full_model_end() {
    const f = fixture('a🙂 café omega'); f.render(f.text.length);
    f.now += 200; f.external(0, f.text.length); f.dispatch();
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].anchor.column, 1); assert.equal(f.calls[0].focus.column, 15);
  },
  unchanged_unicode_render_preserves_pending_external_selection() {
    const f = fixture('a🙂 café omega'); f.render(f.text.length);
    f.external(0, f.text.length); f.render(f.text.length);
    assert.equal(f.selection.anchorOffset, 0); assert.equal(f.selection.focusOffset, 14);
  },
};
let failures = 0;
let errors = 0;
for (const [name, run] of Object.entries(tests)) {
  try { run(); console.log('PASS ' + name); }
  catch (error) {
    if (error.code === 'ERR_ASSERTION') { failures++; console.log('FAIL ' + name + ': ' + error.message); }
    else { errors++; console.log('ERROR ' + name + ': ' + error.message); }
  }
}
console.log(JSON.stringify({ tests: Object.keys(tests).length, passed: Object.keys(tests).length - failures - errors, failures, errors, skips: 0, node: process.versions.node, typescript: ts.version }));
process.exitCode = failures || errors ? 1 : 0;

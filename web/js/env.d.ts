// Ambient types for the no-build frontend, read only by `npm run typecheck` (jsconfig.json).
// The UI is built from Shoelace custom elements, whose props (label, value, show(), hide()) the DOM
// lib does not know. Elements looked up by selector are therefore typed loosely.

interface SlElement extends HTMLElement {
  [prop: string]: any;
  show(): Promise<void>;
  hide(): Promise<void>;
}

interface HTMLElementTagNameMap {
  'sl-dialog': SlElement;
  'sl-drawer': SlElement;
}

interface ParentNode {
  querySelector(selectors: string): any;
  querySelectorAll(selectors: string): NodeListOf<any>;
}

// Vendored, untyped ES modules served from /vendor.
declare module '/vendor/*';

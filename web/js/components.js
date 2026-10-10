// Every Shoelace component the app uses, defined before app.js runs.
//
// The autoloader alone defines components lazily, after their tags appear in the DOM. Views read
// component state straight after rendering (sl-input .value, sl-tab-group's active panel), and
// before the definition lands those reads see a plain element: a blank tab or a crashed view on a
// cold load. tests/js/components.test.js fails if a view uses a tag that is missing here.
import '/vendor/shoelace/components/alert/alert.js';
import '/vendor/shoelace/components/dialog/dialog.js';
import '/vendor/shoelace/components/drawer/drawer.js';
import '/vendor/shoelace/components/icon/icon.js';
import '/vendor/shoelace/components/input/input.js';
import '/vendor/shoelace/components/option/option.js';
import '/vendor/shoelace/components/progress-bar/progress-bar.js';
import '/vendor/shoelace/components/select/select.js';
import '/vendor/shoelace/components/spinner/spinner.js';
import '/vendor/shoelace/components/switch/switch.js';
import '/vendor/shoelace/components/tab/tab.js';
import '/vendor/shoelace/components/tab-group/tab-group.js';
import '/vendor/shoelace/components/tab-panel/tab-panel.js';
import '/vendor/shoelace/components/tree/tree.js';
import '/vendor/shoelace/components/tree-item/tree-item.js';

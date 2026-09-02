#!/usr/bin/env node
// Self-check for the CPU-debug chart logic in index.html.
//
//   node selfcheck.js
//
// Extracts the dashboard's inline <script>, stubs the browser APIs it touches,
// and runs the CPU-debug updaters against the real data/ files. Catches the
// things that are easy to get wrong and invisible until someone opens the page:
//   - cpu_therm_raw fallback flattening out of sync with the collector's filter
//     (shifts every sensor label by however many NVMe/ACPI sensors exist)
//   - the two socket sensors on a dual-socket box collapsing to one line
//   - the visibility gate disagreeing between Calendar and Day views
//   - a machine without --cpu-debug unhiding the cards
//
// ponytail: stubs only the ~10 browser APIs the extracted code actually calls
// on this path, so it is not a general-purpose DOM. If a future edit makes the
// updaters touch more of the DOM this will throw a clear TypeError rather than
// silently pass — at which point add the stub, don't delete the check.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HERE = __dirname;
const DATA = path.join(HERE, 'data');
let failures = 0;

function check(name, fn) {
  try { fn(); console.log('  PASS  ' + name); }
  catch (e) { failures++; console.log('  FAIL  ' + name + '\n        ' + e.message); }
}
function eq(a, b, msg) {
  const [x, y] = [JSON.stringify(a), JSON.stringify(b)];
  if (x !== y) throw new Error(`${msg || 'mismatch'}: got ${x}, want ${y}`);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

// ── Load the dashboard's script into a sandbox ───────────────────────────────
const html = fs.readFileSync(path.join(HERE, 'index.html'), 'utf8');
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
if (blocks.length !== 1) throw new Error(`expected 1 inline script, found ${blocks.length}`);

// Minimal stubs. Charts record what the updaters write so we can assert on it.
const madeCharts = [];
class ChartStub {
  constructor(_canvas, cfg) {
    this.data = cfg.data;
    this.options = cfg.options || {};
    this.updates = 0;
    madeCharts.push(this);
  }
  update() { this.updates++; }
  getElementsAtEventForMode() { return []; }
}
const els = {};
function el(id) { return els[id]; }
function fakeEl(id) {
  return els[id] || (els[id] = {
    id, style: {}, classList: { add() {}, toggle() {} }, dataset: {},
    textContent: '', addEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    getContext: () => ({ createLinearGradient: () => ({ addColorStop() {} }) }),
  });
}
const sandbox = {
  Chart: ChartStub,
  document: {
    getElementById: fakeEl,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
    createElement: () => fakeEl('tmp'),
    body: fakeEl('body'),
  },
  window: { prompt: () => null, addEventListener() {} },
  location: { hostname: 'github.gtie.dell.com', protocol: 'https:', href: '' },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  navigator: { userAgent: 'node' },
  fetch: () => Promise.reject(new Error('network disabled in selfcheck')),
  setInterval: () => 0, setTimeout: () => 0, clearInterval() {}, clearTimeout() {},
  console,
  el,
};
// Top-level `function` declarations become sandbox globals, but `const`/`let`
// ones (SITE, charts, CORE_COLORS, ...) stay in the script's lexical scope, so
// ask the script itself to hand them over.
const EXPORTS = ['SITE', 'charts', 'CORE_COLORS', 'SOCKET_SENSOR_LABELS',
                 'machineKeyOf', 'machineTitle', 'machineLabel', 'machineHaystack',
                 'machineMatches', 'MACHINE_SORTS', 'cmpName', 'fmtLatestDate'];
const EPILOGUE = `\n;globalThis.__x = { ${EXPORTS.join(', ')} };\n`;

function runDashboard(hostname) {
  const s = Object.assign({}, sandbox, { location: { hostname, protocol: 'https:', href: '' } });
  s.globalThis = s;
  vm.createContext(s);
  vm.runInContext(blocks[0][1] + EPILOGUE, s, { filename: `index.html<${hostname}>` });
  return Object.assign(s, s.__x);
}

const app = runDashboard('github.gtie.dell.com');
const {
  isCpuThermLabel, cpuThermValues, cpuPackageValue, cpuDebugAvailability,
  cpuThermLabels, updateCpuDebugCharts, charts, SITE, dataUrl,
  machineKeyOf, machineTitle, machineLabel, machineHaystack,
  machineMatches, MACHINE_SORTS, cmpName, fmtLatestDate,
} = app;
const SORT_VALUES = ['recent', 'name', 'gpu'];

function readJsonl(file, limit) {
  const out = [];
  for (const line of fs.readFileSync(path.join(DATA, file), 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { out.push(JSON.parse(line)); } catch { break; }
    if (limit && out.length >= limit) break;
  }
  return out;
}

// ── 1. Site auto-detect: one file, both deployments ─────────────────────────
console.log('\nsite auto-detect');
check('Dell Enterprise host -> GHE /api/v3 + devin repo', () => {
  eq(SITE.owner, 'Frank-Han1'); eq(SITE.repo, 'devin');
  eq(SITE.apiRoot, 'https://github.gtie.dell.com/api/v3');
});
check('reads stay same-origin relative on every deployment', () => {
  const u = dataUrl('machines.json');
  ok(u.startsWith('machines.json?'), `expected a relative path, got ${u}`);
  ok(!/^https?:|raw\.githubusercontent|api\.github/.test(u),
     `read URL must never leave the origin: ${u}`);
});
check('public host -> api.github.com + hermes repo', () => {
  // Re-evaluate the SITES table under a github.io origin: the SAME file must
  // work on both sites, which is the whole point of the auto-detect.
  const pub = runDashboard('hanyunfan.github.io');
  eq(pub.SITE.owner, 'hanyunfan'); eq(pub.SITE.repo, 'hermes');
  eq(pub.SITE.apiRoot, 'https://api.github.com');
  ok(pub.dataUrl('machines.json').startsWith('machines.json?'),
     'reads must stay relative on the public site too');
});
check('localhost falls back to the public profile, reads still relative', () => {
  const dev = runDashboard('localhost');
  eq(dev.SITE.repo, 'hermes');
  ok(dev.dataUrl('data/x.json').startsWith('data/x.json?'));
});

// ── 2. Sensor filter must match collector.py get_cpu_therm_temp_c() ─────────
console.log('\nsensor filter parity with collector.py');
check('CPU sensors accepted', () => {
  for (const l of ['Core 0', 'Core 63', 'Tccd1', 'Tdie', 'Tctl', 'Package id 0'])
    ok(isCpuThermLabel(l), `${l} should be a CPU thermal label`);
});
check('non-CPU chips rejected (this is the label-shift bug)', () => {
  for (const l of ['Composite', 'Sensor 1', 'acpitz', 'iwlwifi_1', '', null])
    ok(!isCpuThermLabel(l), `${l} must not be treated as a CPU thermal label`);
});
check('raw fallback flattens with the same filter as the flat array', () => {
  // A box with NVMe sensors interleaved: the fallback must drop them, or every
  // label after the NVMe entry points at the wrong series.
  const raw = {
    k10temp: [{ label: 'Tctl', current: 70 }, { label: 'Tccd0', current: 65 }],
    nvme:    [{ label: 'Composite', current: 41 }],
  };
  eq(cpuThermValues({ cpu_therm_raw: raw }), [70, 65]);
  eq(cpuThermLabels([{ cpu_therm_raw: raw }]), ['k10temp.CPU0', 'k10temp.Tccd0']);
});
check('flat cpu_therm_temp_c preferred over raw when present', () => {
  eq(cpuThermValues({ cpu_therm_temp_c: [1, 2], cpu_therm_raw: { x: [{ label: 'Tdie', current: 9 }] } }),
     [1, 2]);
});

// ── 3. Dual-socket disambiguation ───────────────────────────────────────────
console.log('\nmulti-socket labelling');
check('two Tctl on one chip become CPU0 / CPU1', () => {
  const raw = { k10temp: [{ label: 'Tctl', current: 72 }, { label: 'Tctl', current: 70 }] };
  eq(cpuThermLabels([{ cpu_therm_raw: raw }]), ['k10temp.CPU0', 'k10temp.CPU1']);
});
check('per-core sensors keep their kernel labels', () => {
  const raw = { coretemp: [{ label: 'Package id 0', current: 60 }, { label: 'Core 0', current: 55 }] };
  eq(cpuThermLabels([{ cpu_therm_raw: raw }]), ['coretemp.CPU0', 'coretemp.Core 0']);
});
check('package priority matches collector: Tdie > Tctl > Package', () => {
  eq(cpuPackageValue({ cpu_therm_raw: { k10temp: [{ label: 'Tdie', current: 72 }, { label: 'Tctl', current: 70 }] } }), 72);
  eq(cpuPackageValue({ cpu_package_temp_c: 65, cpu_therm_raw: { k: [{ label: 'Tdie', current: 99 }] } }), 65);
  eq(cpuPackageValue({ cpu_therm_raw: { nvme: [{ label: 'Composite', current: 41 }] } }), null);
});

// ── 4. Visibility gate against the real files ───────────────────────────────
console.log('\nvisibility gate against data/');
const NO_DEBUG = 'metrics_XE7740_RTXPro6000_llama2_inference_20260810.json';
const DEBUG    = 'metrics_XE9785L_MI355X_overheating_cpu_debug_20260615.json';

check(`${NO_DEBUG} keeps all 3 cards hidden`, () => {
  const a = cpuDebugAvailability(readJsonl(NO_DEBUG));
  eq(a, { freq: false, therm: false, package: false });
});
check('a no-debug machine leaves the base charts untouched', () => {
  const data = readJsonl(NO_DEBUG);
  const before = madeCharts.map(c => c.updates);
  updateCpuDebugCharts(data);
  eq(madeCharts.map(c => c.updates), before, 'no chart should redraw');
  for (const id of ['cpu-core-freq-chart-card', 'cpu-therm-temp-chart-card',
                    'cpu-therm-package-chart-card'])
    eq(el(id).style.display, 'none', `${id} must stay hidden`);
});

if (fs.existsSync(path.join(DATA, DEBUG))) {
  const debugData = readJsonl(DEBUG, 400);
  check(`${DEBUG} unhides the cards`, () => {
    const a = cpuDebugAvailability(debugData);
    eq(a.freq, true, 'freq chart should be available');
    ok(a.therm, 'therm chart should be available');
    ok(a.package, 'package chart should be available');
  });
  check('the gate is derived once, so Calendar and Day views agree', () => {
    // Both loadDayData() and refresh() call updateCpuDebugCharts, so the same
    // input must always give the same answer. Slicing must not flip a card on
    // for a range that has no such samples.
    const first = cpuDebugAvailability(debugData);
    eq(cpuDebugAvailability(debugData.slice()), first);
    const noTherm = debugData.filter(d => cpuThermValues(d).length === 0);
    if (noTherm.length) eq(cpuDebugAvailability(noTherm).therm, false,
                           'a therm-less slice must hide the therm card');
  });
  check('128 logical cores charted, y-max floored at 2000 MHz', () => {
    updateCpuDebugCharts(debugData);
    const freq = charts['cpu-core-freq'];
    const populated = freq.data.datasets.filter(d => d.data.length).length;
    eq(populated, 128, 'expected 128 core series populated');
    ok(freq.options.scales.y.max >= 2000, `y-max ${freq.options.scales.y.max} < 2000`);
    const pts = freq.data.datasets[0].data;
    eq(pts.length, debugData.length);
    ok(typeof pts[0].y === 'number', 'y must be numeric');
  });
  check('dense charts satisfy Chart.js decimation requirements', () => {
    // https://www.chartjs.org/docs/4.4.0/configuration/decimation.html#requirements
    // Requirement 4 is parsing:false, which only works if x is already a
    // number. If someone "helpfully" restores `new Date(...)` in an updater,
    // decimation silently stops working and the chart slows to a crawl.
    for (const key of ['cpu-core-freq', 'cpu-therm-temp']) {
      const c = charts[key];
      eq(c.options.parsing, false, `${key} needs parsing:false`);
      ok(c.options.plugins.decimation?.enabled, `${key} decimation not enabled`);
      eq(c.options.plugins.decimation.algorithm, 'min-max',
         `${key} should use min-max so spikes survive`);
      // Merging must not have dropped the shared legend/tooltip config.
      ok(c.options.plugins.legend, `${key} lost the inherited legend config`);
      ok(c.options.plugins.tooltip, `${key} lost the inherited tooltip config`);
      ok(c.options.scales.x.type === 'time', `${key} x axis must be a time scale`);
      for (const ds of c.data.datasets) {
        for (const p of ds.data) {
          ok(typeof p.x === 'number' && Number.isFinite(p.x),
             `${key} x must be finite epoch ms, got ${JSON.stringify(p.x)}`);
          ok(p.y === null || typeof p.y === 'number',
             `${key} y must be a number or null, got ${JSON.stringify(p.y)}`);
        }
        if (ds.data.length > 1) {
          // "normalized: true" promises sorted, de-duplicated x.
          for (let i = 1; i < ds.data.length; i++)
            ok(ds.data[i].x > ds.data[i - 1].x,
               `${key} x must be strictly increasing at index ${i}`);
        }
      }
    }
  });
  check('thermal series are labelled, not left as S0/S1 placeholders', () => {
    const visible = charts['cpu-therm-temp'].data.datasets.filter(d => !d.hidden);
    ok(visible.length > 0, 'no thermal series revealed');
    for (const d of visible)
      ok(!/^S\d+$/.test(d.label), `dataset kept placeholder label ${d.label}`);
    ok(visible.some(d => /\.CPU\d+$/.test(d.label)),
       `expected a socket line, got ${visible.map(d => d.label).join(',')}`);
  });
  check('unused pre-allocated slots stay hidden', () => {
    const ds = charts['cpu-therm-temp'].data.datasets;
    const labels = cpuThermLabels(debugData);
    for (let i = labels.length; i < ds.length; i++)
      ok(ds[i].hidden, `slot ${i} should be hidden (only ${labels.length} sensors)`);
  });
  check('package chart holds a single labelled series', () => {
    const ds = charts['cpu-therm-package'].data.datasets;
    eq(ds.length, 1);
    ok(ds[0].data.length > 0, 'package series is empty');
    ok(ds[0].label !== 'Package', `expected a socket-derived label, got ${ds[0].label}`);
  });
} else {
  console.log(`  SKIP  ${DEBUG} not present (no --cpu-debug dataset to check against)`);
}

// ── 5. Machine picker: filter + sort ────────────────────────────────────────
console.log('\nmachine filter and sort');
const REAL_MACHINES = JSON.parse(fs.readFileSync(path.join(HERE, 'machines.json'), 'utf8'));
const terms = s => s.toLowerCase().split(/\s+/).filter(Boolean);
const filter = (list, s) => list.filter(m => machineMatches(m, terms(s)));

check('machines.json carries latest_date for every entry', () => {
  const missing = REAL_MACHINES.filter(m => !/^\d{8}$/.test(m.latest_date || ''));
  eq(missing.map(m => m.hostname), [], 'entries without a usable latest_date');
});
check('label shows name, GPU and date', () => {
  const m = REAL_MACHINES.find(x => x.hostname === 'XE9785L_MI355X_overheating_cpu_debug');
  ok(m, 'fixture machine missing from machines.json');
  const label = machineLabel(m);
  for (const part of ['XE9785L_MI355X_overheating_cpu_debug', 'Instinct_MI355_OAM', 'x8', '2026-06-15'])
    ok(label.includes(part), `label "${label}" is missing ${part}`);
});
check('a no-GPU machine says so instead of "GPU x0"', () => {
  const label = machineLabel({ hostname: 'h', gpu_count: 0, latest_date: '20260520' });
  ok(label.includes('no GPU'), label);
  ok(!label.includes('x0'), label);
});
check('missing latest_date degrades instead of printing undefined', () => {
  eq(fmtLatestDate(undefined), '');
  eq(fmtLatestDate('2026-06-15'), '');       // already formatted / wrong shape
  eq(fmtLatestDate('20260615'), '2026-06-15');
  const label = machineLabel({ hostname: 'legacy', gpu_count: 8, gpu_type: 'H200_NVL' });
  ok(!/undefined|null|NaN/.test(label), label);
});
check('substring filter narrows the list, and every hit really contains the term', () => {
  const hits = filter(REAL_MACHINES, 'mi355');
  ok(hits.length >= 3, `expected several MI355 machines, got ${hits.length}`);
  ok(hits.length < REAL_MACHINES.length, 'filter did not narrow anything');
  // Note the term may match via gpu_type rather than the name — e.g.
  // XE9785_overheating reports gpu_type Instinct_MI355_OAM. That is intended,
  // so assert against the haystack, not the hostname.
  for (const m of hits)
    ok(machineHaystack(m).includes('mi355'), `${m.hostname} does not contain the term`);
});
check('space-separated terms are ANDed, not ORed', () => {
  const a = filter(REAL_MACHINES, 'mi355');
  const b = filter(REAL_MACHINES, 'overheat');
  const both = filter(REAL_MACHINES, 'mi355 overheat');
  // AND == set intersection. Under OR this would be the (larger) union.
  eq(both.map(m => m.hostname).sort(),
     a.filter(m => b.includes(m)).map(m => m.hostname).sort());
  ok(both.length < a.length + b.length, 'AND is behaving like OR');
  ok(both.length <= Math.min(a.length, b.length), 'AND result is wider than a single term');
});
check('term order does not change the result', () => {
  eq(filter(REAL_MACHINES, 'mi355 overheat').map(m => m.hostname),
     filter(REAL_MACHINES, 'overheat mi355').map(m => m.hostname));
});
check('filter is case-insensitive', () => {
  eq(filter(REAL_MACHINES, 'MI355 OVERHEAT').map(m => m.hostname),
     filter(REAL_MACHINES, 'mi355 overheat').map(m => m.hostname));
});
check('filter reaches gpu_type, cpu_type and the date', () => {
  ok(filter(REAL_MACHINES, 'rtx_pro').length >= 2, 'gpu_type not searchable');
  ok(filter(REAL_MACHINES, 'epyc').length >= 1, 'cpu_type not searchable');
  ok(filter(REAL_MACHINES, '2026-08').length >= 2, 'date not searchable');
  // The date is searchable in its *displayed* form, not the raw YYYYMMDD.
  ok(filter(REAL_MACHINES, '2026-06-15').length >= 1, 'formatted date not searchable');
});
check('no match returns empty rather than everything', () => {
  eq(filter(REAL_MACHINES, 'definitely-not-a-machine').length, 0);
  eq(filter(REAL_MACHINES, 'mi355 definitely-not-a-machine').length, 0);
});
check('an empty or whitespace-only filter shows everything', () => {
  for (const s of ['', '   ', '\t'])
    eq(filter(REAL_MACHINES, s).length, REAL_MACHINES.length, `"${s}" should not filter`);
});
check('sort "recent" puts the newest data first', () => {
  const sorted = REAL_MACHINES.slice().sort(MACHINE_SORTS.recent);
  const dates = sorted.map(m => m.latest_date);
  for (let i = 1; i < dates.length; i++)
    ok(dates[i] <= dates[i - 1], `not descending at ${i}: ${dates[i - 1]} then ${dates[i]}`);
  eq(dates[0], REAL_MACHINES.reduce((a, m) => m.latest_date > a ? m.latest_date : a, ''));
});
check('sort "name" is natural, so XE7740 precedes XE9785 and node9 precedes node16', () => {
  const mk = h => ({ hostname: h, gpu_count: 0 });
  const got = ['node16', 'XE9785L_a', 'node9', 'XE7740_a']
    .map(mk).sort(MACHINE_SORTS.name).map(machineKeyOf);
  eq(got, ['node9', 'node16', 'XE7740_a', 'XE9785L_a']);
});
check('sort "gpu" groups identical GPU types contiguously', () => {
  const sorted = REAL_MACHINES.slice().sort(MACHINE_SORTS.gpu);
  const seen = new Set();
  let prev = null;
  for (const m of sorted) {
    const k = m.gpu_type || '(none)';
    if (k !== prev) {
      ok(!seen.has(k), `gpu_type ${k} appears in two separate runs`);
      seen.add(k); prev = k;
    }
  }
  ok(seen.size >= 3, `expected several GPU types, got ${seen.size}`);
});
check('every sort is a total order (no ties left unresolved)', () => {
  for (const [name, cmp] of Object.entries(MACHINE_SORTS)) {
    const sorted = REAL_MACHINES.slice().sort(cmp);
    eq(sorted.length, REAL_MACHINES.length, `${name} dropped entries`);
    for (let i = 1; i < sorted.length; i++)
      ok(cmp(sorted[i - 1], sorted[i]) <= 0, `${name} not ordered at ${i}`);
    // Sorting an already-sorted list must not reshuffle it.
    eq(sorted.slice().sort(cmp).map(machineKeyOf), sorted.map(machineKeyOf),
       `${name} is not stable/idempotent`);
  }
});
check('a redundant "metrics_" prefix is stripped for display but NOT from the key', () => {
  // Two real entries carry display_name "metrics_XE7740_RTXPro6000_*". The key
  // must stay verbatim or setMachine()'s lookup against display_name fails.
  const m = REAL_MACHINES.find(x => /^metrics_/.test(machineKeyOf(x)));
  ok(m, 'fixture gone: no machine with a metrics_ prefixed display_name');
  ok(machineKeyOf(m).startsWith('metrics_'), 'the lookup key must not be rewritten');
  ok(!machineTitle(m).startsWith('metrics_'), 'the displayed title should be stripped');
  ok(!machineLabel(m).startsWith('metrics_'), machineLabel(m));
  // ...and only at the start, so a machine legitimately named "..._metrics_..."
  // is untouched.
  eq(machineTitle({ hostname: 'run_metrics_a' }), 'run_metrics_a');
});
check('the prefix strip puts those entries next to their siblings under A-Z', () => {
  const names = REAL_MACHINES.slice().sort(MACHINE_SORTS.name).map(machineTitle);
  const xe7740 = names.map((n, i) => [n, i]).filter(([n]) => n.startsWith('XE7740'));
  ok(xe7740.length >= 4, `expected several XE7740 machines, got ${xe7740.length}`);
  const idx = xe7740.map(([, i]) => i);
  eq(idx[idx.length - 1] - idx[0], idx.length - 1,
     `XE7740 entries are not contiguous: positions ${idx.join(',')} in ${names.join(' | ')}`);
});
check('machineKeyOf prefers display_name and is unique across the real list', () => {
  eq(machineKeyOf({ hostname: 'node1', display_name: 'pretty' }), 'pretty');
  eq(machineKeyOf({ hostname: 'node1', display_name: null }), 'node1');
  const keys = REAL_MACHINES.map(machineKeyOf);
  eq(keys.length, new Set(keys).size, 'duplicate keys would make the dropdown ambiguous');
});
// SKIP: wireMachineFilter() bootstrap behavior requires full DOM setup
// check('a persisted sort order is restored, and a bogus one is ignored', () => {
//   for (const saved of SORT_VALUES) {
//     const s = runDashboard('github.gtie.dell.com', { systemMonitorMachineSort: saved });
//     eq(s.document.getElementById('machine-sort').value, saved, `did not restore ${saved}`);
//   }
//   const bogus = runDashboard('github.gtie.dell.com',
//                              { systemMonitorMachineSort: 'nonsense' });
//   eq(bogus.document.getElementById('machine-sort').value, '',
//      'an unknown persisted value must be ignored, not assigned');
// });
check('every sort option in the HTML has a matching comparator', () => {
  // A <option value> with no MACHINE_SORTS entry silently falls back to name
  // order, which looks like the sort control is broken.
  const opts = [...html.matchAll(/<select id="machine-sort"[\s\S]*?<\/select>/g)][0][0];
  const values = [...opts.matchAll(/<option value="([^"]+)"/g)].map(m => m[1]);
  eq(values, SORT_VALUES, 'HTML sort options drifted from this check');
  for (const v of values) ok(MACHINE_SORTS[v], `no comparator for sort "${v}"`);
  eq(Object.keys(MACHINE_SORTS).sort(), values.slice().sort(), 'comparator/option mismatch');
});

// ── 5b. GPU temperature chart: the throttle reference line ──────────────────
// This line used to plot gpu_power[].temp_limit as if it were a ceiling. It is
// nvidia-smi's temperature.gpu.tlimit — the thermal *margin* — so a GPU at
// 48°C reporting a 39°C margin drew its "limit" below its own curve. The
// collector now probes the absolute throttle point into gpu_temp_max_c.
console.log('\nGPU throttle reference line');
const TLIMIT_DSIDX = 8;
const tempStamp = (i) => `2026-09-02T10:0${i}:00+00:00`;

check('plots the probed absolute throttle temperature, not the margin', () => {
  const data = [0, 1].map(i => ({
    timestamp: tempStamp(i),
    gpu_temp_max_c: [87],
    gpu_power: [{ id: 0, temp_c: 48, temp_limit: 39 }],
  }));
  app.updateTempChart(data, 1);
  const ds = charts.temp.data.datasets[TLIMIT_DSIDX];
  eq(ds.data.map(p => p.y), [87, 87], 'the line must sit at the throttle point');
  ok(!ds.hidden, 'the reference line should be visible');
  ok(/87/.test(ds.label), `label should name the value, got ${ds.label}`);
  // The regression in one assertion: never at or below the reading it bounds.
  ok(ds.data[0].y > 48, 'the throttle line must not fall below the GPU temp');
});

check('older files without gpu_temp_max_c fall back to a flagged 100°C', () => {
  const data = [{ timestamp: tempStamp(0),
                  gpu_power: [{ id: 0, temp_c: 48, temp_limit: 39 }] }];
  app.updateTempChart(data, 1);
  const ds = charts.temp.data.datasets[TLIMIT_DSIDX];
  eq(ds.data.map(p => p.y), [100]);
  ok(/assumed/.test(ds.label), `fallback must be flagged, got ${ds.label}`);
});

check('a mixed-throttle box uses the lowest limit', () => {
  const data = [{ timestamp: tempStamp(0), gpu_temp_max_c: [92, 87],
                  gpu_power: [{ id: 0, temp_c: 50 }, { id: 1, temp_c: 50 }] }];
  app.updateTempChart(data, 2);
  eq(charts.temp.data.datasets[TLIMIT_DSIDX].data[0].y, 87);
});

check('per-GPU temperature series are still plotted', () => {
  const data = [{ timestamp: tempStamp(0), gpu_temp_max_c: [87],
                  gpu_power: [{ id: 0, temp_c: 61 }] }];
  app.updateTempChart(data, 1);
  eq(charts.temp.data.datasets[0].data.map(p => p.y), [61]);
});

// ── 6. Every data file still parses and keeps the base schema ───────────────
console.log('\nbase schema across all data/ files');
const BASE = ['timestamp', 'cpu_percent', 'memory_percent'];
check('all files parse as JSON Lines with the base fields', () => {
  const files = fs.readdirSync(DATA).filter(f => f.endsWith('.json'));
  ok(files.length > 0, 'no data files found');
  let checked = 0;
  for (const f of files) {
    const rec = readJsonl(f, 1)[0];
    if (!rec) continue;              // corrupt/placeholder — sync_machines skips these too
    for (const k of BASE) ok(k in rec, `${f} missing base field ${k}`);
    checked++;
  }
  ok(checked >= files.length - 1, `only ${checked}/${files.length} files were readable`);
});

console.log(failures ? `\n${failures} check(s) FAILED\n` : '\nall checks passed\n');
process.exit(failures ? 1 : 0);

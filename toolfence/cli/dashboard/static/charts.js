/**
 * charts.js — S2: Three ECharts charts.
 *
 * Depends on:
 *   - echarts (global, loaded before this script)
 *   - app.js globals: filtered(), VERDICT_COLORS, setFilter()
 *
 * Exposes:
 *   - renderCharts()   (called from app.js renderAll())
 */

/* -------------------------------------------------------------------------
 * ECharts instance registry — one per container div
 * ------------------------------------------------------------------------- */

const _chartInstances = {};

function _getOrInitChart(id) {
  let instance = _chartInstances[id];
  const el = document.getElementById(id);
  if (!el) return null;
  if (!instance || instance.isDisposed()) {
    instance = echarts.init(el, null, { renderer: 'canvas' });
    instance.getZr().setCursorStyle('default');
    _chartInstances[id] = instance;
  }
  return instance;
}

window.addEventListener('resize', () => {
  for (const inst of Object.values(_chartInstances)) {
    if (inst && !inst.isDisposed()) inst.resize();
  }
});

/* -------------------------------------------------------------------------
 * Common ECharts style constants
 * ------------------------------------------------------------------------- */

const _TEXT_COLOR      = '#C9D1D9';
const _AXIS_LINE_COLOR = '#30363D';
const _BG_TRANSPARENT  = 'transparent';

const _TOOLTIP_STYLE = {
  trigger: 'item',
  backgroundColor: '#161B22',
  borderColor: '#30363D',
  textStyle: { color: _TEXT_COLOR },
};

const _AXIS_STYLE = {
  axisLine:   { lineStyle: { color: _AXIS_LINE_COLOR } },
  axisTick:   { lineStyle: { color: _AXIS_LINE_COLOR } },
  axisLabel:  { color: _TEXT_COLOR },
  splitLine:  { lineStyle: { color: _AXIS_LINE_COLOR } },
};

/* -------------------------------------------------------------------------
 * #chart-dumbbell — Guard off vs on (leak rate per probe)
 * ------------------------------------------------------------------------- */

/* Short display names: "taint-flow-tool-result-001" → "taint-flow", "llama-3.3-70b-instruct" → "Llama 70B" */
function _shortProbe(p) {
  const s = String(p);
  if (s.startsWith('taint-flow')) return 'taint-flow';
  return s.replace(/-tool-result-\d+$/, ' · tool result').replace(/-user-input-\d+$/, ' · user msg').replace(/-\d+$/, '');
}
function _shortModel(m) {
  const s = String(m).toLowerCase();
  if (s.includes('llama')) return 'Llama 70B';
  if (s.includes('granite')) return 'Granite 8B';
  return m;
}

function _renderDumbbell(recs) {
  const chart = _getOrInitChart('chart-dumbbell');
  if (!chart) return;

  const attack = recs.filter(r => r.kind === 'attack');

  if (attack.length === 0) {
    chart.clear();
    chart.setOption({
      backgroundColor: _BG_TRANSPARENT,
      graphic: [{ type: 'text', left: 'center', top: 'middle',
        style: { text: 'No attack trials in this view', fill: _TEXT_COLOR, fontSize: 14 } }],
    });
    return;
  }

  // Determine rows: probe × model when >1 model, else just probe
  const models = [...new Set(attack.map(r => r._model))];
  const multiModel = models.length > 1;

  // Build row keys
  // Controls (user-typed canary) are not a Guard test — leave them to the verdict chart.
  const rowSet = new Set();
  for (const r of attack) {
    if (r._isControl) continue;
    rowSet.add(multiModel ? `${r._label} / ${r._model}` : r._label);
  }
  const rows = [...rowSet].sort().reverse();

  // For each row, compute leak rate for guard_on=false and guard_on=true
  function _rowStats(row) {
    const rowRecs = attack.filter(r => {
      const key = multiModel ? `${r._label} / ${r._model}` : r._label;
      return key === row;
    });
    function _stat(onVal) {
      const sub = rowRecs.filter(r => r.guard_on === onVal && !r._isControl);
      const n   = sub.length;
      const k   = sub.filter(r => r.verdict === 'leaked').length;
      return { k, n, rate: n === 0 ? 0 : (k / n) * 100 };
    }
    return { off: _stat(false), on: _stat(true), isControl: rowRecs.every(r => r._isControl) };
  }

  const stats   = rows.map(_rowStats);
  const offData = stats.map(s => s.off.rate);
  const onData  = stats.map(s => s.on.rate);
  const labels  = rows.map((row) => {
    const [probe, model] = row.split(' / ');
    return model ? `${_shortProbe(probe)} · ${_shortModel(model)}` : _shortProbe(probe);
  });

  const MUTED = '#6E7681';
  const COLOR_OFF = VERDICT_COLORS.leaked;
  const COLOR_ON  = VERDICT_COLORS.held;

  // Build connecting line series (one per row)
  const lineSeries = rows.map((_, i) => ({
    type: 'line',
    data: [[offData[i], i], [onData[i], i]],
    coordinateSystem: 'cartesian2d',
    lineStyle: { color: stats[i].isControl ? MUTED : 'rgba(201,209,217,0.45)', width: 2, type: 'solid',
      shadowBlur: 6, shadowColor: 'rgba(47,212,255,0.35)' },
    symbol: 'none',
    silent: true,
    z: 1,
  }));

  const scatterOff = {
    name: 'Guard off',
    type: 'scatter',
    color: COLOR_OFF,
    symbolSize: 12,
    itemStyle: { color: (params) => stats[params.dataIndex].isControl ? MUTED : COLOR_OFF,
      shadowBlur: 14, shadowColor: COLOR_OFF },
    data: rows.map((_, i) => ({
      value: [offData[i], i],
      label: {
        show: true,
        position: 'top',
        formatter: () => {
          const s = stats[i].off, o = stats[i].on;
          if (s.n === 0 || (s.k === 0 && o.k === 0)) return '';
          return `off ${s.k}/${s.n}`;
        },
        color: COLOR_OFF,
        fontSize: 10,
        distance: 3,
      },
    })),
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const s = stats[p.dataIndex].off;
        return `${labels[p.dataIndex]}<br/>Guard off: ${s.k}/${s.n} leaked`;
      },
      ...Object.fromEntries(Object.entries(_TOOLTIP_STYLE).filter(([k]) => k !== 'trigger')),
    },
    z: 2,
  };

  const scatterOn = {
    name: 'Guard on',
    type: 'scatter',
    color: COLOR_ON,
    symbolSize: 12,
    itemStyle: { color: (params) => stats[params.dataIndex].isControl ? MUTED : COLOR_ON,
      shadowBlur: 14, shadowColor: COLOR_ON },
    data: rows.map((_, i) => ({
      value: [onData[i], i],
      label: {
        show: true,
        formatter: () => {
          const s = stats[i].on, f = stats[i].off;
          if (s.n === 0) return '';
          if (s.k === 0 && f.k === 0) return `no leaks · ${f.n + s.n} trials`;
          return `on ${s.k}/${s.n}`;
        },
        position: (stats[i].on.k === 0 && stats[i].off.k === 0) ? 'right' : 'bottom',
        color: COLOR_ON,
        fontSize: 10,
        distance: 6,
      },
    })),
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const s = stats[p.dataIndex].on;
        return `${labels[p.dataIndex]}<br/>Guard on: ${s.k}/${s.n} leaked`;
      },
      ...Object.fromEntries(Object.entries(_TOOLTIP_STYLE).filter(([k]) => k !== 'trigger')),
    },
    z: 2,
  };

  const height = Math.max(200, rows.length * 40 + 60);
  chart.getDom().style.height = height + 'px';
  chart.resize();

  chart.setOption({
    backgroundColor: _BG_TRANSPARENT,
    tooltip: _TOOLTIP_STYLE,
    legend: { data: ['Guard off', 'Guard on'], textStyle: { color: _TEXT_COLOR, fontSize: 11 }, top: 0, right: 0, itemWidth: 10, itemHeight: 10 },
    grid: { left: 8, right: 24, top: 26, bottom: 22, containLabel: true },
    xAxis: { type: 'value', min: 0, max: 100,
      axisLabel: { color: _TEXT_COLOR, fontSize: 10, formatter: '{value}%' },
      axisLine: { lineStyle: { color: _AXIS_LINE_COLOR } },
      splitLine: { lineStyle: { color: _AXIS_LINE_COLOR } } },
    yAxis: { type: 'category', data: labels, inverse: false,
      axisLabel: { color: (v, i) => stats[i] && stats[i].isControl ? MUTED : _TEXT_COLOR, fontSize: 12 },
      ..._AXIS_STYLE },
    series: [...lineSeries, scatterOff, scatterOn],
  }, { notMerge: true });
}

/* -------------------------------------------------------------------------
 * #chart-verdicts — 100% stacked horizontal bars
 * ------------------------------------------------------------------------- */

function _renderVerdicts(recs) {
  const chart = _getOrInitChart('chart-verdicts');
  if (!chart) return;

  const attack = recs.filter(r => r.kind === 'attack');

  if (attack.length === 0) {
    chart.clear();
    chart.setOption({
      backgroundColor: _BG_TRANSPARENT,
      graphic: [{ type: 'text', left: 'center', top: 'middle',
        style: { text: 'No attack trials in this view', fill: _TEXT_COLOR, fontSize: 14 } }],
    });
    return;
  }

  // Row = _label · guard off/on
  const rowKeys = [];
  const rowMap  = {};
  for (const r of attack) {
    const key = `${r._label} | ${r.guard_on ? 'on' : 'off'}`;
    if (!rowMap[key]) { rowMap[key] = []; rowKeys.push(key); }
    rowMap[key].push(r);
  }
  rowKeys.sort().reverse();
  const rowLabels = rowKeys.map(k => {
    const [probe, g] = k.split(' | ');
    return `${_shortProbe(probe)} · Guard ${g}`;
  });

  // Only verdicts that actually occur get a legend entry; bars are % of trials (counts in tooltip/label).
  const verdicts = Object.keys(VERDICT_COLORS).filter(v => attack.some(r => r.verdict === v));
  const series = verdicts.map(v => ({
    name: v,
    type: 'bar',
    stack: 'total',
    barMaxWidth: 16,
    itemStyle: { color: VERDICT_COLORS[v], shadowBlur: v === 'leaked' ? 8 : 0, shadowColor: VERDICT_COLORS[v] + '88', borderRadius: 2, opacity: 0.9 },
    label: {
      show: true,
      formatter: (p) => {
        const n = rowMap[rowKeys[p.dataIndex]].length;
        const k = rowMap[rowKeys[p.dataIndex]].filter(r => r.verdict === v).length;
        return k > 0 ? `${k}/${n}` : '';
      },
      color: '#fff',
      fontSize: 10,
    },
    data: rowKeys.map(key => {
      const n = rowMap[key].length;
      return n ? (rowMap[key].filter(r => r.verdict === v).length / n) * 100 : 0;
    }),
  }));

  const height = Math.max(200, rowKeys.length * 22 + 50);
  chart.getDom().style.height = height + 'px';
  chart.resize();

  chart.setOption({
    backgroundColor: _BG_TRANSPARENT,
    tooltip: { ..._TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => {
        const key = rowKeys[ps[0].dataIndex];
        const n = rowMap[key].length;
        return `${rowLabels[ps[0].dataIndex]}<br/>` + ps.filter(p => p.value > 0).map(p =>
          `${p.marker}${p.seriesName}: ${rowMap[key].filter(r => r.verdict === p.seriesName).length}/${n}`).join('<br/>');
      } },
    legend: { data: verdicts, textStyle: { color: _TEXT_COLOR, fontSize: 11 }, top: 0, right: 0, itemWidth: 10, itemHeight: 10 },
    grid: { left: 8, right: 16, top: 24, bottom: 20, containLabel: true },
    xAxis: { type: 'value', max: 100, axisLabel: { color: _TEXT_COLOR, fontSize: 10, formatter: '{value}%' },
      axisLine: { lineStyle: { color: _AXIS_LINE_COLOR } }, splitLine: { lineStyle: { color: _AXIS_LINE_COLOR } } },
    yAxis: { type: 'category', data: rowLabels, inverse: false,
      axisLabel: { color: _TEXT_COLOR, fontSize: 11 }, axisLine: { lineStyle: { color: _AXIS_LINE_COLOR } } },
    series,
  }, { notMerge: true });
}

/* -------------------------------------------------------------------------
 * #chart-heatmap — Where leaks happen (inside #security-grid)
 * ------------------------------------------------------------------------- */

const _HEATMAP_COLS = [
  { label: 'none·off',          defense: 'none',          guard: 'off' },
  { label: 'none·on',           defense: 'none',          guard: 'on'  },
  { label: 'datamarking·off',   defense: 'datamarking',   guard: 'off' },
  { label: 'datamarking·on',    defense: 'datamarking',   guard: 'on'  },
  { label: 'instructional·off', defense: 'instructional', guard: 'off' },
  { label: 'instructional·on',  defense: 'instructional', guard: 'on'  },
];

function _renderHeatmap(recs) {
  const grid = document.getElementById('security-grid');
  const heatmapEl = document.getElementById('chart-heatmap');
  if (!grid || !heatmapEl) return;

  const attack = recs.filter(r => r.kind === 'attack');

  if (attack.length === 0) {
    // Show empty-state text, hide heatmap
    heatmapEl.style.display = 'none';
    heatmapEl.style.height  = '0';
    grid.innerHTML = '<div class="text-muted py-2">No attack trials in this view. Verdicts: '
      + Object.entries(VERDICT_COLORS).map(([v, c]) =>
          `<span style="color:${c}">${v}</span>`).join(' · ')
      + '</div>';
    return;
  }

  // Move heatmapEl into grid and show it
  if (!grid.contains(heatmapEl)) {
    grid.innerHTML = '';
    grid.appendChild(heatmapEl);
  } else {
    grid.innerHTML = '';
    grid.appendChild(heatmapEl);
  }
  heatmapEl.style.display = 'block';
  heatmapEl.style.height  = '';

  const probes = [...new Set(attack.map(r => r._label))].sort();

  // Compute cell data: [colIdx, rowIdx, leakedCount]
  const cellData = [];
  let maxVal = 0;

  // Also need total-per-cell for the k/n label
  const cellTotals = {};
  const cellLeaked = {};

  for (const r of attack) {
    const colIdx = _HEATMAP_COLS.findIndex(c => {
      const defenseMatch = r.defense === c.defense;
      const guardMatch   = (r.guard_on === true ? 'on' : 'off') === c.guard;
      return defenseMatch && guardMatch;
    });
    if (colIdx < 0) continue;
    const rowIdx = probes.indexOf(r._label);
    if (rowIdx < 0) continue;
    const key = `${colIdx},${rowIdx}`;
    cellTotals[key] = (cellTotals[key] || 0) + 1;
    if (r.verdict === 'leaked') {
      cellLeaked[key] = (cellLeaked[key] || 0) + 1;
      maxVal = Math.max(maxVal, cellLeaked[key]);
    }
  }

  for (let ci = 0; ci < _HEATMAP_COLS.length; ci++) {
    for (let ri = 0; ri < probes.length; ri++) {
      const key   = `${ci},${ri}`;
      const total = cellTotals[key] || 0;
      const leaked = cellLeaked[key] || 0;
      cellData.push({
        value:  [ci, ri, total === 0 ? null : leaked],
        label_: total === 0 ? '–' : `${leaked}/${total}`,
        total,
        leaked,
        colIdx: ci,
        rowIdx: ri,
      });
    }
  }

  const height = Math.max(200, probes.length * 34 + 60);
  heatmapEl.style.height = height + 'px';

  const chart = _getOrInitChart('chart-heatmap');
  if (!chart) return;
  chart.resize();

  chart.setOption({
    backgroundColor: _BG_TRANSPARENT,
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const d = p.data;
        if (!d) return '';
        const col = _HEATMAP_COLS[d.value[0]];
        const probe = probes[d.value[1]];
        const total = d.total;
        if (total === 0) return `${probe} / ${col.label}<br/>No trials`;
        return `${probe} / ${col.label}<br/>leaked: ${d.leaked}/${total}`;
      },
      backgroundColor: '#161B22',
      borderColor: _AXIS_LINE_COLOR,
      textStyle: { color: _TEXT_COLOR },
    },
    grid: { left: 8, right: 8, top: 4, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      position: 'top',
      data: _HEATMAP_COLS.map(c => c.label.replace('instructional', 'instruct.').replace('datamarking', 'datamark').replace('·', ' · Guard ')),
      axisLabel: { color: _TEXT_COLOR, fontSize: 10, interval: 0 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: probes.map(_shortProbe),
      inverse: true,
      axisLabel: { color: _TEXT_COLOR, fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    visualMap: {
      show: false,
      min: 0,
      max: Math.max(maxVal, 1),
      inRange: { color: ['#1A2433', VERDICT_COLORS.leaked] },
    },
    series: [{
      name: 'Leaks',
      type: 'heatmap',
      data: cellData.map(d => ({
        value: d.value,
        // null values get gray styling via itemStyle
        itemStyle: d.total === 0 ? { color: '#161B22', borderColor: '#0D1117', borderWidth: 2 } : { borderColor: '#0D1117', borderWidth: 2 },
        label: { show: true, formatter: () => d.label_, color: _TEXT_COLOR, fontSize: 11 },
      })),
      label: { show: true },
      emphasis: { itemStyle: { shadowBlur: 16, shadowColor: VERDICT_COLORS.leaked } },
    }],
  }, { notMerge: true });

  // Click a cell → filter by probe, defense, guard
  chart.off('click');
  chart.on('click', (params) => {
    if (!params.data) return;
    const ci    = params.data.value[0];
    const ri    = params.data.value[1];
    const col   = _HEATMAP_COLS[ci];
    const probe = probes[ri];
    if (col === undefined || probe === undefined) return;
    setFilter('probe', probe);
    setFilter('defense', col.defense);
    setFilter('guard', col.guard);
    const explorer = document.querySelector('.card:has(#trial-table)');
    if (explorer) explorer.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}


/* -------------------------------------------------------------------------
 * #chart-donuts — attack outcomes, Guard off vs Guard on (part-to-whole)
 * ------------------------------------------------------------------------- */

function _renderDonuts(recs) {
  const chart = _getOrInitChart('chart-donuts');
  if (!chart) return;
  const attack = recs.filter(r => r.kind === 'attack' && !r._isControl);
  const sides = [
    { name: 'Guard off', recs: attack.filter(r => !r.guard_on), center: '25%' },
    { name: 'Guard on',  recs: attack.filter(r => r.guard_on),  center: '75%' },
  ];
  const verdicts = Object.keys(VERDICT_COLORS).filter(v => attack.some(r => r.verdict === v));

  const series = sides.map(side => {
    const n = side.recs.length;
    const leaked = side.recs.filter(r => r.verdict === 'leaked').length;
    const main = n === 0 ? '–' : `${Math.round((leaked / n) * 100)}%`;
    return {
      name: side.name,
      type: 'pie',
      radius: ['58%', '78%'],
      center: [side.center, '52%'],
      padAngle: 3,
      itemStyle: { borderRadius: 4 },
      avoidLabelOverlap: true,
      label: {
        show: true, position: 'center',
        formatter: () => `{v|${main}}\n{s|leaked}\n{t|${side.name} · ${leaked}/${n}}`,
        rich: {
          v: { fontSize: 22, fontWeight: 700, color: leaked > 0 ? VERDICT_COLORS.leaked : VERDICT_COLORS.refused,
               textShadowBlur: 12, textShadowColor: leaked > 0 ? VERDICT_COLORS.leaked : VERDICT_COLORS.refused },
          s: { fontSize: 10, color: '#8B949E', padding: [2, 0, 4, 0] },
          t: { fontSize: 10, color: _TEXT_COLOR },
        },
      },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 4, label: { show: true } },
      data: verdicts.map(v => ({
        name: v,
        value: side.recs.filter(r => r.verdict === v).length,
        itemStyle: { color: VERDICT_COLORS[v], shadowBlur: 18, shadowColor: VERDICT_COLORS[v] },
      })).filter(d => d.value > 0),
    };
  });

  chart.setOption({
    backgroundColor: _BG_TRANSPARENT,
    tooltip: { ..._TOOLTIP_STYLE, formatter: (p) => `${p.seriesName}<br/>${p.marker}${p.name}: ${p.value} (${p.percent}%)` },
    legend: { data: verdicts, bottom: 0, textStyle: { color: _TEXT_COLOR, fontSize: 11 }, itemWidth: 10, itemHeight: 10, icon: 'circle' },
    series,
  }, { notMerge: true });
}

/* -------------------------------------------------------------------------
 * renderCharts — public entry point, called from app.js renderAll()
 * ------------------------------------------------------------------------- */

function renderCharts() {
  const recs = filtered();
  _renderDumbbell(recs);
  _renderDonuts(recs);
  _renderVerdicts(recs);
  _renderHeatmap(recs);
}

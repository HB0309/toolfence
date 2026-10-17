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
  const rowSet = new Set();
  for (const r of attack) {
    rowSet.add(multiModel ? `${r._label} / ${r._model}` : r._label);
  }
  const rows = [...rowSet].sort();

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
  const labels  = rows.map((row, i) => {
    const s = stats[i];
    return s.isControl ? row + ' (control)' : row;
  });

  const MUTED = '#6E7681';
  const COLOR_OFF = '#D55E00';
  const COLOR_ON  = '#56B4E9';

  // Build connecting line series (one per row)
  const lineSeries = rows.map((_, i) => ({
    type: 'line',
    data: [[offData[i], i], [onData[i], i]],
    coordinateSystem: 'cartesian2d',
    lineStyle: { color: stats[i].isControl ? MUTED : _TEXT_COLOR, width: 1, type: 'solid' },
    symbol: 'none',
    silent: true,
    z: 1,
  }));

  const scatterOff = {
    name: 'Guard off',
    type: 'scatter',
    symbolSize: 10,
    itemStyle: { color: (params) => stats[params.dataIndex].isControl ? MUTED : COLOR_OFF },
    data: rows.map((_, i) => ({
      value: [offData[i], i],
      label: {
        show: true,
        position: 'insideLeft',
        formatter: () => {
          const s = stats[i].off;
          return s.n === 0 ? '' : `${s.k}/${s.n}`;
        },
        color: _TEXT_COLOR,
        fontSize: 11,
        distance: 8,
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
    symbolSize: 10,
    itemStyle: { color: (params) => stats[params.dataIndex].isControl ? MUTED : COLOR_ON },
    data: rows.map((_, i) => ({
      value: [onData[i], i],
      label: {
        show: true,
        position: 'insideRight',
        formatter: () => {
          const s = stats[i].on;
          return s.n === 0 ? '' : `${s.k}/${s.n}`;
        },
        color: _TEXT_COLOR,
        fontSize: 11,
        distance: 8,
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

  const height = Math.max(300, rows.length * 36 + 80);
  chart.getDom().style.height = height + 'px';
  chart.resize();

  chart.setOption({
    backgroundColor: _BG_TRANSPARENT,
    tooltip: _TOOLTIP_STYLE,
    legend: { data: ['Guard off', 'Guard on'], textStyle: { color: _TEXT_COLOR }, top: 4 },
    grid: { left: '3%', right: '6%', top: 36, bottom: 30, containLabel: true },
    xAxis: { type: 'value', min: 0, max: 100, name: 'Leak rate %',
      nameTextStyle: { color: _TEXT_COLOR }, ..._AXIS_STYLE },
    yAxis: { type: 'category', data: labels, inverse: false,
      axisLabel: { color: (v, i) => stats[i] && stats[i].isControl ? MUTED : _TEXT_COLOR, fontSize: 12 },
      ..._AXIS_STYLE },
    series: [...lineSeries, scatterOff, scatterOn],
  }, true);
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
  rowKeys.sort();

  const verdicts = Object.keys(VERDICT_COLORS);
  const series = verdicts.map(v => ({
    name: v,
    type: 'bar',
    stack: 'total',
    barMaxWidth: 28,
    itemStyle: { color: VERDICT_COLORS[v] },
    label: {
      show: true,
      formatter: (p) => p.value > 0 ? String(p.value) : '',
      color: '#fff',
      fontSize: 11,
    },
    data: rowKeys.map(key => rowMap[key].filter(r => r.verdict === v).length),
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const n = rowMap[rowKeys[p.dataIndex]].length;
        return `${rowKeys[p.dataIndex]}<br/>${v}: ${p.value}/${n}`;
      },
      ...Object.fromEntries(Object.entries(_TOOLTIP_STYLE).filter(([k]) => k !== 'trigger')),
    },
  }));

  const height = Math.max(300, rowKeys.length * 32 + 80);
  chart.getDom().style.height = height + 'px';
  chart.resize();

  chart.setOption({
    backgroundColor: _BG_TRANSPARENT,
    tooltip: { ..._TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: verdicts, textStyle: { color: _TEXT_COLOR }, top: 4 },
    grid: { left: '3%', right: '6%', top: 36, bottom: 30, containLabel: true },
    xAxis: { type: 'value', ..._AXIS_STYLE },
    yAxis: { type: 'category', data: rowKeys, inverse: false, ..._AXIS_STYLE },
    series,
  }, true);
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

  const height = Math.max(280, probes.length * 38 + 100);
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
    grid: { left: '3%', right: '120px', top: 20, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: _HEATMAP_COLS.map(c => c.label),
      axisLabel: { rotate: 30, color: _TEXT_COLOR, fontSize: 11 },
      axisLine: { lineStyle: { color: _AXIS_LINE_COLOR } },
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      data: probes,
      axisLabel: { color: _TEXT_COLOR, fontSize: 12 },
      axisLine: { lineStyle: { color: _AXIS_LINE_COLOR } },
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: Math.max(maxVal, 1),
      calculable: false,
      orient: 'vertical',
      right: 0,
      top: 'center',
      inRange: { color: ['#1F2A37', '#D55E00'] },
      textStyle: { color: _TEXT_COLOR },
    },
    series: [{
      name: 'Leaks',
      type: 'heatmap',
      data: cellData.map(d => ({
        value: d.value,
        // null values get gray styling via itemStyle
        itemStyle: d.total === 0 ? { color: '#2D333B' } : {},
        label: { show: true, formatter: () => d.label_, color: _TEXT_COLOR, fontSize: 11 },
      })),
      label: { show: true },
      emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.5)' } },
    }],
  }, true);

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
 * renderCharts — public entry point, called from app.js renderAll()
 * ------------------------------------------------------------------------- */

function renderCharts() {
  const recs = filtered();
  _renderDumbbell(recs);
  _renderVerdicts(recs);
  _renderHeatmap(recs);
}

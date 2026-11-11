/* Admin dashboard charts (Chart.js) fed by /admin/api/charts */
(function () {
  const C = { maroon: '#7B1E2B', saffron: '#E8772E', gold: '#D4A017', leaf: '#2F7D32', teal: '#0F6B63', plum: '#6A2A7B', blue: '#1E4FA0', rose: '#C2185B' };
  const PALETTE = [C.saffron, C.maroon, C.gold, C.leaf, C.teal, C.plum, C.blue, C.rose, '#8D6E63', '#F7B733'];
  const cur = window.CURRENCY || '$';
  const money = v => cur + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  Chart.defaults.font.family = "Mukta, system-ui, sans-serif";
  Chart.defaults.color = '#8A6E5A';
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  const charts = {};
  let data = null, trend = 'daily';

  function make(id, cfg) {
    charts[id]?.destroy();
    charts[id] = new Chart(document.getElementById(id), cfg);
  }

  function gradient(ctx) {
    const g = ctx.createLinearGradient(0, 0, 0, 320);
    g.addColorStop(0, 'rgba(232,119,46,.35)'); g.addColorStop(1, 'rgba(232,119,46,0)');
    return g;
  }

  function drawTrend() {
    const t = data[trend];
    const ctx = document.getElementById('trendChart').getContext('2d');
    const datasets = [{
      type: trend === 'daily' ? 'line' : 'bar', label: 'Revenue', data: t.revenue, yAxisID: 'y',
      borderColor: C.saffron, backgroundColor: trend === 'daily' ? gradient(ctx) : C.saffron,
      fill: true, tension: .35, pointRadius: t.labels.length > 40 ? 0 : 3, borderRadius: 6, maxBarThickness: 46,
    }];
    if (t.orders) datasets.push({ type: 'line', label: 'Orders', data: t.orders, yAxisID: 'y1', borderColor: C.maroon, backgroundColor: C.maroon, tension: .35, pointRadius: 0, borderWidth: 2, borderDash: [5, 4] });
    make('trendChart', {
      data: { labels: t.labels, datasets },
      options: {
        maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { tooltip: { callbacks: { label: c => c.dataset.label === 'Revenue' ? ` Revenue ${money(c.raw)}` : ` Orders ${c.raw}` } } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: money }, grid: { color: '#F1E6D4' } },
          y1: { display: !!t.orders, position: 'right', beginAtZero: true, grid: { display: false } },
          x: { grid: { display: false }, ticks: { maxTicksLimit: 12 } },
        },
      },
    });
  }

  function hbar(id, rows, color) {
    make(id, {
      type: 'bar',
      data: { labels: rows.map(r => r.name), datasets: [{ label: 'Units sold', data: rows.map(r => r.qty), backgroundColor: color, borderRadius: 6, maxBarThickness: 22 }] },
      options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false },
        tooltip: { callbacks: { afterLabel: c => `Revenue ${money(rows[c.dataIndex].revenue)}` } } },
        scales: { x: { grid: { color: '#F1E6D4' } }, y: { grid: { display: false } } } },
    });
  }

  function doughnut(id, labels, values, fmt) {
    make(id, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: PALETTE, borderColor: '#fff', borderWidth: 3, hoverOffset: 8 }] },
      options: { maintainAspectRatio: false, cutout: '62%', plugins: { legend: { position: 'right' },
        tooltip: { callbacks: { label: c => ` ${c.label}: ${fmt(c.raw)}` } } } },
    });
  }

  function render() {
    const r = data.range;
    document.getElementById('rangeSummary').innerHTML =
      `<span><b>${money(r.revenue)}</b> revenue</span><span><b>${r.orders}</b> orders</span>` +
      `<span><b>${r.orders ? money(r.revenue / r.orders) : money(0)}</b> avg order</span>`;
    drawTrend();
    hbar('sweetsChart', data.best_sweets, C.saffron);
    hbar('foodChart', data.best_food, C.maroon);
    doughnut('categoryChart', data.categories.labels, data.categories.revenue, money);
    doughnut('paymentChart', data.payment_methods.labels, data.payment_methods.orders, v => `${v} orders`);
  }

  async function load(params) {
    const res = await fetch(`${window.CHART_URL}?${new URLSearchParams(params)}`, { headers: { Accept: 'application/json' } });
    data = await res.json();
    render();
  }

  const form = document.getElementById('rangeForm');
  form.addEventListener('submit', e => { e.preventDefault(); load(new FormData(form)); });
  form.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => {
    const end = new Date(form.end.value || Date.now());
    const start = new Date(end); start.setDate(end.getDate() - parseInt(b.dataset.days, 10) + 1);
    form.start.value = start.toISOString().slice(0, 10);
    load(new FormData(form));
  }));
  document.querySelectorAll('#trendTabs [data-trend]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#trendTabs button').forEach(x => x.classList.toggle('active', x === b));
    trend = b.dataset.trend; drawTrend();
  }));
  load(new FormData(form));
})();

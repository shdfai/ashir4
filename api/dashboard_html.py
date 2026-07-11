"""
Dashboard HTML — kept as a Python string constant for simple single-file serving.
Uses Chart.js (CDN) for the equity curve. Polls WebSocket for live data,
REST endpoints for history/metrics on tab switch.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XT Trading Bot — Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.3/chart.umd.min.js"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0a0e1a; color:#e0e6f0; font-family:'Inter',-apple-system,sans-serif; }
  .header { background:#0d1528; padding:14px 24px; border-bottom:1px solid #1e3a5f; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; }
  .header h1 { font-size:1.3rem; color:#00d4ff; display:flex; align-items:center; gap:8px;}
  .badges { display:flex; gap:8px; align-items:center; }
  .badge { padding:4px 12px; border-radius:20px; font-size:0.72rem; font-weight:600; border:1px solid; }
  .badge-live { background:#0d3320; color:#00ff88; border-color:#00ff88; }
  .badge-halted { background:#3d0d0d; color:#ff4444; border-color:#ff4444; }
  .badge-mode-paper { background:#1a1a3d; color:#a0a0ff; border-color:#a0a0ff; }
  .badge-mode-live { background:#3d2a0d; color:#ffaa00; border-color:#ffaa00; }
  .tabs { display:flex; gap:4px; padding:0 24px; background:#0d1528; border-bottom:1px solid #1e3a5f; overflow-x:auto; }
  .tab { padding:12px 18px; cursor:pointer; color:#607b96; font-size:0.85rem; font-weight:600; border-bottom:2px solid transparent; white-space:nowrap; }
  .tab.active { color:#00d4ff; border-bottom-color:#00d4ff; }
  .content { padding:24px; }
  .tab-content { display:none; }
  .tab-content.active { display:block; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin-bottom:20px; }
  .card { background:#0d1528; border:1px solid #1e3a5f; border-radius:12px; padding:18px; }
  .card-title { font-size:0.68rem; color:#607b96; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }
  .card-value { font-size:1.6rem; font-weight:700; color:#00d4ff; }
  .card-sub { font-size:0.75rem; color:#607b96; margin-top:4px; }
  .positive { color:#00ff88 !important; }
  .negative { color:#ff4444 !important; }
  .chart-card { background:#0d1528; border:1px solid #1e3a5f; border-radius:12px; padding:20px; margin-bottom:20px; }
  .chart-card h3 { font-size:0.9rem; color:#00d4ff; margin-bottom:14px; }
  table { width:100%; border-collapse:collapse; background:#0d1528; border-radius:12px; overflow:hidden; }
  th { background:#0a0e1a; padding:10px 14px; text-align:left; font-size:0.68rem; color:#607b96; text-transform:uppercase; position:sticky; top:0; }
  td { padding:10px 14px; border-top:1px solid #1e3a5f; font-size:0.82rem; }
  tr:hover { background:#101a30; }
  .table-wrap { max-height:500px; overflow-y:auto; border-radius:12px; }
  .controls { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
  button { padding:9px 18px; border:none; border-radius:8px; cursor:pointer; font-size:0.82rem; font-weight:600; transition:.2s; }
  .btn-halt { background:#3d0d0d; color:#ff4444; border:1px solid #ff4444; }
  .btn-resume { background:#0d3320; color:#00ff88; border:1px solid #00ff88; }
  button:hover { opacity:.8; transform:translateY(-1px); }
  .pulse { animation:pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
  .empty { text-align:center; color:#607b96; padding:30px; }
  .dir-long { color:#00ff88; }
  .dir-short { color:#ff4444; }
  select { background:#0d1528; color:#e0e6f0; border:1px solid #1e3a5f; padding:6px 12px; border-radius:6px; font-size:0.8rem; }
</style>
</head>
<body>

<div class="header">
  <h1>⚡ XT Trading Bot</h1>
  <div class="badges">
    <span id="mode-badge" class="badge badge-mode-paper">PAPER</span>
    <span id="status-badge" class="badge badge-live pulse">● CONNECTING</span>
  </div>
</div>

<div class="tabs">
  <div class="tab active" data-tab="overview">Overview</div>
  <div class="tab" data-tab="positions">Positions</div>
  <div class="tab" data-tab="history">Trade History</div>
  <div class="tab" data-tab="metrics">Performance</div>
  <div class="tab" data-tab="events">System Log</div>
</div>

<div class="content">

  <!-- OVERVIEW -->
  <div class="tab-content active" id="tab-overview">
    <div class="grid">
      <div class="card"><div class="card-title">Free Balance</div><div class="card-value" id="ov-balance">--</div><div class="card-sub">USDT</div></div>
      <div class="card"><div class="card-title">Equity</div><div class="card-value" id="ov-equity">--</div><div class="card-sub">Balance + Unrealized PnL</div></div>
      <div class="card"><div class="card-title">Daily PnL</div><div class="card-value" id="ov-pnl">--</div><div class="card-sub">Today</div></div>
      <div class="card"><div class="card-title">Open Positions</div><div class="card-value" id="ov-pos">--</div><div class="card-sub">Active</div></div>
      <div class="card"><div class="card-title">Win Rate</div><div class="card-value" id="ov-winrate">--</div><div class="card-sub">Today</div></div>
      <div class="card"><div class="card-title">Daily Trades</div><div class="card-value" id="ov-trades">--</div><div class="card-sub">Executed</div></div>
    </div>

    <div class="controls">
      <button class="btn-halt" onclick="haltTrading()">🛑 Halt Trading</button>
      <button class="btn-resume" onclick="resumeTrading()">✅ Resume Trading</button>
    </div>

    <div class="chart-card">
      <h3>📈 Equity Curve</h3>
      <canvas id="equityChart" height="80"></canvas>
    </div>
  </div>

  <!-- POSITIONS -->
  <div class="tab-content" id="tab-positions">
    <div class="table-wrap">
      <table>
        <thead><tr><th>Symbol</th><th>Direction</th><th>Entry</th><th>Current</th><th>Leverage</th><th>PnL</th></tr></thead>
        <tbody id="positions-body"><tr><td colspan="6" class="empty">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- HISTORY -->
  <div class="tab-content" id="tab-history">
    <div class="table-wrap">
      <table>
        <thead><tr><th>Symbol</th><th>Dir</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th><th>Closed</th></tr></thead>
        <tbody id="history-body"><tr><td colspan="7" class="empty">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- METRICS -->
  <div class="tab-content" id="tab-metrics">
    <div class="controls">
      <select id="metrics-period" onchange="loadMetrics()">
        <option value="7">Last 7 days</option>
        <option value="30" selected>Last 30 days</option>
        <option value="90">Last 90 days</option>
        <option value="365">Last year</option>
      </select>
    </div>
    <div class="grid">
      <div class="card"><div class="card-title">Total Trades</div><div class="card-value" id="m-total">--</div></div>
      <div class="card"><div class="card-title">Win Rate</div><div class="card-value" id="m-winrate">--</div></div>
      <div class="card"><div class="card-title">Total PnL</div><div class="card-value" id="m-pnl">--</div></div>
      <div class="card"><div class="card-title">Profit Factor</div><div class="card-value" id="m-pf">--</div></div>
      <div class="card"><div class="card-title">Sharpe Ratio</div><div class="card-value" id="m-sharpe">--</div></div>
      <div class="card"><div class="card-title">Max Drawdown</div><div class="card-value" id="m-dd">--</div></div>
      <div class="card"><div class="card-title">Avg Win</div><div class="card-value positive" id="m-avgwin">--</div></div>
      <div class="card"><div class="card-title">Avg Loss</div><div class="card-value negative" id="m-avgloss">--</div></div>
      <div class="card"><div class="card-title">Best Trade</div><div class="card-value positive" id="m-best">--</div></div>
      <div class="card"><div class="card-title">Worst Trade</div><div class="card-value negative" id="m-worst">--</div></div>
      <div class="card"><div class="card-title">Wins / Losses</div><div class="card-value" id="m-wl">--</div></div>
    </div>
  </div>

  <!-- EVENTS -->
  <div class="tab-content" id="tab-events">
    <div class="table-wrap">
      <table>
        <thead><tr><th>Type</th><th>Message</th><th>Time</th></tr></thead>
        <tbody id="events-body"><tr><td colspan="3" class="empty">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

</div>

<script>
  // ─── Tabs ──────────────────────────────────────────────
  document.querySelectorAll('.tab').forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
      if (tab.dataset.tab === 'history') loadHistory();
      if (tab.dataset.tab === 'metrics') loadMetrics();
      if (tab.dataset.tab === 'events') loadEvents();
    };
  });

  // ─── WebSocket live updates ──────────────────────────────
  const ws = new WebSocket(`ws://${location.host}/ws`);
  let equityChart;

  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.error || d.status === 'offline') return;

    const bal = d.balance?.USDT || 0;
    const total = d.balance?.total || 0;
    document.getElementById('ov-balance').textContent = '$' + bal.toFixed(2);

    const stats = d.stats || {};
    document.getElementById('ov-pos').textContent = stats.open_positions || 0;
    document.getElementById('ov-winrate').textContent = (stats.win_rate || 0) + '%';
    document.getElementById('ov-trades').textContent = stats.daily_trades || 0;

    const pnl = stats.daily_pnl || 0;
    const pnlEl = document.getElementById('ov-pnl');
    pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
    pnlEl.className = 'card-value ' + (pnl >= 0 ? 'positive' : 'negative');

    const positions = d.positions || [];
    const unrealized = positions.reduce((s,p) => s + (p.unrealizedPnl||0), 0);
    document.getElementById('ov-equity').textContent = '$' + (total + unrealized).toFixed(2);

    // Mode badge
    const modeBadge = document.getElementById('mode-badge');
    modeBadge.textContent = (d.mode || 'paper').toUpperCase();
    modeBadge.className = 'badge ' + (d.mode === 'live' ? 'badge-mode-live' : 'badge-mode-paper');

    // Status badge
    const statusBadge = document.getElementById('status-badge');
    if (stats.trading_halted) {
      statusBadge.textContent = '● HALTED';
      statusBadge.className = 'badge badge-halted';
    } else {
      statusBadge.textContent = '● LIVE';
      statusBadge.className = 'badge badge-live pulse';
    }

    renderPositions(positions);
  };

  function renderPositions(positions) {
    const tbody = document.getElementById('positions-body');
    if (!positions.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No open positions</td></tr>';
      return;
    }
    tbody.innerHTML = positions.map(p => {
      const pnl = p.unrealizedPnl || 0;
      const isLong = (p.contracts || 0) > 0;
      return `<tr>
        <td>${p.symbol}</td>
        <td class="${isLong ? 'dir-long' : 'dir-short'}">${isLong ? '🟢 LONG' : '🔴 SHORT'}</td>
        <td>${(p.entryPrice||0).toFixed(4)}</td>
        <td>${(p.markPrice||0).toFixed(4)}</td>
        <td>${p.leverage || '-'}x</td>
        <td class="${pnl>=0?'positive':'negative'}">${pnl>=0?'+':''}$${pnl.toFixed(2)}</td>
      </tr>`;
    }).join('');
  }

  async function haltTrading() {
    if (confirm('Halt all trading?')) await fetch('/api/halt', {method:'POST'});
  }
  async function resumeTrading() {
    await fetch('/api/resume', {method:'POST'});
  }

  // ─── History tab ─────────────────────────────────────────
  async function loadHistory() {
    const res = await fetch('/api/history?limit=200');
    const trades = await res.json();
    const tbody = document.getElementById('history-body');
    if (!trades.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">No closed trades yet</td></tr>';
      return;
    }
    tbody.innerHTML = trades.map(t => {
      const pnl = t.pnl_usdt || 0;
      const dirClass = t.direction === 'long' ? 'dir-long' : 'dir-short';
      const closedAt = t.closed_at ? new Date(t.closed_at).toLocaleString() : '-';
      return `<tr>
        <td>${t.symbol}</td>
        <td class="${dirClass}">${t.direction}</td>
        <td>${(t.entry_price||0).toFixed(4)}</td>
        <td>${(t.exit_price||0).toFixed(4)}</td>
        <td class="${pnl>=0?'positive':'negative'}">${pnl>=0?'+':''}$${pnl.toFixed(2)}</td>
        <td>${t.exit_reason||'-'}</td>
        <td>${closedAt}</td>
      </tr>`;
    }).join('');
  }

  // ─── Metrics tab ─────────────────────────────────────────
  async function loadMetrics() {
    const days = document.getElementById('metrics-period').value;
    const res = await fetch(`/api/metrics?days=${days}`);
    const m = await res.json();

    document.getElementById('m-total').textContent = m.total_trades;
    document.getElementById('m-winrate').textContent = m.win_rate + '%';

    const pnlEl = document.getElementById('m-pnl');
    pnlEl.textContent = (m.total_pnl_usdt>=0?'+':'') + '$' + m.total_pnl_usdt;
    pnlEl.className = 'card-value ' + (m.total_pnl_usdt>=0?'positive':'negative');

    document.getElementById('m-pf').textContent = m.profit_factor ?? '∞';
    document.getElementById('m-sharpe').textContent = m.sharpe_ratio;
    document.getElementById('m-dd').textContent = '$' + m.max_drawdown_usdt + ' (' + m.max_drawdown_pct + '%)';
    document.getElementById('m-avgwin').textContent = '$' + m.avg_win_usdt;
    document.getElementById('m-avgloss').textContent = '$' + m.avg_loss_usdt;
    document.getElementById('m-best').textContent = '$' + m.best_trade_usdt;
    document.getElementById('m-worst').textContent = '$' + m.worst_trade_usdt;
    document.getElementById('m-wl').textContent = `${m.wins} / ${m.losses}`;
  }

  // ─── Events tab ──────────────────────────────────────────
  async function loadEvents() {
    const res = await fetch('/api/events?limit=50');
    const events = await res.json();
    const tbody = document.getElementById('events-body');
    if (!events.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty">No events yet</td></tr>';
      return;
    }
    tbody.innerHTML = events.map(ev => `<tr>
      <td>${ev.event_type}</td>
      <td>${ev.message || ''}</td>
      <td>${ev.timestamp ? new Date(ev.timestamp).toLocaleString() : '-'}</td>
    </tr>`).join('');
  }

  // ─── Equity Curve Chart ──────────────────────────────────
  async function loadEquityCurve() {
    const res = await fetch('/api/equity-curve?limit=500');
    const data = await res.json();
    const labels = data.map(d => new Date(d.timestamp).toLocaleString());
    const equity = data.map(d => d.equity_usdt);

    const ctx = document.getElementById('equityChart').getContext('2d');
    if (equityChart) equityChart.destroy();
    equityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Equity (USDT)',
          data: equity,
          borderColor: '#00d4ff',
          backgroundColor: 'rgba(0,212,255,0.08)',
          fill: true,
          tension: 0.2,
          pointRadius: 0,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#607b96', maxTicksLimit: 8 }, grid: { color: '#1e3a5f' } },
          y: { ticks: { color: '#607b96' }, grid: { color: '#1e3a5f' } },
        }
      }
    });
  }

  loadEquityCurve();
  setInterval(loadEquityCurve, 60000); // refresh chart every minute
</script>

</body>
</html>"""

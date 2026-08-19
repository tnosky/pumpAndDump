const socket = typeof io === 'function' ? io() : null;

function money(value) {
  return `$${Number(value).toFixed(2)}`;
}

function price(value) {
  return `$${Number(value).toFixed(3)}`;
}

function signed(value, digits = 2) {
  const n = Number(value);
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function stockClass(value) {
  return Number(value) >= 0 ? 'pos' : 'neg';
}

function updateTicker(stocks) {
  const bar = document.getElementById('tickerbar');
  if (!bar) return;
  bar.innerHTML = stocks.map(s =>
    `<a href="/stock/${s.ticker}">${s.ticker} ${price(s.price)} <span class="${stockClass(s.change)}">${signed(s.change)}</span></a>`
  ).join('');
}

function updateMarketTable(stocks) {
  const body = document.querySelector('#market-table tbody');
  if (!body) return;
  body.innerHTML = stocks.map(s => `
    <tr>
      <td><a href="/stock/${s.ticker}">${s.ticker}</a></td>
      <td>${s.name}</td>
      <td data-stock-price="${s.ticker}">${price(s.price)}</td>
      <td class="${stockClass(s.change)}">${signed(s.change)}</td>
      <td>${money(s.market_cap)}</td>
      <td>${s.available}</td>
    </tr>
  `).join('');
}

function updateRecentTrades(trades, targetId = 'recent-trades-body') {
  const body = document.getElementById(targetId);
  if (!body) return;
  if (!trades.length) {
    body.innerHTML = '<tr><td colspan="6">no trades yet</td></tr>';
    return;
  }
  body.innerHTML = trades.map(t => `
    <tr>
      <td>${t.user}</td>
      <td class="${t.side === 'BUY' ? 'pos' : 'neg'}">${t.side}</td>
      <td>${t.shares}</td>
      <td><a href="/stock/${t.ticker}">${t.ticker}</a></td>
      <td>${price(t.price)}</td>
      <td>${money(t.total)}</td>
    </tr>
  `).join('');
}

function updateStockTrades(trades) {
  const body = document.getElementById('stock-trades-body');
  if (!body) return;
  if (!trades.length) {
    body.innerHTML = '<tr><td colspan="4">no trades yet</td></tr>';
    return;
  }
  body.innerHTML = trades.map(t => `
    <tr><td>${t.user}</td><td class="${t.side === 'BUY' ? 'pos' : 'neg'}">${t.side}</td><td>${t.shares}</td><td>${price(t.price)}</td></tr>
  `).join('');
}

function updateLeaderboard(rows, targetId = 'leaderboard-body') {
  const body = document.getElementById(targetId);
  if (!body) return;
  body.innerHTML = rows.map((u, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><a href="/user/${encodeURIComponent(u.username)}">${u.username}</a></td>
      <td>${money(u.net_worth)}</td>
      <td>${money(u.cash)}</td>
      <td>${money(u.invested)}</td>
      <td>${signed(u.return_pct)}</td>
      <td class="${stockClass(u.realized)}">${money(u.realized)}</td>
      <td class="${stockClass(u.unrealized)}">${money(u.unrealized)}</td>
      <td>${u.trades}</td>
    </tr>
  `).join('');
}

function updateAccount(account) {
  if (!account) return;
  document.querySelectorAll('[data-live-account="net_worth"]').forEach(el => el.textContent = money(account.net_worth));
  document.querySelectorAll('[data-live-account="cash"]').forEach(el => el.textContent = money(account.cash));
  document.querySelectorAll('[data-live-account="invested"]').forEach(el => el.textContent = money(account.invested));
  document.querySelectorAll('[data-live-account="return_pct"]').forEach(el => el.textContent = signed(account.return_pct));

  const body = document.querySelector('#portfolio-holdings tbody');
  if (body && account.holdings) {
    body.innerHTML = account.holdings.length ? account.holdings.map(h => `
      <tr><td><a href="/stock/${h.ticker}">${h.ticker}</a></td><td>${h.shares}</td><td>${price(h.avg_cost)}</td><td>${price(h.price)}</td><td>${money(h.value)}</td><td>${Number(h.allocation || 0).toFixed(1)}%</td><td class="${stockClass(h.unrealized)}">${money(h.unrealized)}</td></tr>
    `).join('') : '<tr><td colspan="7">no holdings</td></tr>';
  }
}

let nextMarketChange = null;

function updateMarketStatus(open, label, nextChange) {
  nextMarketChange = nextChange || null;
  document.querySelectorAll('[data-market-status]').forEach(el => {
    el.textContent = label || (open ? 'OPEN' : 'CLOSED');
    el.classList.toggle('pos', open);
    el.classList.toggle('neg', !open);
  });
  updateCountdown();
}

function updateCountdown() {
  const el = document.querySelector('[data-market-countdown]');
  if (!el) return;
  if (!nextMarketChange) {
    el.textContent = '';
    return;
  }
  const ms = new Date(nextMarketChange).getTime() - Date.now();
  if (ms <= 0) {
    el.textContent = 'updating...';
    return;
  }
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  el.textContent = `(${hours}h ${String(minutes).padStart(2, '0')}m ${String(seconds).padStart(2, '0')}s)`;
}

function updateStockPage(payload) {
  const stockTicker = document.body.dataset.stockTicker;
  if (!stockTicker) return;
  const data = payload.stocks.find(s => s.ticker === stockTicker);
  if (!data) return;

  document.querySelectorAll('[data-live-stock="price"]').forEach(el => el.textContent = price(data.price));
  document.querySelectorAll('[data-live-stock="change"]').forEach(el => {
    el.textContent = signed(data.change);
    el.classList.toggle('pos', data.change >= 0);
    el.classList.toggle('neg', data.change < 0);
  });
  document.querySelectorAll('[data-live-stock="market_cap"]').forEach(el => el.textContent = money(data.market_cap));
  document.querySelectorAll('[data-live-stock="volume"]').forEach(el => el.textContent = data.volume);
  document.querySelectorAll('[data-live-stock="high"]').forEach(el => el.textContent = price(data.high));
  document.querySelectorAll('[data-live-stock="low"]').forEach(el => el.textContent = price(data.low));
  document.querySelectorAll('[data-live-stock="available"]').forEach(el => el.textContent = data.available);
  document.querySelectorAll('[data-live-stock="holder_count"]').forEach(el => el.textContent = data.holder_count);
  document.querySelectorAll('[data-live-stock="held"]').forEach(el => el.textContent = data.held);
  document.querySelectorAll('[data-live-stock="trades"]').forEach(el => el.textContent = data.trades);
  document.querySelectorAll('[data-live-stock="avg_trade_price"]').forEach(el => el.textContent = price(data.avg_trade_price));
  document.querySelectorAll('[data-live-stock="volatility"]').forEach(el => el.textContent = `${Number(data.volatility).toFixed(2)}%`);
  document.querySelectorAll('[data-live-stock="buy_shares"]').forEach(el => el.textContent = data.buy_shares);
  document.querySelectorAll('[data-live-stock="sell_shares"]').forEach(el => el.textContent = data.sell_shares);
  document.querySelectorAll('[data-live-stock="largest_holder"]').forEach(el => el.textContent = data.largest_holder ? `${data.largest_holder} (${data.largest_holder_shares})` : 'none');

  const trades = payload.recent_trades.filter(t => t.ticker === stockTicker).slice(0, 30);
  updateStockTrades(trades);

  if (window.addChartPoint && payload.price_point && payload.price_point.ticker === stockTicker) {
    window.addChartPoint(payload.price_point);
  }
}

function estimateTrade(ticker, side, shares) {
  const stock = (window.liveMarketStocks || []).find(s => s.ticker === ticker);
  if (!stock || !shares) return null;
  const start = Number(stock.price);
  const step = Number(window.priceStep || 0.0003);
  let total = 0;
  for (let i = 0; i < shares; i++) {
    total += side === 'BUY' ? start + step * i : Math.max(0.001, start - step * (i + 1));
  }
  return { total, average: total / shares, finalPrice: side === 'BUY' ? start + step * shares : Math.max(0.001, start - step * shares) };
}

function showTradeModal(form) {
  const ticker = form.querySelector('[name="ticker"]').value;
  const side = form.querySelector('[name="side"]').value;
  const input = form.querySelector('[name="shares"]');
  const shares = Number(input.value);
  if (!Number.isInteger(shares) || shares < 1 || shares > 50) {
    showNotice('enter a whole number from 1 to 50 shares.', 'error');
    return;
  }
  const estimate = estimateTrade(ticker, side, shares);
  if (!estimate) {
    showNotice('could not calculate the trade estimate.', 'error');
    return;
  }

  const modal = document.getElementById('trade-modal');
  modal.querySelector('[data-trade-title]').textContent = `${side === 'BUY' ? 'buy' : 'sell'} ${shares} ${ticker}`;
  modal.querySelector('[data-trade-detail]').textContent = side === 'BUY'
    ? `estimated cost: ${money(estimate.total)} | avg: ${price(estimate.average)} | new market price: ${price(estimate.finalPrice)}`
    : `estimated proceeds: ${money(estimate.total)} | avg: ${price(estimate.average)} | new market price: ${price(estimate.finalPrice)}`;
  modal.querySelector('[data-trade-confirm]').textContent = side === 'BUY' ? 'confirm buy' : 'confirm sell';
  modal.classList.add('show');
  modal._form = form;
}

function closeTradeModal() {
  const modal = document.getElementById('trade-modal');
  if (modal) modal.classList.remove('show');
}

function showNotice(text, type = 'success') {
  const box = document.getElementById('trade-notice');
  if (!box) return;
  box.textContent = text;
  box.className = `trade-notice ${type}`;
  box.classList.add('show');
  clearTimeout(window.tradeNoticeTimer);
  window.tradeNoticeTimer = setTimeout(() => box.classList.remove('show'), 5000);
}

function setupTradeForms() {
  document.querySelectorAll('.trade-form').forEach(form => {
    form.addEventListener('submit', event => {
      event.preventDefault();
      showTradeModal(form);
    });
  });

  const modal = document.getElementById('trade-modal');
  if (!modal) return;
  modal.querySelector('[data-trade-cancel]').addEventListener('click', closeTradeModal);
  modal.querySelector('[data-trade-confirm]').addEventListener('click', async () => {
    const form = modal._form;
    if (!form) return;
    const confirmButton = modal.querySelector('[data-trade-confirm]');
    confirmButton.disabled = true;
    confirmButton.textContent = 'processing...';
    closeTradeModal();
    const response = await fetch(form.action, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      body: new FormData(form),
    });
    const data = await response.json().catch(() => ({ ok: false, error: 'trade request failed' }));
    confirmButton.disabled = false;
    confirmButton.textContent = form.querySelector('[name="side"]')?.value === 'BUY' ? 'confirm buy' : 'confirm sell';
    if (!data.ok) {
      showNotice(data.error || 'trade failed.', 'error');
      return;
    }
    applyLiveUpdate(data.market);
    const t = data.trade;
    const label = t.side === 'BUY' ? 'bought' : 'sold';
    const moneyLabel = t.side === 'BUY' ? 'cost' : 'proceeds';
    showNotice(`${label} ${t.shares} ${t.ticker} | ${moneyLabel}: ${money(t.total)} | avg: ${price(t.price)} | market: ${price(t.market_price)}`, 'success');
  });
}

if (socket) {
  socket.on('connect', () => {
    fetch('/api/market').then(r => r.json()).then(applyLiveUpdate).catch(() => {});
  });
  socket.on('market_update', applyLiveUpdate);
}

function applyLiveUpdate(payload) {
  window.liveMarketStocks = payload.stocks || [];
  updateTicker(payload.stocks || []);
  updateMarketStatus(!!payload.market_open, payload.market_label, payload.next_change);
  updateMarketTable(payload.stocks || []);
  updateRecentTrades(payload.recent_trades || []);
  updateLeaderboard(payload.leaderboard || []);
  updateAccount(payload.account);
  updateStockPage(payload);
}

function refreshMarketStatus() {
  fetch('/api/market').then(r => r.json()).then(applyLiveUpdate).catch(() => {});
}

window.priceStep = Number(document.body.dataset.priceStep || 0.0003);
setupTradeForms();
refreshMarketStatus();
setInterval(refreshMarketStatus, 10000);
setInterval(updateCountdown, 1000);

function setupSortableTables() {
  document.querySelectorAll('.sortable-table th').forEach((th, index) => {
    let asc = true;
    th.addEventListener('click', () => {
      const table = th.closest('table');
      const rows = [...table.tBodies[0].rows];
      rows.sort((a, b) => {
        const av = a.cells[index].innerText.replace(/[$,%+]/g, '');
        const bv = b.cells[index].innerText.replace(/[$,%+]/g, '');
        const an = Number(av);
        const bn = Number(bv);
        if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * (asc ? 1 : -1);
        return av.localeCompare(bv) * (asc ? 1 : -1);
      });
      rows.forEach(row => table.tBodies[0].appendChild(row));
      asc = !asc;
    });
  });
}
setupSortableTables();

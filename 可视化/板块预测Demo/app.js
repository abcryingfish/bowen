const fallbackSectors = [
  ['半导体','881001',4.8,2.9,5.6,11.8,18.6,'strong','科技','#4b8e9c'], ['机器人','885728',3.9,2.4,4.8,9.7,15.1,'strong','重点','#cf8b37'], ['人工智能','885982',3.5,2.0,4.2,8.4,12.8,'fund','科技','#7d70a7'], ['新能源','881005',2.7,1.8,3.5,6.1,10.2,'fund','资金','#5c9b70'], ['军工','881006',2.1,1.2,2.7,4.6,7.9,'watch','观察','#6e86a9'], ['医药生物', '881008',1.8,1.0,2.1,3.8,5.4,'watch','观察','#67a58f'], ['消费电子','885901',2.6,1.5,3.1,5.2,8.6,'strong','科技','#c27b57'], ['通信设备','881009',1.6,.8,2.4,3.2,6.5,'fund','资金','#5a8eb7'], ['软件服务','881010',2.9,1.7,3.8,7.6,11.2,'strong','科技','#8873aa'], ['电力设备','881011',1.1,.6,1.5,2.1,4.1,'watch','观察','#6b9a73'], ['有色金属','881012',-0.8,-1.1,.3,-2.7,1.5,'watch','观察','#a98247'], ['煤炭','881013',-1.4,-.8,-.2,-3.4,-.9,'watch','观察','#74716a'], ['食品饮料','881014',.7,.3,1.1,1.6,3.3,'fund','资金','#b47b52'], ['家用电器','881015',.4,.2,.8,1.2,2.5,'fund','资金','#a89952'], ['银行','881016',-.2,.1,.5,.9,1.7,'watch','观察','#6b8b78'], ['非银金融','881017',-.5,-.2,.4,-1.1,2.2,'watch','观察','#7885a1'], ['房地产','881018',-1.7,-1.2,-.5,-4.8,-5.6,'watch','观察','#b66b61'], ['汽车整车','881019',1.2,.8,1.9,3.4,5.7,'fund','资金','#bd7e4d'], ['公用事业','881020',.2,.1,.7,.8,2.1,'fund','资金','#5e917e'], ['传媒','885644',2.2,1.3,2.9,4.9,9.3,'strong','科技','#a56c9a']
];
const trend = (seed, rising) => Array.from({length:20},(_,i)=> Math.max(18, 48 + Math.sin(i*.72+seed)*5 + (rising ? i*1.55 : -i*.55) + Math.cos(i*.2+seed)*2));
const funds = (seed, share) => Array.from({length:18},(_,i)=> Math.max(16, 42 + Math.sin(i*.58+seed)*6 + i*(share > 6 ? .9 : .2)));
const path = values => { const min=Math.min(...values), max=Math.max(...values), range=max-min||1; return values.map((v,i)=>`${(i/(values.length-1)*100).toFixed(1)},${(38-(v-min)/range*30).toFixed(1)}`).join(' '); };
const cls = value => value > .35 ? 'up' : value < -.35 ? 'down' : 'flat';
const fmt = value => Number.isFinite(Number(value)) ? `${value >= 0 ? '+' : ''}${Number(value).toFixed(1)}%` : '--';
const probFmt = value => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : '--';
// 5日高波概率的全历史 P20/P40/P60/P80（2019-01-02 ~ 2026-08-24）。
// 运行时只做分档比较，不扫描历史概率文件。
const FIVE_DAY_VOLATILITY_QUANTILES = { p20: 8.2729, p40: 9.3286, p60: 10.1469, p80: 10.9593 };
const volatilityLabel = value => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '波动未知';
  const q = FIVE_DAY_VOLATILITY_QUANTILES;
  if (n <= q.p20) return '极端低波动';
  if (n <= q.p40) return '低波动';
  if (n <= q.p60) return '中波动';
  if (n <= q.p80) return '高波动';
  return '极端高波动';
};
const probabilityStyle = direction => direction === '看涨' ? 'color:#c95749' : direction === '看跌' ? 'color:#4b966f' : 'color:#aa8323';
const forecastCell = (value, isLive, direction, volatility) => {
  if (!isLive) return `<div class="metric metric-single"><span>5日方向概率</span><strong class="${cls(value)}">${fmt(value)}</strong></div>`;
  return `<div class="metric metric-single"><span>5日${direction} · ${volatility}</span><strong class="probability-value" style="${probabilityStyle(direction)}">${probFmt(value)}</strong></div>`;
};
function spark(values, mode='candles') {
  if (mode === 'line') {
    const series = (Array.isArray(values) ? values : []).map(item => item && typeof item === 'object' ? Number(item.close) : Number(item)).filter(Number.isFinite);
    if (series.length < 2) return '<div class="chart-empty">暂无资金数据</div>';
    const min=Math.min(...series); const max=Math.max(...series); const range=max-min||1;
    const points=series.map((value,index)=>`${(index/(series.length-1)*100).toFixed(2)},${(55-(value-min)/range*45).toFixed(2)}`).join(' ');
    return `<svg class="sparkline fund-sparkline" viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true"><polyline class="fund-curve" points="${points}"></polyline></svg>`;
  }
  const raw = (Array.isArray(values) ? values : []).map((item, index) => {
    if (item && typeof item === 'object') return { open:Number(item.open), high:Number(item.high), low:Number(item.low), close:Number(item.close) };
    const close = Number(item); const previous = Number(values[index - 1]); const open = Number.isFinite(previous) ? previous : close;
    const spread = Math.max(Math.abs(close - open) * 0.35, Math.abs(close) * 0.002);
    return { open, high:Math.max(open, close) + spread, low:Math.min(open, close) - spread, close };
  }).filter(item => [item.open,item.high,item.low,item.close].every(Number.isFinite));
  if (raw.length < 2) return '<div class="chart-empty">暂无走势</div>';
  const min = Math.min(...raw.map(item => item.low)); const max = Math.max(...raw.map(item => item.high)); const range = max - min || 1;
  const y = value => 55 - ((value - min) / range) * 45; const step = 100 / raw.length; const bodyWidth = Math.max(1.1, Math.min(4.5, step * 0.58));
  const candles = raw.map((item,index) => { const x = index * step + step / 2; const openY = y(item.open); const closeY = y(item.close); const bodyY = Math.min(openY, closeY); const bodyH = Math.max(1.4, Math.abs(closeY - openY)); const direction = item.close >= item.open ? 'up' : 'down'; return `<g class="candle ${direction}"><line class="candle-wick" x1="${x.toFixed(2)}" y1="${y(item.high).toFixed(2)}" x2="${x.toFixed(2)}" y2="${y(item.low).toFixed(2)}"></line><rect class="candle-body" x="${(x-bodyWidth/2).toFixed(2)}" y="${bodyY.toFixed(2)}" width="${bodyWidth.toFixed(2)}" height="${bodyH.toFixed(2)}"></rect></g>`; }).join('');
  return `<svg class="sparkline" viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true">${candles}</svg>`;
}
function card(item, index) { const [name,code,d3,d5,d20,change20,share,filter,tag,color,liveValues,liveFunds,isLive,direction,volatility]=item; const values=Array.isArray(liveValues) && liveValues.length > 1 ? liveValues : trend(index+1,Number(change20)>=0), f=Array.isArray(liveFunds) && liveFunds.length > 1 ? liveFunds : funds(index+3,Number(share)); const shareLabel=Number.isFinite(Number(share)) ? `${Number(share).toFixed(3)}%` : '--'; return `<article class="sector-card" data-filter="${filter}" style="--accent:${color}"><div class="card-head"><div><h2 class="sector-name">${name}</h2></div><span class="rank">NO.${String(index+1).padStart(2,'0')}</span></div><div class="chart-block"><div class="chart-label"><span>最近20日走势</span><strong>${fmt(change20)}</strong></div>${spark(values)}</div><div class="chart-block fund-chart"><div class="chart-label"><span>资金占比曲线</span><strong>${shareLabel}</strong></div>${spark(f,'line')}</div><div class="metrics">${forecastCell(d5, isLive, direction, volatility)}</div></article>`; }
const grid = document.querySelector('#sector-grid');
function render(items) { grid.innerHTML = items.map(card).join(''); }
render(fallbackSectors);

function apiJson(url) {
  const joiner = url.includes('?') ? '&' : '?';
  return fetch(`${url}${joiner}_refresh=${Date.now()}`, { cache: 'no-store' }).then(response => {
    if (!response.ok) throw new Error(`接口请求失败：${response.status}`);
    return response.json();
  });
}

async function mapWithLimit(items, limit, worker) {
  const output = new Array(items.length); let cursor = 0;
  const run = async () => { while (cursor < items.length) { const index = cursor++; output[index] = await worker(items[index], index); } };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
  return output;
}

async function loadRealSectors() {
  try {
    const [codesPayload, modelPayload, fundPayload] = await Promise.all([
      apiJson('http://127.0.0.1:8000/api/market/index-codes'),
      apiJson('http://127.0.0.1:8000/api/market/sector-model-signals?prefix=881'),
      apiJson('http://127.0.0.1:8000/api/market/sector-fund-shares?prefix=881&limit=80')
    ]);
    const codes = (codesPayload.items || []).filter(item => String(item.code || '').startsWith('881'));
    const models = new Map((modelPayload.items || modelPayload.data?.items || []).map(item => [String(item.htsc_code).toUpperCase(), item]));
    const fundMap = new Map();
    (fundPayload.points || []).forEach(point => { const key=String(point.sector_code || '').toUpperCase(); if (!fundMap.has(key)) fundMap.set(key, []); fundMap.get(key).push(Number(point.fund_share_pct)); });
    const colors = ['#4b8e9c','#cf8b37','#7d70a7','#5c9b70','#6e86a9','#67a58f','#c27b57','#5a8eb7','#8873aa','#6b9a73'];
    const live = await mapWithLimit(codes, 6, async (item, index) => {
      const key=String(item.code).toUpperCase(); const barsPayload=await apiJson(`http://127.0.0.1:8000/api/market/index/bars?code=${encodeURIComponent(item.code)}&limit=80`);
      const bars=(barsPayload.bars || []).filter(bar => Number(bar.close)>0); const closes=bars.map(bar=>Number(bar.close));
      const change = (n) => closes.length > n ? (closes[closes.length-1] / closes[closes.length-1-n] - 1) * 100 : null;
      const model=models.get(key) || {}; const probability=(field) => Number.isFinite(Number(model[field])) ? Number(model[field])*100 : null;
      const sumProbabilities = (...fields) => { const values=fields.map(probability); return values.every(Number.isFinite) ? values.reduce((sum, value) => sum + value, 0) : null; };
      const bullish = sumProbabilities('5d_prob_valley_bullish', '5d_prob_sideways_bullish');
      const bearish = sumProbabilities('5d_prob_peak_bearish', '5d_prob_sideways_bearish');
      const highVolatility = probability('5d_prob_two_sided_high_volatility');
      const denominator = Number.isFinite(bullish) && Number.isFinite(bearish) ? bullish + bearish : null;
      const direction = Number.isFinite(bullish) && Number.isFinite(bearish) ? (bullish > bearish ? '看涨' : '看跌') : '方向未知';
      const directionProbability = Number.isFinite(denominator) && denominator > 0 ? Math.max(bullish, bearish) / denominator * 100 : null;
      const volatility = volatilityLabel(highVolatility);
      const fundValues=fundMap.get(key) || []; const share=fundValues.length ? fundValues[fundValues.length-1] : null;
      const candles = bars.slice(-20).map(bar => ({ open:Number(bar.open), high:Number(bar.high), low:Number(bar.low), close:Number(bar.close) }));
      return [item.name || item.code, item.code, probability('ultra_short_prob_valley_bullish'), directionProbability, probability('20d_prob_valley_bullish'), change(20), share, 'all', '881行业', colors[index % colors.length], candles, fundValues.slice(-18), true, direction, volatility];
    });
    // 先按方向分组：看涨在前，看跌在后；看跌组反向排列以保留最看跌在末尾。
    live.sort((left, right) => {
      const directionRank = value => value === '看涨' ? 0 : value === '看跌' ? 1 : 2;
      const groupDiff = directionRank(left[13]) - directionRank(right[13]);
      if (groupDiff !== 0) return groupDiff;
      const leftProbability = Number.isFinite(Number(left[3])) ? Number(left[3]) : -1;
      const rightProbability = Number.isFinite(Number(right[3])) ? Number(right[3]) : -1;
      // 看涨组强者优先；看跌组弱者优先，最看跌的自然落在最后。
      return left[13] === '看跌'
        ? leftProbability - rightProbability
        : rightProbability - leftProbability;
    });
    render(live);
    document.querySelector('.asof strong').textContent = `881行业实时数据 · ${live.length}个`;
    document.querySelector('.filter[data-filter="all"]').textContent = `全部 ${live.length} 行业`;
  } catch (error) {
    document.querySelector('.asof small').textContent = '接口未连接，当前为参考样式';
    console.warn('881 行业数据加载失败，使用参考样式：', error);
  }
}
loadRealSectors();

function scheduleDailyRefresh() {
  const now = new Date();
  const next = new Date(now);
  next.setHours(24, 0, 5, 0);
  window.setTimeout(() => { void loadRealSectors(); scheduleDailyRefresh(); }, Math.max(1000, next.getTime() - now.getTime()));
}
scheduleDailyRefresh();

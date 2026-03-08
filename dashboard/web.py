"""
Web Dashboard for Daily News Agent
Serves a modern HTML dashboard with live stats, recent stories,
and manual trigger controls.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📰 Daily News Agent</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        
        /* Header */
        .header {
            text-align: center;
            padding: 30px 0;
        }
        .header h1 {
            font-size: 2.2em;
            background: linear-gradient(90deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }
        .header .subtitle {
            color: #888;
            font-size: 0.95em;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(76, 175, 80, 0.15);
            border: 1px solid rgba(76, 175, 80, 0.3);
            padding: 6px 16px;
            border-radius: 20px;
            margin-top: 12px;
            font-size: 0.85em;
            color: #4CAF50;
        }
        .status-dot {
            width: 8px; height: 8px;
            background: #4CAF50;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin: 24px 0;
        }
        .stat-card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            transition: transform 0.2s, border-color 0.2s;
        }
        .stat-card:hover {
            transform: translateY(-2px);
            border-color: rgba(102, 126, 234, 0.4);
        }
        .stat-value {
            font-size: 2em;
            font-weight: 700;
            background: linear-gradient(90deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .stat-label { font-size: 0.8em; color: #888; margin-top: 4px; }

        /* Actions */
        .actions {
            display: flex;
            gap: 12px;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        .btn {
            padding: 10px 24px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            font-weight: 500;
            font-size: 0.9em;
            transition: all 0.2s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }
        .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 15px rgba(102,126,234,0.4); }
        .btn-secondary {
            background: rgba(255,255,255,0.08);
            color: #e0e0e0;
            border: 1px solid rgba(255,255,255,0.15);
        }
        .btn-secondary:hover { background: rgba(255,255,255,0.12); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }

        /* Schedule */
        .schedule {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin: 20px 0;
        }
        .schedule-item {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 14px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .schedule-icon { font-size: 1.3em; }
        .schedule-time { font-weight: 600; font-size: 0.9em; }
        .schedule-desc { font-size: 0.75em; color: #888; }

        /* Claims Table */
        .section-title {
            font-size: 1.2em;
            font-weight: 600;
            margin: 30px 0 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .claims-list { display: flex; flex-direction: column; gap: 10px; }
        .claim-card {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 16px;
            transition: border-color 0.2s;
        }
        .claim-card:hover { border-color: rgba(102, 126, 234, 0.3); }
        .claim-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            gap: 12px;
        }
        .claim-title {
            font-weight: 500;
            font-size: 0.95em;
            flex: 1;
        }
        .claim-title a { color: #b0b0ff; text-decoration: none; }
        .claim-title a:hover { text-decoration: underline; }
        .claim-meta {
            display: flex;
            gap: 8px;
            margin-top: 8px;
            flex-wrap: wrap;
        }
        .tag {
            font-size: 0.7em;
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 500;
        }
        .tag-cat { background: rgba(102,126,234,0.2); color: #a0b4ff; }
        .tag-conf-high { background: rgba(76,175,80,0.2); color: #81C784; }
        .tag-conf-med { background: rgba(255,193,7,0.2); color: #FFD54F; }
        .tag-conf-low { background: rgba(244,67,54,0.2); color: #E57373; }
        .tag-ticker { background: rgba(255,255,255,0.1); color: #ccc; }

        /* Sentiment */
        .sentiment-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 16px 0;
        }
        .sentiment-card {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 12px;
            text-align: center;
        }
        .sentiment-ticker { font-weight: 600; font-size: 1em; }
        .sentiment-bar {
            height: 6px;
            border-radius: 3px;
            background: rgba(255,255,255,0.1);
            margin: 8px 0;
            overflow: hidden;
        }
        .sentiment-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s;
        }
        .sentiment-positive { background: linear-gradient(90deg, #4CAF50, #81C784); }
        .sentiment-negative { background: linear-gradient(90deg, #f44336, #e57373); }
        .sentiment-neutral { background: linear-gradient(90deg, #FFB74D, #FFF176); }
        .sentiment-count { font-size: 0.75em; color: #888; }

        /* Toast */
        .toast {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(76,175,80,0.9);
            color: white;
            padding: 12px 24px;
            border-radius: 10px;
            font-size: 0.9em;
            opacity: 0;
            transform: translateY(20px);
            transition: all 0.3s;
            z-index: 100;
        }
        .toast.show { opacity: 1; transform: translateY(0); }
        .toast.error { background: rgba(244,67,54,0.9); }

        /* Responsive */
        @media (max-width: 600px) {
            .header h1 { font-size: 1.6em; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📰 Daily News Agent</h1>
            <div class="subtitle">AI-Powered News Intelligence</div>
            <div class="status-badge">
                <div class="status-dot"></div>
                <span id="status-text">Connecting...</span>
            </div>
        </div>

        <div class="stats-grid" id="stats-grid">
            <div class="stat-card"><div class="stat-value" id="stat-total">—</div><div class="stat-label">Articles Today</div></div>
            <div class="stat-card"><div class="stat-value" id="stat-verified">—</div><div class="stat-label">Verified (≥80%)</div></div>
            <div class="stat-card"><div class="stat-value" id="stat-categories">—</div><div class="stat-label">Categories</div></div>
            <div class="stat-card"><div class="stat-value" id="stat-week">—</div><div class="stat-label">This Week</div></div>
        </div>

        <div class="actions">
            <button class="btn btn-primary" id="btn-trigger" onclick="triggerFetch()">⚡ Trigger Fetch Now</button>
            <button class="btn btn-secondary" onclick="loadData()">🔄 Refresh</button>
            <button class="btn btn-secondary" onclick="loadSentiment()">📊 Sentiment</button>
        </div>

        <div class="schedule">
            <div class="schedule-item"><span class="schedule-icon">⏱</span><div><div class="schedule-time" id="next-fetch">—</div><div class="schedule-desc">Next Fetch</div></div></div>
            <div class="schedule-item"><span class="schedule-icon">📰</span><div><div class="schedule-time">8:00 AM IST</div><div class="schedule-desc">Morning Brief</div></div></div>
            <div class="schedule-item"><span class="schedule-icon">📊</span><div><div class="schedule-time">10:00 PM IST</div><div class="schedule-desc">Evening Recap</div></div></div>
            <div class="schedule-item"><span class="schedule-icon">📅</span><div><div class="schedule-time">Sun 9:00 AM</div><div class="schedule-desc">Weekly Summary</div></div></div>
        </div>

        <div id="sentiment-section" style="display:none;">
            <div class="section-title">📈 Ticker Sentiment (7 days)</div>
            <div class="sentiment-grid" id="sentiment-grid"></div>
        </div>

        <div class="section-title">📰 Recent Stories</div>
        <div class="claims-list" id="claims-list">
            <div style="text-align:center; color:#666; padding:30px;">Loading stories...</div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        async function loadData() {
            try {
                const [statusRes, claimsRes] = await Promise.all([
                    fetch('/status'), fetch('/claims?hours=24&limit=15')
                ]);
                const status = await statusRes.json();
                const claims = await claimsRes.json();

                document.getElementById('status-text').textContent = 'Online';
                document.getElementById('stat-total').textContent = status.today.total_articles;
                document.getElementById('stat-verified').textContent = status.today.verified;
                document.getElementById('stat-categories').textContent = status.today.categories.filter(c => c).length;

                // Next fetch
                const fetchJob = status.scheduled_jobs.find(j => j.id === 'fetch_and_verify');
                if (fetchJob && fetchJob.next_run) {
                    const d = new Date(fetchJob.next_run);
                    document.getElementById('next-fetch').textContent = d.toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit'});
                }

                // Week count
                try {
                    const weekRes = await fetch('/claims?hours=168&limit=999');
                    const week = await weekRes.json();
                    document.getElementById('stat-week').textContent = week.total;
                } catch (e) { document.getElementById('stat-week').textContent = '—'; }

                // Claims
                const list = document.getElementById('claims-list');
                if (claims.claims.length === 0) {
                    list.innerHTML = '<div style="text-align:center;color:#666;padding:30px;">No stories yet. Fetch will run soon!</div>';
                    return;
                }
                list.innerHTML = claims.claims.map(c => {
                    const conf = c.confidence || 0;
                    const confClass = conf >= 80 ? 'tag-conf-high' : conf >= 50 ? 'tag-conf-med' : 'tag-conf-low';
                    const confIcon = conf >= 80 ? '🟢' : conf >= 50 ? '🟡' : '🔴';
                    const tickers = (c.tickers || []);
                    const tickerTags = (typeof tickers === 'string' ? JSON.parse(tickers || '[]') : tickers)
                        .slice(0, 3).map(t => '<span class="tag tag-ticker">'+t+'</span>').join('');
                    return '<div class="claim-card"><div class="claim-header"><div class="claim-title">' +
                        (c.url ? '<a href="'+c.url+'" target="_blank">'+c.title+'</a>' : c.title) +
                        '</div></div><div class="claim-meta">' +
                        '<span class="tag tag-cat">'+(c.category||'')+'</span>' +
                        '<span class="tag '+confClass+'">'+confIcon+' '+conf+'%</span>' +
                        tickerTags +
                        '<span class="tag" style="color:#666">'+(c.source||'')+'</span>' +
                        '</div></div>';
                }).join('');

            } catch (e) {
                document.getElementById('status-text').textContent = 'Offline';
                console.error(e);
            }
        }

        async function triggerFetch() {
            const btn = document.getElementById('btn-trigger');
            btn.disabled = true;
            btn.textContent = '⏳ Fetching...';
            try {
                const res = await fetch('/trigger', { method: 'POST' });
                if (res.ok) { showToast('✅ Fetch triggered!'); loadData(); }
                else showToast('❌ Trigger failed', true);
            } catch (e) { showToast('❌ ' + e.message, true); }
            btn.disabled = false;
            btn.textContent = '⚡ Trigger Fetch Now';
        }

        async function loadSentiment() {
            try {
                const res = await fetch('/sentiment');
                const data = await res.json();
                const section = document.getElementById('sentiment-section');
                const grid = document.getElementById('sentiment-grid');
                
                if (data.tickers && data.tickers.length > 0) {
                    section.style.display = 'block';
                    grid.innerHTML = data.tickers.map(t => {
                        const total = t.positive + t.negative + t.neutral;
                        const posPct = total > 0 ? Math.round((t.positive / total) * 100) : 0;
                        const negPct = total > 0 ? Math.round((t.negative / total) * 100) : 0;
                        const cls = posPct > 60 ? 'sentiment-positive' : negPct > 40 ? 'sentiment-negative' : 'sentiment-neutral';
                        return '<div class="sentiment-card">' +
                            '<div class="sentiment-ticker">' + t.ticker + '</div>' +
                            '<div class="sentiment-bar"><div class="sentiment-fill ' + cls + '" style="width:' + Math.max(posPct, 5) + '%"></div></div>' +
                            '<div class="sentiment-count">' + total + ' mentions | ' + posPct + '% positive</div></div>';
                    }).join('');
                } else {
                    section.style.display = 'block';
                    grid.innerHTML = '<div style="color:#666;padding:20px;text-align:center;">No ticker data yet. Check back after a few fetch cycles.</div>';
                }
            } catch (e) { showToast('❌ Sentiment load failed', true); }
        }

        function showToast(msg, isError = false) {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'toast show' + (isError ? ' error' : '');
            setTimeout(() => t.className = 'toast', 3000);
        }

        loadData();
        setInterval(loadData, 60000);
    </script>
</body>
</html>"""

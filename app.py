"""
STElliot Web — 엘리어트 파동 자동 분석기 웹 UI
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
import io
import sys
import traceback

from elliott import analyze

app = FastAPI(title="STElliot", description="엘리어트 파동 자동 분석기")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STElliot — 엘리어트 파동 분석기</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            padding: 24px 32px;
            border-bottom: 1px solid #333;
        }
        .header h1 { font-size: 28px; color: #00d4ff; letter-spacing: 2px; }
        .header p { color: #888; margin-top: 4px; font-size: 14px; }
        .container { max-width: 900px; margin: 0 auto; padding: 24px; }
        .input-section {
            background: #111;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .input-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
        .input-group { display: flex; flex-direction: column; gap: 4px; }
        .input-group label { font-size: 12px; color: #888; text-transform: uppercase; }
        .input-group input, .input-group select {
            background: #1a1a1a;
            border: 1px solid #444;
            color: #fff;
            padding: 10px 14px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 15px;
        }
        .input-group input:focus, .input-group select:focus {
            outline: none; border-color: #00d4ff;
        }
        .input-group input { width: 280px; }
        .btn {
            background: #00d4ff;
            color: #000;
            border: none;
            padding: 10px 24px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 15px;
            font-weight: bold;
            cursor: pointer;
            letter-spacing: 1px;
        }
        .btn:hover { background: #00b8d9; }
        .btn:disabled { background: #444; color: #888; cursor: not-allowed; }
        .presets { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
        .preset-btn {
            background: #1a1a2e;
            color: #00d4ff;
            border: 1px solid #333;
            padding: 6px 14px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            cursor: pointer;
        }
        .preset-btn:hover { background: #16213e; border-color: #00d4ff; }
        .result {
            background: #0d0d0d;
            border: 1px solid #222;
            border-radius: 8px;
            padding: 20px;
            white-space: pre-wrap;
            font-size: 13px;
            line-height: 1.6;
            min-height: 200px;
            overflow-x: auto;
        }
        .result-colored {
            background: #0d0d0d;
            border: 1px solid #222;
            border-radius: 8px;
            padding: 20px;
            font-size: 13px;
            line-height: 1.6;
            min-height: 200px;
            overflow-x: auto;
            white-space: pre-wrap;
            font-family: 'Courier New', monospace;
        }
        .result-colored .line-buy { color: #51cf66; font-weight: bold; }
        .result-colored .line-sell { color: #ff6b6b; font-weight: bold; }
        .result-colored .line-warn { color: #ffd43b; }
        .result-colored .line-info { color: #00d4ff; }
        .result-colored .line-header { color: #00d4ff; font-weight: bold; }
        .result-colored .line-bar { color: #4dabf7; }
        .loading {
            display: none;
            color: #00d4ff;
            padding: 40px;
            text-align: center;
            font-size: 16px;
        }
        .loading.active { display: block; }
        .footer {
            text-align: center;
            padding: 20px;
            color: #444;
            font-size: 12px;
        }
        .footer a { color: #00d4ff; text-decoration: none; }
    </style>
</head>
<body>
    <div class="header">
        <h1>STElliot</h1>
        <p>TradingView 실시간 데이터 기반 엘리어트 파동 자동 분석기</p>
    </div>
    <div class="container">
        <div class="input-section">
            <div class="input-row">
                <div class="input-group">
                    <label>종목 심볼</label>
                    <input type="text" id="symbol" placeholder="005930 또는 BINANCE:BTCUSDT" value="005930">
                </div>
                <div class="input-group">
                    <label>타임프레임</label>
                    <select id="timeframe">
                        <option value="15">15분봉</option>
                        <option value="60" selected>1시간봉</option>
                        <option value="240">4시간봉</option>
                        <option value="D">일봉</option>
                    </select>
                </div>
                <button class="btn" id="analyzeBtn" onclick="runAnalysis()">ANALYZE</button>
            </div>
            <div class="presets">
                <button class="preset-btn" onclick="setSymbol('005930')">삼성전자</button>
                <button class="preset-btn" onclick="setSymbol('000660')">SK하이닉스</button>
                <button class="preset-btn" onclick="setSymbol('005380')">현대차</button>
                <button class="preset-btn" onclick="setSymbol('KOSPI')">코스피</button>
                <button class="preset-btn" onclick="setSymbol('COINBASE:BTCUSD')">BTC</button>
            </div>
        </div>
        <div class="loading" id="loading">분석 중... TradingView 데이터 수집 + 파동 분석 (최대 30초 소요)</div>
        <div class="result" id="result">종목 심볼을 입력하고 ANALYZE 버튼을 누르세요.

한국 주식: 종목코드 6자리 (예: 005930, 000660, 005380)
한국 지수: KOSPI, KOSDAQ
암호화폐:  BINANCE:BTCUSDT</div>
    </div>
    <div class="footer">
        <a href="https://github.com/Terry-Gabia/STElliot" target="_blank">GitHub</a> |
        Powered by TradingView Data + Elliott Wave Theory
    </div>
    <script>
        function escapeHtml(text) {
            return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }
        function colorize(text) {
            return escapeHtml(text).split('\\n').map(line => {
                if (line.includes('매수 추천') || line.includes('💰'))
                    return '<span class="line-buy">' + line + '</span>';
                if (line.includes('★★') && (line.includes('적극') || line.includes('지금')))
                    return '<span class="line-buy">' + line + '</span>';
                if (line.includes('★ 지금 매수') || line.includes('★★ 적극'))
                    return '<span class="line-buy">' + line + '</span>';
                if (line.includes('1차 매수') || line.includes('2차 매수') || line.includes('3차 매수'))
                    return '<span class="line-buy">' + line + '</span>';
                if (line.includes('손절'))
                    return '<span class="line-sell">' + line + '</span>';
                if (line.includes('⚠️') || line.includes('비추천'))
                    return '<span class="line-warn">' + line + '</span>';
                if (line.includes('━') || line.includes('═'))
                    return '<span class="line-header">' + line + '</span>';
                if (line.includes('종합 판단') || line.includes('가격 레벨') || line.includes('📊') || line.includes('💰'))
                    return '<span class="line-info">' + line + '</span>';
                if (line.includes('█'))
                    return '<span class="line-bar">' + line + '</span>';
                if (line.includes('◀◀◀'))
                    return '<span class="line-buy">' + line + '</span>';
                return line;
            }).join('\\n');
        }
        function setSymbol(sym) {
            document.getElementById('symbol').value = sym;
        }
        async function runAnalysis() {
            const symbol = document.getElementById('symbol').value.trim();
            const tf = document.getElementById('timeframe').value;
            if (!symbol) return;

            const btn = document.getElementById('analyzeBtn');
            const loading = document.getElementById('loading');
            const result = document.getElementById('result');

            btn.disabled = true;
            loading.classList.add('active');
            result.style.display = 'none';

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 60000);

                const resp = await fetch(
                    `/api/analyze?symbol=${encodeURIComponent(symbol)}&tf=${tf}`,
                    { signal: controller.signal }
                );
                clearTimeout(timeoutId);
                const data = await resp.json();

                if (data.error) {
                    result.className = 'result';
                    result.textContent = '오류: ' + data.error;
                } else {
                    result.className = 'result-colored';
                    result.innerHTML = colorize(data.result);
                }
                result.style.display = 'block';
            } catch (e) {
                if (e.name === 'AbortError') {
                    result.textContent = '시간 초과: 서버에서 데이터 수집에 실패했습니다.\\n다시 시도해 주세요.';
                } else {
                    result.textContent = '오류 발생: ' + e.message;
                }
                result.style.display = 'block';
            } finally {
                btn.disabled = false;
                loading.classList.remove('active');
            }
        }
        document.getElementById('symbol').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') runAnalysis();
        });
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_TEMPLATE


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "STElliot"}


def run_analysis_sync(symbol, tf):
    """동기 분석 실행 (stdout 캡처)"""
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        analyze(symbol, timeframe=tf, n_bars=500)
    except Exception as e:
        print(f"분석 오류: {e}")
        traceback.print_exc()
    output = buffer.getvalue()
    sys.stdout = old_stdout
    return output


@app.get("/api/analyze")
async def api_analyze(symbol: str = "005930", tf: str = "60"):
    try:
        loop = asyncio.get_event_loop()
        output = await asyncio.wait_for(
            loop.run_in_executor(None, run_analysis_sync, symbol, tf),
            timeout=45
        )

        if not output or "데이터 수집 실패" in output:
            return JSONResponse({
                "symbol": symbol,
                "timeframe": tf,
                "result": output or "데이터 수집 실패: TradingView 서버에 연결할 수 없습니다.",
                "error": "data_fetch_failed"
            })

        return JSONResponse({"symbol": symbol, "timeframe": tf, "result": output})

    except asyncio.TimeoutError:
        return JSONResponse({
            "symbol": symbol,
            "timeframe": tf,
            "result": "",
            "error": "분석 시간 초과 (45초). TradingView 서버 연결 문제일 수 있습니다."
        })
    except Exception as e:
        return JSONResponse({
            "symbol": symbol,
            "timeframe": tf,
            "result": "",
            "error": str(e)
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

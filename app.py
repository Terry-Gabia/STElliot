"""
STElliot Web — 엘리어트 파동 자동 분석기 웹 UI (Google SSO)
"""

import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from jose import jwt
from datetime import datetime, timedelta, timezone
import asyncio
import io
import sys
import traceback

from elliott import analyze

# ── Config ──────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "stelliot-change-this-secret")
ALLOWED_EMAILS = [
    e.strip() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()
]

# ── App ─────────────────────────────────────────────────
app = FastAPI(title="STElliot", description="엘리어트 파동 자동 분석기")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# ── OAuth ───────────────────────────────────────────────
oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ── JWT helpers ─────────────────────────────────────────
def _create_token(email: str, name: str, picture: str) -> str:
    return jwt.encode(
        {
            "email": email,
            "name": name,
            "picture": picture,
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
        },
        SECRET_KEY,
        algorithm="HS256",
    )


def _get_user(request: Request) -> dict | None:
    token = request.cookies.get("stelliot_token")
    if not token:
        return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None


# ── Login Page ──────────────────────────────────────────
LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STElliot — 로그인</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .login-box {
            text-align: center;
            background: #111;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 48px;
        }
        h1 { font-size: 42px; color: #00d4ff; letter-spacing: 3px; margin-bottom: 8px; }
        .subtitle { color: #888; font-size: 14px; margin-bottom: 36px; }
        .google-btn {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            background: #fff;
            color: #333;
            border: none;
            padding: 12px 32px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 15px;
            font-weight: bold;
            cursor: pointer;
            text-decoration: none;
            transition: box-shadow 0.2s;
        }
        .google-btn:hover { box-shadow: 0 2px 12px rgba(0,212,255,0.3); }
        .google-btn svg { width: 20px; height: 20px; }
        .error { color: #ff6b6b; margin-top: 16px; font-size: 13px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>STElliot</h1>
        <p class="subtitle">엘리어트 파동 자동 분석기</p>
        <a href="/auth/google/login" class="google-btn">
            <svg viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Google 계정으로 로그인
        </a>
        <!--ERRMSG-->
    </div>
</body>
</html>"""


# ── Main Page ───────────────────────────────────────────
MAIN_TEMPLATE = """<!DOCTYPE html>
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
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header-left h1 { font-size: 28px; color: #00d4ff; letter-spacing: 2px; }
        .header-left p { color: #888; margin-top: 4px; font-size: 14px; }
        .user-info {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .user-info img {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            border: 1px solid #444;
        }
        .user-info .name { color: #aaa; font-size: 13px; }
        .logout-btn {
            background: none;
            border: 1px solid #444;
            color: #888;
            padding: 4px 12px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            cursor: pointer;
            text-decoration: none;
        }
        .logout-btn:hover { border-color: #ff6b6b; color: #ff6b6b; }
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
        <div class="header-left">
            <h1>STElliot</h1>
            <p>TradingView 실시간 데이터 기반 엘리어트 파동 자동 분석기</p>
        </div>
        <div class="user-info">
            <!--USER_AVATAR-->
            <span class="name"><!--USER_NAME--></span>
            <a href="/auth/logout" class="logout-btn">logout</a>
        </div>
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


# ── Auth Routes ─────────────────────────────────────────
@app.get("/auth/google/login")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        html = LOGIN_TEMPLATE.replace(
            "<!--ERRMSG-->",
            '<p class="error">인증 실패. 다시 시도해주세요.</p>',
        )
        return HTMLResponse(html)

    userinfo = token.get("userinfo", {})
    email = userinfo.get("email", "")
    name = userinfo.get("name", "")
    picture = userinfo.get("picture", "")

    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        html = LOGIN_TEMPLATE.replace(
            "<!--ERRMSG-->",
            f'<p class="error">접근 권한이 없습니다: {email}</p>',
        )
        return HTMLResponse(html)

    jwt_token = _create_token(email, name, picture)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        "stelliot_token",
        jwt_token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/auth/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("stelliot_token")
    return response


# ── Pages ───────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = _get_user(request)
    if not user:
        html = LOGIN_TEMPLATE.replace("<!--ERRMSG-->", "")
        return HTMLResponse(html)

    name = user.get("name", "")
    picture = user.get("picture", "")
    avatar_tag = f'<img src="{picture}" alt="">' if picture else ""

    html = MAIN_TEMPLATE.replace("<!--USER_AVATAR-->", avatar_tag)
    html = html.replace("<!--USER_NAME-->", name)
    return HTMLResponse(html)


# ── API ─────────────────────────────────────────────────
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
async def api_analyze(request: Request, symbol: str = "005930", tf: str = "60"):
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "로그인이 필요합니다."}, status_code=401)

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

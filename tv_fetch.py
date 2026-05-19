"""
TradingView 웹소켓 데이터 수집기
- TradingView 내부 웹소켓 API를 사용하여 OHLCV 데이터를 가져옴
- 한국 주식, 해외 주식, 암호화폐, 지수 등 TradingView 지원 심볼 모두 사용 가능
"""

import json
import random
import string
import re
import pandas as pd
from websocket import create_connection


def generate_session():
    """TradingView 세션 ID 생성"""
    chars = string.ascii_lowercase
    return "qs_" + "".join(random.choice(chars) for _ in range(12))


def generate_chart_session():
    """TradingView 차트 세션 ID 생성"""
    chars = string.ascii_lowercase
    return "cs_" + "".join(random.choice(chars) for _ in range(12))


def prepend_header(msg):
    """메시지에 헤더 추가"""
    return "~m~" + str(len(msg)) + "~m~" + msg


def construct_message(func, params):
    """TradingView 프로토콜 메시지 생성"""
    return json.dumps({"m": func, "p": params}, separators=(",", ":"))


def create_message(func, params):
    """전송용 메시지 생성"""
    return prepend_header(construct_message(func, params))


def send_message(ws, func, params):
    """웹소켓으로 메시지 전송"""
    ws.send(create_message(func, params))


def fetch_tv_data(symbol="KRX:000660", interval="60", n_bars=500):
    """
    TradingView에서 OHLCV 데이터 가져오기

    Args:
        symbol: TradingView 심볼
            한국: KRX:005930 (삼성전자), KRX:000660 (SK하이닉스), KRX:KOSPI (코스피)
            미국: NASDAQ:AAPL, NASDAQ:NVDA, NYSE:TSLA
            암호화폐: BINANCE:BTCUSDT, BINANCE:ETHUSDT
        interval: 봉 간격
            '1', '5', '15', '60' (분), '240' (4시간), 'D' (일봉), 'W' (주봉)
        n_bars: 가져올 봉 수 (최대 5000)

    Returns:
        pandas DataFrame (datetime index, open, high, low, close, volume)
    """

    ws = create_connection(
        "wss://data.tradingview.com/socket.io/websocket",
        headers={"Origin": "https://data.tradingview.com"},
        timeout=30
    )

    session = generate_session()
    chart_session = generate_chart_session()

    # 초기 메시지 수신
    ws.recv()

    # 세션 설정
    send_message(ws, "set_auth_token", ["unauthorized_user_token"])
    send_message(ws, "chart_create_session", [chart_session, ""])
    send_message(ws, "quote_create_session", [session])
    send_message(ws, "quote_set_fields", [session,
        "ch", "chp", "current_session", "description", "local_description",
        "language", "exchange", "fractional", "is_tradable", "lp", "lp_time",
        "minmov", "minmove2", "original_name", "pricescale", "pro_name",
        "short_name", "type", "update_mode", "volume", "currency_code",
        "logoid", "provider_id"
    ])
    send_message(ws, "quote_add_symbols", [session, symbol])
    send_message(ws, "quote_fast_symbols", [session, symbol])

    # 차트 데이터 요청
    send_message(ws, "resolve_symbol", [
        chart_session, "sds_sym_1",
        '={"symbol":"' + symbol + '","adjustment":"splits","session":"extended"}'
    ])
    send_message(ws, "create_series", [
        chart_session, "sds_1", "s1", "sds_sym_1", interval, n_bars, ""
    ])

    # 데이터 수신
    raw_data = ""
    for _ in range(100):
        try:
            result = ws.recv()
            raw_data += result + "\n"

            if "~h~" in result:
                ws.send(result)

            if "series_completed" in result:
                break
        except Exception:
            break

    ws.close()
    return parse_raw_data(raw_data)


def parse_raw_data(raw_data):
    """수신된 원시 데이터에서 OHLCV 추출"""

    candles = []

    for line in raw_data.split("\n"):
        if "timescale_update" not in line:
            continue

        try:
            json_strs = re.findall(r'~m~\d+~m~(.+?)(?=~m~\d+~m~|$)', line)

            for json_str in json_strs:
                if "timescale_update" not in json_str:
                    continue

                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                if data.get("m") != "timescale_update":
                    continue

                params = data.get("p", [])
                if len(params) < 2:
                    continue

                series_data = params[1]

                if "sds_1" in series_data:
                    sds = series_data["sds_1"]
                    if "s" in sds:
                        for bar in sds["s"]:
                            v = bar.get("v", [])
                            if len(v) >= 5:
                                candles.append({
                                    "timestamp": v[0],
                                    "open": v[1],
                                    "high": v[2],
                                    "low": v[3],
                                    "close": v[4],
                                    "volume": v[5] if len(v) >= 6 else 0
                                })
        except Exception:
            continue

    if not candles:
        return None

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
    df = df.set_index("datetime")
    df = df.drop(columns=["timestamp"])
    df = df.sort_index()

    return df

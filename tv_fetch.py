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
    chars = string.ascii_lowercase
    return "qs_" + "".join(random.choice(chars) for _ in range(12))


def generate_chart_session():
    chars = string.ascii_lowercase
    return "cs_" + "".join(random.choice(chars) for _ in range(12))


def prepend_header(msg):
    return "~m~" + str(len(msg)) + "~m~" + msg


def construct_message(func, params):
    return json.dumps({"m": func, "p": params}, separators=(",", ":"))


def create_message(func, params):
    return prepend_header(construct_message(func, params))


def send_message(ws, func, params):
    ws.send(create_message(func, params))


def fetch_tv_data(symbol="KRX:000660", interval="60", n_bars=500, timeout=15):
    """
    TradingView에서 OHLCV 데이터 가져오기

    Args:
        symbol: TradingView 심볼
        interval: 봉 간격 ('1','5','15','60','240','D','W')
        n_bars: 가져올 봉 수
        timeout: 웹소켓 타임아웃 (초)
    """

    try:
        ws = create_connection(
            "wss://data.tradingview.com/socket.io/websocket",
            headers={"Origin": "https://data.tradingview.com"},
            timeout=timeout
        )
    except Exception as e:
        print(f"웹소켓 연결 실패: {e}")
        return None

    session = generate_session()
    chart_session = generate_chart_session()

    try:
        ws.recv()

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

        send_message(ws, "resolve_symbol", [
            chart_session, "sds_sym_1",
            '={"symbol":"' + symbol + '","adjustment":"splits","session":"extended"}'
        ])
        send_message(ws, "create_series", [
            chart_session, "sds_1", "s1", "sds_sym_1", interval, n_bars, ""
        ])

        raw_data = ""
        for _ in range(100):
            try:
                result = ws.recv()
                raw_data += result + "\n"

                if "~h~" in result:
                    ws.send(result)

                if "series_completed" in result:
                    break

                if "symbol_error" in result or "critical_error" in result:
                    break
            except Exception:
                break

    except Exception as e:
        print(f"데이터 수신 오류: {e}")
        return None
    finally:
        try:
            ws.close()
        except Exception:
            pass

    return parse_raw_data(raw_data)


def parse_raw_data(raw_data):
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

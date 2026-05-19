#!/usr/bin/env python3
"""
엘리어트 파동 자동 분석기
사용법: python elliott.py 005930          (삼성전자)
       python elliott.py 000660          (SK하이닉스)
       python elliott.py 066570          (LG전자)
       python elliott.py 005930 --tf 240  (4시간봉)
       python elliott.py KOSPI            (코스피 지수)
"""

import sys
import pandas as pd
import numpy as np
from tv_fetch import fetch_tv_data

# ─── 스윙 포인트 탐지 ───

def find_swings(df, window=5):
    """스윙 고점/저점 찾기"""
    highs = []
    lows = []
    for i in range(window, len(df) - window):
        if df['high'].iloc[i] == df['high'].iloc[i-window:i+window+1].max():
            highs.append((df.index[i], df['high'].iloc[i]))
        if df['low'].iloc[i] == df['low'].iloc[i-window:i+window+1].min():
            lows.append((df.index[i], df['low'].iloc[i]))
    return highs, lows


def find_major_swings(df, window=10):
    """주요 스윙 포인트 (더 큰 윈도우)"""
    return find_swings(df, window)


# ─── 갭 급등 감지 ───

def detect_gap_spike(df, recent_high, recent_high_date):
    """이벤트성 갭 급등인지 감지"""
    # 고점 20봉 전부터 체크
    idx = df.index.get_loc(recent_high_date) if recent_high_date in df.index else len(df) - 1
    lookback = max(0, idx - 30)
    before = df.iloc[lookback:idx]

    if len(before) < 5:
        return False, 0, 0

    # 고점 전 20봉의 평균 종가
    avg_before = before['close'].tail(20).mean()
    rise_pct = (recent_high - avg_before) / avg_before * 100

    # 갭 체크: 하루 사이에 5% 이상 갭업이 있었는지
    has_gap = False
    for i in range(max(1, len(before)-10), len(before)):
        gap = (before['open'].iloc[i] - before['close'].iloc[i-1]) / before['close'].iloc[i-1] * 100
        if gap > 3:
            has_gap = True
            break

    is_spike = rise_pct > 25 and has_gap
    return is_spike, rise_pct, avg_before


# ─── ABC 구조 탐지 ───

def find_abc_structure(df, recent_high, recent_high_date):
    """고점 이후 ABC 조정 구조 자동 탐지"""
    after_high = df.loc[df.index > recent_high_date]
    if len(after_high) < 5:
        return None

    # A파 저점: 고점 이후 첫 번째 주요 저점
    # 최소 3봉 이상 지난 후의 저점
    min_bars_for_a = min(3, len(after_high) - 1)

    # 롤링 방식으로 저점 찾기
    a_low = after_high['low'].min()
    a_low_date = after_high['low'].idxmin()
    a_low_idx = after_high.index.get_loc(a_low_date)

    # A파 저점 이후 반등 (B파) 찾기
    after_a = after_high.iloc[a_low_idx:]
    if len(after_a) < 2:
        # A파 저점이 마지막이면 → A파 진행 중
        return {
            'phase': 'A파 진행 중',
            'high': recent_high,
            'high_date': recent_high_date,
            'a_low': a_low,
            'a_low_date': a_low_date,
            'a_drop': recent_high - a_low,
        }

    b_high = after_a['high'].max()
    b_high_date = after_a['high'].idxmax()
    b_high_idx = after_a.index.get_loc(b_high_date)

    # B파가 A파 저점과 같은 위치면 → A파 진행 중일 수 있음
    if b_high <= a_low * 1.005:
        return {
            'phase': 'A파 진행 중',
            'high': recent_high,
            'high_date': recent_high_date,
            'a_low': a_low,
            'a_low_date': a_low_date,
            'a_drop': recent_high - a_low,
        }

    a_drop = recent_high - a_low
    b_retrace = (b_high - a_low) / a_drop if a_drop > 0 else 0

    # B파 이후 데이터
    after_b = after_a.iloc[b_high_idx:]
    current = df.iloc[-1]['close']
    today_low = df.iloc[-1]['low'] if len(df) > 0 else current

    # 오늘 데이터 중 저가
    today_data = df.loc[df.index >= df.index[-1].normalize()] if hasattr(df.index[-1], 'normalize') else df.tail(7)
    today_low = today_data['low'].min()

    c_drop = b_high - current
    c_ratio = c_drop / a_drop if a_drop > 0 else 0

    # C파 진행 중인지 B파 반등 중인지 판단
    if current > b_high * 0.98:
        phase = 'B파 반등 중'
    elif current > a_low:
        if c_ratio > 0.15:
            phase = 'C파 진행 중'
        else:
            phase = 'B파 고점 후 초기 하락'
    else:
        phase = 'C파 진행 중 (A파 저점 이탈)'

    return {
        'phase': phase,
        'high': recent_high,
        'high_date': recent_high_date,
        'a_low': a_low,
        'a_low_date': a_low_date,
        'a_drop': a_drop,
        'b_high': b_high,
        'b_high_date': b_high_date,
        'b_retrace': b_retrace,
        'c_current': current,
        'c_drop': c_drop,
        'c_ratio': c_ratio,
        'today_low': today_low,
    }


# ─── 상승 시작점 찾기 ───

def find_uptrend_start(df, high_date):
    """상승 시작점 (고점 이전 주요 저점)"""
    before = df.loc[df.index < high_date]
    if len(before) < 10:
        return before['low'].min(), before['low'].idxmin()

    # 고점 대비 가장 큰 상승을 만든 저점
    low_val = before['low'].min()
    low_date = before['low'].idxmin()
    return low_val, low_date


# ─── 더블바텀 감지 ───

def detect_double_bottom(df, a_low, tolerance_pct=0.5):
    """더블바텀 패턴 감지"""
    today = df.tail(7)
    today_low = today['low'].min()
    diff_pct = abs(today_low - a_low) / a_low * 100
    if diff_pct <= tolerance_pct:
        return True, today_low
    return False, today_low


# ─── 새 상승파 감지 ───

def detect_new_impulse(abc, df):
    """ABC 완료 후 새 상승 1-2파 감지"""
    if abc is None or 'b_high' not in abc:
        return None

    # C파 저점 이후 반등이 있는지
    current = df.iloc[-1]['close']
    c_low = abc.get('today_low', current)

    # A파 저점 근처에서 반등 (더블바텀)
    is_db, db_low = detect_double_bottom(df, abc['a_low'])

    if is_db and current > db_low * 1.005:
        wave1_height = current - db_low
        wave1_retrace_levels = {
            '38.2%': current - wave1_height * 0.382,
            '50.0%': current - wave1_height * 0.500,
            '61.8%': current - wave1_height * 0.618,
        }
        return {
            'detected': True,
            'wave1_low': db_low,
            'wave1_high': current,
            'wave1_height': wave1_height,
            'invalidation': db_low,  # 여기 깨면 무효
            'retrace_levels': wave1_retrace_levels,
        }
    return None


# ─── 메인 분석 ───

def analyze(symbol_input, timeframe='60', n_bars=500):
    """종목 엘리어트 파동 분석"""

    # 심볼 변환
    sym_map = {
        'KOSPI': 'KRX:KOSPI',
        'KOSDAQ': 'KRX:KOSDAQ',
    }

    if symbol_input.upper() in sym_map:
        symbol = sym_map[symbol_input.upper()]
        name = symbol_input.upper()
    elif symbol_input.isdigit() and len(symbol_input) == 6:
        symbol = f'KRX:{symbol_input}'
        name = symbol_input
    else:
        symbol = symbol_input
        name = symbol_input

    # 데이터 수집
    tf_names = {'60': '1시간봉', '240': '4시간봉', 'D': '일봉', '15': '15분봉'}
    tf_label = tf_names.get(timeframe, f'{timeframe}분봉')

    print(f'\n{"="*65}')
    print(f'  {name} 엘리어트 파동 분석 ({tf_label})')
    print(f'{"="*65}')
    print(f'  데이터 수집 중...')

    df = fetch_tv_data(symbol=symbol, interval=timeframe, n_bars=n_bars)
    if df is None or df.empty:
        print(f'  ❌ 데이터 수집 실패: {symbol}')
        return None

    current = df.iloc[-1]['close']
    current_time = df.index[-1]

    print(f'  수집 완료: {len(df)}개 봉 ({df.index[0]} ~ {current_time})')
    print(f'  현재가: {current:,.0f}')

    # ─── 최근 고점 찾기 ───
    highs, lows = find_major_swings(df, window=10)

    if not highs:
        highs, lows = find_swings(df, window=5)

    if not highs:
        print('  ❌ 스윙 포인트를 찾을 수 없습니다.')
        return None

    # 최근 주요 고점 (현재가보다 높은 것 중 가장 최근)
    recent_highs = [(d, p) for d, p in highs if p > current]
    if recent_highs:
        recent_high_date, recent_high = max(recent_highs, key=lambda x: x[1])
    else:
        recent_high_date, recent_high = max(highs, key=lambda x: x[1])

    # ─── 갭 급등 감지 ───
    is_spike, spike_pct, pre_spike_avg = detect_gap_spike(df, recent_high, recent_high_date)

    # ─── 상승 시작점 ───
    uptrend_start, uptrend_start_date = find_uptrend_start(df, recent_high_date)

    # ─── ABC 구조 분석 ───
    abc = find_abc_structure(df, recent_high, recent_high_date)

    # ─── 출력 ───
    print(f'\n{"━"*65}')

    # 갭 급등 경고
    if is_spike:
        print(f'  ⚠️  이벤트성 급등 감지! (갭 전 평균 대비 +{spike_pct:.1f}%)')
        print(f'  갭 전 평균가: {pre_spike_avg:,.0f}')
        print(f'  현재가 vs 갭전: {"원점 복귀" if current <= pre_spike_avg * 1.02 else f"+{(current/pre_spike_avg-1)*100:.1f}% 위"}')
        print(f'  → 엘리어트 5파 상승이 아닌 이벤트 스파이크 가능성')
        print(f'{"━"*65}')

    # 파동 구조
    print(f'  상승 시작: {uptrend_start:,.0f} ({uptrend_start_date})')
    print(f'  고점: {recent_high:,.0f} ({recent_high_date})')
    print(f'  상승폭: {recent_high - uptrend_start:,.0f} (+{(recent_high/uptrend_start-1)*100:.1f}%)')

    if abc is None:
        print(f'\n  현재 상태: 분석 불가 (데이터 부족)')
        return None

    print(f'\n{"━"*65}')
    print(f'  ABC 조정 분석')
    print(f'{"━"*65}')

    phase = abc['phase']
    a_drop = abc['a_drop']

    print(f'\n  ★ 현재 상태: {phase}')
    print(f'\n  A파: {abc["high"]:,.0f} → {abc["a_low"]:,.0f} = ▼{a_drop:,.0f} (-{a_drop/abc["high"]*100:.1f}%)')

    if 'b_high' in abc:
        b_ret_pct = abc['b_retrace'] * 100
        print(f'  B파: {abc["a_low"]:,.0f} → {abc["b_high"]:,.0f} (되돌림: {b_ret_pct:.1f}%)')

        # B파 되돌림 평가
        if 38 <= b_ret_pct <= 78:
            b_eval = '정상 범위 ✓'
        elif b_ret_pct > 78:
            b_eval = '과도한 되돌림 ⚠️'
        else:
            b_eval = '약한 되돌림'
        print(f'       B파 평가: {b_eval}')

        c_ratio_pct = abc['c_ratio'] * 100
        print(f'  C파: {abc["b_high"]:,.0f} → {current:,.0f} = ▼{abc["c_drop"]:,.0f} (C/A: {c_ratio_pct:.1f}%)')

        # C파 피보나치 타겟
        b_high = abc['b_high']
        print(f'\n{"━"*65}')
        print(f'  C파 피보나치 타겟')
        print(f'{"━"*65}')

        targets = [
            ('C=0.618A', 0.618),
            ('C=0.786A', 0.786),
            ('C=A (1:1)', 1.0),
            ('C=1.272A', 1.272),
            ('C=1.618A', 1.618),
        ]

        current_zone = None
        for label, ratio in targets:
            target = b_high - a_drop * ratio
            if current <= target:
                status = '◀ 이탈'
            else:
                dist = current - target
                pct = dist / current * 100
                status = f'▼{dist:,.0f} ({pct:.1f}%)'
                if current_zone is None:
                    current_zone = label

            marker = ' ★' if current_zone == label else ''
            print(f'  {label:12s}: {target:>12,.0f}  {status}{marker}')

        if current_zone:
            print(f'\n  → 현재 {current_zone} 위, 다음 타겟을 향해 진행 중')
        else:
            print(f'\n  → C=0.618A 이하로 이미 이탈 — 과매도 구간')

    # 전체 피보나치 되돌림
    full_range = recent_high - uptrend_start
    print(f'\n{"━"*65}')
    print(f'  전체 상승 피보나치 되돌림 ({uptrend_start:,.0f} → {recent_high:,.0f})')
    print(f'{"━"*65}')

    for label, ratio in [('23.6%', 0.236), ('38.2%', 0.382), ('50.0%', 0.5), ('61.8%', 0.618), ('78.6%', 0.786)]:
        level = recent_high - full_range * ratio
        if current <= level:
            status = '◀ 이탈'
        else:
            dist = current - level
            status = f'▼{dist:,.0f} ({dist/current*100:.1f}%)'
        near = ' ◀ 현재 근접' if abs(current - level) / current * 100 < 1.5 else ''
        print(f'  {label:6s}: {level:>12,.0f}  {status}{near}')

    # 더블바텀 감지
    if 'a_low' in abc:
        is_db, db_low = detect_double_bottom(df, abc['a_low'])
        if is_db:
            print(f'\n  🔔 더블바텀 감지! A파 저점({abc["a_low"]:,.0f}) ≈ 최근 저가({db_low:,.0f})')

    # 새 상승파 감지
    new_impulse = detect_new_impulse(abc, df)
    if new_impulse and new_impulse.get('detected'):
        ni = new_impulse
        print(f'\n{"━"*65}')
        print(f'  🚀 새 상승 임펄스 가능성 감지')
        print(f'{"━"*65}')
        print(f'  1파: {ni["wave1_low"]:,.0f} → {ni["wave1_high"]:,.0f} (△{ni["wave1_height"]:,.0f})')
        print(f'  2파 되돌림 예상:')
        for label, level in ni['retrace_levels'].items():
            print(f'    {label}: {level:,.0f}')
        print(f'  무효화: {ni["invalidation"]:,.0f} 이탈 시')

    # 종합 판단
    print(f'\n{"━"*65}')
    print(f'  종합 판단')
    print(f'{"━"*65}')

    if is_spike:
        print(f'  ⚠️  이벤트성 급등 후 되돌림 — 엘리어트 적용 부적합')
        print(f'  → 갭 메꾸기 패턴, 바닥 예측 어려움')
        print(f'  → 매수 비추천')
    elif 'b_high' in abc:
        c_ratio_pct = abc['c_ratio'] * 100
        if c_ratio_pct < 30:
            print(f'  📉 C파 초기 (C/A={c_ratio_pct:.0f}%) — 추가 하락 예상')
            print(f'  → 매수 대기')
        elif 30 <= c_ratio_pct < 55:
            print(f'  📉 C파 진행 중 (C/A={c_ratio_pct:.0f}%) — 아직 진행 중')
            print(f'  → 분할매수 준비')
        elif 55 <= c_ratio_pct < 90:
            print(f'  📊 C파 중후반 (C/A={c_ratio_pct:.0f}%) — 0.618A~A 구간')
            if is_db:
                print(f'  → 더블바텀 + C=0.618A 지지 = 매수 관심 구간!')
            else:
                print(f'  → C=A(1:1) 타겟 주시, 분할매수 시작 가능')
        elif 90 <= c_ratio_pct <= 115:
            print(f'  📊 C≈A 도달 (C/A={c_ratio_pct:.0f}%) — 교과서적 C파 종료 구간')
            print(f'  → 적극 매수 구간!')
        else:
            print(f'  ⚠️  C파 과확장 (C/A={c_ratio_pct:.0f}%) — 과매도')
            print(f'  → 바닥잡기 위험, 확인 후 매수')
    else:
        print(f'  📉 {phase}')

    print(f'\n{"="*65}\n')
    return abc


# ─── CLI ───

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        print('예시:')
        print('  python elliott.py 005930        # 삼성전자 1시간봉')
        print('  python elliott.py 000660        # SK하이닉스 1시간봉')
        print('  python elliott.py KOSPI         # 코스피 지수')
        print('  python elliott.py 005930 --tf 240  # 삼성전자 4시간봉')
        print('  python elliott.py 005930 --tf D    # 삼성전자 일봉')
        sys.exit(0)

    symbol = sys.argv[1]
    tf = '60'
    n = 500

    for i, arg in enumerate(sys.argv):
        if arg == '--tf' and i + 1 < len(sys.argv):
            tf = sys.argv[i + 1]
        if arg == '--bars' and i + 1 < len(sys.argv):
            n = int(sys.argv[i + 1])

    # 여러 종목 동시 분석
    if ',' in symbol:
        symbols = [s.strip() for s in symbol.split(',')]
        for s in symbols:
            analyze(s, timeframe=tf, n_bars=n)
    else:
        analyze(symbol, timeframe=tf, n_bars=n)

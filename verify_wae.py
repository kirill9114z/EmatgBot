"""Сверка быстрого WAE с эталонным на реальных данных Bybit.

Запуск:  python verify_wae.py [кол-во пар] [таймфрейм]

Проверяет три вещи:
  1. массивы wae_v2 и wae_v2_fast совпадают (сравнение по abs/rel допуску);
  2. решения check_sequence на обеих реализациях идентичны — это то, что
     реально влияет на отправку сигнала;
  3. во сколько раз быстрее считает векторная версия.

Скрипт только читает публичные рыночные данные, ничего никуда не отправляет.
"""
import asyncio
import sys
import time

import numpy as np
import ccxt.async_support as ccxt

from wae_filter import wae_v2, check_sequence
from wae_fast import wae_v2_fast, compute_wae_map

FIELDS = ('t1', 'trend_up', 'trend_down', 'e1', 'dead_zone', 'macd_line')

# Последовательности, на которых сверяем решения фильтра.
TEST_SEQUENCES = [
    [{'SELL': 10}],
    [{'SELL': -90}, {'SELL': 10}],
    [{'BUY': -90}, {'BUY': -90}, {'BUY': -90}],
]


def compare(a, b):
    """Максимальное расхождение двух массивов, NaN в одинаковых местах — ок."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return None, 'разная длина'
    nan_a, nan_b = np.isnan(a), np.isnan(b)
    if not np.array_equal(nan_a, nan_b):
        return None, f'NaN в разных позициях ({nan_a.sum()} против {nan_b.sum()})'
    mask = ~nan_a
    if not mask.any():
        return 0.0, None
    diff = np.abs(a[mask] - b[mask])
    scale = np.maximum(np.abs(a[mask]), 1e-12)
    return float(np.max(diff / scale)), None


async def main():
    limit_pairs = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    timeframe = sys.argv[2] if len(sys.argv) > 2 else '1d'

    exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try:
        await exchange.load_markets()
        symbols = [
            s for s, m in exchange.markets.items()
            if m.get('swap') and m.get('linear') and m.get('settle') == 'USDT' and m.get('active', True)
        ][:limit_pairs]

        print(f'Проверяю {len(symbols)} пар на таймфрейме {timeframe}\n')

        worst_rel, worst_symbol, worst_field = 0.0, None, None
        problems, decision_mismatch = [], 0
        checked, t_ref, t_fast = 0, 0.0, 0.0
        candles_map, refs = {}, {}

        for symbol in symbols:
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=200)
            except Exception as e:
                problems.append(f'{symbol}: свечи не получены ({e})')
                continue
            if not ohlcv or len(ohlcv) < 101:
                continue

            rows = np.asarray(ohlcv, dtype=float)
            high, low, close = rows[:, 2], rows[:, 3], rows[:, 4]

            started = time.perf_counter()
            ref = wae_v2(high, low, close)
            t_ref += time.perf_counter() - started

            started = time.perf_counter()
            fast = wae_v2_fast(high, low, close)
            t_fast += time.perf_counter() - started

            checked += 1
            candles_map[symbol] = ohlcv
            refs[symbol] = ref
            for field in FIELDS:
                rel, err = compare(ref[field], fast[field])
                if err:
                    problems.append(f'{symbol}.{field}: {err}')
                    continue
                if rel > worst_rel:
                    worst_rel, worst_symbol, worst_field = rel, symbol, field

            # Главное: совпадают ли РЕШЕНИЯ фильтра, а не только числа.
            for sequence in TEST_SEQUENCES:
                ok_ref, _ = check_sequence(ref, sequence)
                ok_fast, _ = check_sequence(fast, sequence)
                if ok_ref != ok_fast:
                    decision_mismatch += 1
                    problems.append(f'{symbol}: решение разошлось на {sequence}')

        # Пакетный путь — тот, которым реально ходит сканер.
        started = time.perf_counter()
        batch = compute_wae_map(candles_map)
        t_batch = time.perf_counter() - started

        batch_worst = 0.0
        for symbol, ref in refs.items():
            got = batch.get(symbol)
            if got is None:
                problems.append(f'{symbol}: пакетный расчёт пару потерял')
                continue
            for field in FIELDS:
                rel, err = compare(ref[field], got[field])
                if err:
                    problems.append(f'{symbol}.{field} (пакет): {err}')
                    continue
                batch_worst = max(batch_worst, rel)
            for sequence in TEST_SEQUENCES:
                ok_ref, _ = check_sequence(ref, sequence)
                ok_batch, _ = check_sequence(got, sequence)
                if ok_ref != ok_batch:
                    decision_mismatch += 1
                    problems.append(f'{symbol}: решение пакета разошлось на {sequence}')

        print(f'Сверено пар:            {checked}')
        print(f'Худшее относительное    {worst_rel:.3e}'
              + (f'  ({worst_symbol}, поле {worst_field})' if worst_symbol else ''))
        print(f'расхождение             (1e-15 — уровень округления float64)')
        print(f'Разошедшихся решений:   {decision_mismatch}')
        print(f'Худшее расхождение      {batch_worst:.3e}')
        print(f'пакетного расчёта')
        if checked:
            print(f'\nВремя эталона:          {t_ref * 1000 / checked:.3f} мс/пара')
            print(f'Время быстрой версии:   {t_fast * 1000 / checked:.3f} мс/пара'
                  f'   ({t_ref / t_fast:.1f}x)' if t_fast else '')
            print(f'Время пакетной версии:  {t_batch * 1000 / checked:.3f} мс/пара'
                  f'   ({t_ref / t_batch:.1f}x)' if t_batch else '')

        if problems:
            print(f'\nПроблемы ({len(problems)}):')
            for p in problems[:20]:
                print(f'  - {p}')
        else:
            print('\nПроблем не найдено.')

        ok = not problems and worst_rel < 1e-9 and batch_worst < 1e-9
        print('\nИТОГ:', 'реализации эквивалентны' if ok else 'ЕСТЬ РАСХОЖДЕНИЯ')
        return 0 if ok else 1
    finally:
        await exchange.close()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))

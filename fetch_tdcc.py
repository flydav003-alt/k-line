#!/usr/bin/env python3
"""
每週抓取集保結算所「全市場股權分散表」(開放資料 id=1-5)，累積成每檔股票一個 JSON：
    data/holders/<代號>.json   ->  {"code": "2330", "weeks": [{"d": "2026-10-30", "p": [15個級距占比%], "n": [15個級距人數]}, ...]}

集保公布的 CSV 只有「當週」資料，所以歷史要靠這支腳本每週累積。
用法：
    python scripts/fetch_tdcc.py                 # 線上下載
    python scripts/fetch_tdcc.py some_file.csv   # 用本機 CSV（除錯用）
CSV 欄位（依位置讀取，不依賴標題文字）：資料日期, 證券代號, 持股分級(1~15, 16=差異數調整, 17=合計), 人數, 股數, 占集保庫存數比例%
"""
import csv, io, json, os, re, sys, urllib.request
from datetime import datetime, timezone

URL = 'https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5'
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
OUT_DIR = os.path.join(ROOT, 'data', 'holders')
KEEP_WEEKS = 60                                   # 每檔保留約 14 個月
CODE_RE = re.compile(r'^(\d{4}|00\d{2,4}[A-Z]?)$')  # 一般股票 + ETF；排除權證、債券等
MIN_ROWS_SANITY = 5000                            # 解析到的列數低於此值視為下載異常


def download():
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (kline-holders-bot)'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode('utf-8-sig', errors='replace')


def num(s):
    s = str(s).strip().replace(',', '')
    try:
        return float(s)
    except ValueError:
        return None


def parse(text):
    """-> (date 'YYYY-MM-DD', {code: {'p': [15], 'n': [15]}}, 讀到的有效列數)"""
    rows = 0
    date = None
    acc = {}
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 6:
            continue
        d, code, lv = rec[0].strip().lstrip('\ufeff'), rec[1].strip(), rec[2].strip()
        if not re.fullmatch(r'\d{8}', d) or not lv.isdigit():       # 跳過標題列
            continue
        rows += 1
        level = int(lv)
        if level < 1 or level > 15 or not CODE_RE.match(code):
            continue
        people, pct = num(rec[3]), num(rec[5])
        if people is None or pct is None:
            continue
        date = f'{d[:4]}-{d[4:6]}-{d[6:]}'
        e = acc.setdefault(code, {'p': [None] * 15, 'n': [None] * 15})
        e['p'][level - 1] = pct
        e['n'][level - 1] = int(people)
    # 只留 15 個級距都齊全的
    clean = {c: v for c, v in acc.items() if None not in v['p'] and None not in v['n']}
    return date, clean, rows


def merge(out_dir, date, data):
    os.makedirs(out_dir, exist_ok=True)
    changed = 0
    for code, rec in data.items():
        path = os.path.join(out_dir, f'{code}.json')
        weeks = []
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    weeks = json.load(f).get('weeks', [])
            except Exception:
                weeks = []
        weeks = [w for w in weeks if w.get('d') != date]          # 同一週重跑 → 覆蓋，不重複
        weeks.append({'d': date, 'p': rec['p'], 'n': rec['n']})
        weeks.sort(key=lambda w: w['d'])
        weeks = weeks[-KEEP_WEEKS:]
        new = json.dumps({'code': code, 'weeks': weeks}, ensure_ascii=False, separators=(',', ':'))
        old = None
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                old = f.read()
        if old != new:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new)
            changed += 1
    return changed


def main(argv):
    text = open(argv[1], encoding='utf-8-sig').read() if len(argv) > 1 else download()
    date, data, rows = parse(text)
    if not date or rows < MIN_ROWS_SANITY and len(argv) <= 1:
        print(f'解析結果異常：date={date} rows={rows}，不寫入。', file=sys.stderr)
        return 1
    if not data:
        print('沒有任何股票通過檢查，不寫入。', file=sys.stderr)
        return 1
    changed = merge(OUT_DIR, date, data)
    with open(os.path.join(OUT_DIR, '_meta.json'), 'w', encoding='utf-8') as f:
        json.dump({'latest': date, 'stocks': len(data), 'updated': datetime.now(timezone.utc).isoformat(timespec='seconds')}, f)
    print(f'資料日 {date}｜{len(data)} 檔｜更新 {changed} 個檔案')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

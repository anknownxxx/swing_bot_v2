"""
price_compare.py - 候補銘柄の株価比較モジュール

指定したExcelファイルのA列から銘柄コードを読み込み、
現在の株価・前回との差・変化率・為替をG列以降に追記する。

実行するたびに右側に新しい列が追加されていく。
"""

import yfinance as yf
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter
from datetime import datetime
import sys


def get_current_price(ticker: str) -> float | None:
    """
    銘柄の現在価格を取得する関数。

    Args:
        ticker (str): 銘柄コード（例: "AAPL"）

    Returns:
        float | None: 現在価格（取得失敗時はNone）
    """
    try:
        df = yf.download(ticker, period="5d",
                        auto_adjust=True, progress=False)
        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].iloc[:, 0].dropna()
        else:
            close = df["Close"].squeeze().dropna()

        return float(close.iloc[-1])

    except Exception:
        return None


def get_usdjpy() -> float:
    """
    現在のドル円レートを取得する関数。

    Returns:
        float: ドル円レート（取得失敗時は150.0）
    """
    try:
        df = yf.download("USDJPY=X", period="5d",
                        auto_adjust=True, progress=False)
        if df.empty:
            return 150.0

        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].iloc[:, 0].dropna()
        else:
            close = df["Close"].squeeze().dropna()

        return float(close.iloc[-1])

    except Exception:
        return 150.0


def find_next_group_start(ws) -> int:
    """
    次に書き込むG列以降の開始列を探す関数。

    既存のデータの右端の次の列から書き込む。
    4列（株価・差・変化率・為替）を1セットとして
    右に追加していく。

    Returns:
        int: 書き込み開始列番号（最小7 = G列）
    """
    # G列（7列目）から右に向かって空列を探す
    start_col = 7  # G列

    # 1行目のヘッダーを確認して最後の記録列を探す
    for col in range(7, ws.max_column + 2):
        cell = ws.cell(row=1, column=col)
        if cell.value is None:
            return col

    return ws.max_column + 1


def update_price_comparison(filepath: str) -> None:
    """
    Excelファイルに現在の株価比較データを追記する関数。

    A列の銘柄コードを読み込んで現在価格を取得し
    G列以降に追記する。実行するたびに右に4列追加される。

    Args:
        filepath (str): Excelファイルのパス
    """
    try:
        wb = load_workbook(filepath)
    except FileNotFoundError:
        print(f"エラー: {filepath} が見つかりません")
        return

    ws = wb.active
    today = datetime.now().strftime("%Y/%m/%d %H:%M")

    # A列から銘柄コードを取得（1行目はヘッダーとして除外）
    tickers = []
    for row in range(2, ws.max_row + 1):
        ticker = ws.cell(row=row, column=1).value
        if ticker:
            tickers.append((row, str(ticker).strip()))

    if not tickers:
        print("銘柄が見つかりません（A列を確認してください）")
        return

    print(f"対象銘柄: {[t[1] for t in tickers]}")

    # 書き込み開始列を決定
    start_col = find_next_group_start(ws)
    price_col  = start_col      # 現在株価($)
    diff_col   = start_col + 1  # 前回との差($)
    pct_col    = start_col + 2  # 変化率(%)
    fx_col     = start_col + 3  # 為替

    # ヘッダーの色設定
    header_fill = PatternFill(
        start_color="366092",
        end_color="366092",
        fill_type="solid"
    )
    header_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center")

    # 1行目にヘッダーを追加
    headers = {
        price_col: f"株価($)\n{today}",
        diff_col:  f"前回差($)\n{today}",
        pct_col:   f"変化率(%)\n{today}",
        fx_col:    f"為替\n{today}"
    }

    for col, header in headers.items():
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center", wrap_text=True
        )
        ws.row_dimensions[1].height = 35
        ws.column_dimensions[get_column_letter(col)].width = 14

    # 現在の為替レートを取得
    usdjpy = get_usdjpy()
    print(f"為替: {usdjpy:.1f}円/ドル")

    # 各銘柄の価格を取得して書き込む
    for row, ticker in tickers:
        current_price = get_current_price(ticker)

        if current_price is None:
            print(f"  {ticker}: 取得失敗")
            ws.cell(row=row, column=price_col, value="取得失敗")
            continue

        # 前回の株価を探す（左側の株価列から最新を取得）
        prev_price = None
        for col in range(price_col - 1, 6, -4):
            # 4列1セットで左に遡る（株価列は4n+7の位置）
            if col >= 7:
                val = ws.cell(row=row, column=col).value
                if val and isinstance(val, (int, float)):
                    prev_price = float(val)
                    break

        # 前回との差を計算
        if prev_price:
            diff = current_price - prev_price
            pct_change = (diff / prev_price) * 100
        else:
            # 前回データがない場合はC列（記録時の株価）と比較
            c_val = ws.cell(row=row, column=3).value
            if c_val and isinstance(c_val, (int, float)):
                diff = current_price - float(c_val)
                pct_change = (diff / float(c_val)) * 100
            else:
                diff = 0.0
                pct_change = 0.0

        # 符号付きの文字列に変換
        diff_str = f"+{diff:.2f}" if diff >= 0 else f"{diff:.2f}"
        pct_str  = f"+{pct_change:.2f}%" if pct_change >= 0 \
                   else f"{pct_change:.2f}%"

        # 色設定（プラスは緑・マイナスは赤）
        if diff >= 0:
            color_fill = PatternFill(
                start_color="E2EFDA",
                end_color="E2EFDA",
                fill_type="solid"
            )
            color_font = Font(color="375623")
        else:
            color_fill = PatternFill(
                start_color="FCE4D6",
                end_color="FCE4D6",
                fill_type="solid"
            )
            color_font = Font(color="C00000")

        # 株価を書き込む
        price_cell = ws.cell(
            row=row, column=price_col, value=current_price
        )
        price_cell.alignment = center

        # 差を書き込む（色付き）
        diff_cell = ws.cell(
            row=row, column=diff_col, value=diff_str
        )
        diff_cell.fill = color_fill
        diff_cell.font = color_font
        diff_cell.alignment = center

        # 変化率を書き込む（色付き）
        pct_cell = ws.cell(
            row=row, column=pct_col, value=pct_str
        )
        pct_cell.fill = color_fill
        pct_cell.font = color_font
        pct_cell.alignment = center

        # 為替を書き込む
        fx_cell = ws.cell(
            row=row, column=fx_col, value=round(usdjpy, 1)
        )
        fx_cell.alignment = center

        print(f"  {ticker}: ${current_price:.2f} "
              f"({diff_str}) {pct_str}")

    wb.save(filepath)
    print(f"\nExcel更新完了: {filepath}")


if __name__ == "__main__":
    """
    使い方:
    python price_compare.py                           # デフォルト
    python price_compare.py candidate_tracker.xlsx   # ファイル指定
    """
    # コマンドライン引数でファイルパスを指定できる
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = "candidate_tracker.xlsx"

    print(f"=== 株価比較更新 ===")
    print(f"対象ファイル: {filepath}")
    update_price_comparison(filepath)
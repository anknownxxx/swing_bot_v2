"""
tracker.py - 候補銘柄の株価追跡モジュール

週次スクリーニングで選出された候補銘柄の
株価推移をExcelで自動管理する。

【Excelの構成】
シート1 (log): 候補銘柄の記録
  銘柄・候補日・候補時株価($)・為替・候補時株価(円)

シート2 (tracking): 日次株価追跡
  縦=銘柄、横=日付（候補日から10営業日分）
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter
import os

# Excelファイルのパス
EXCEL_PATH = "candidate_tracker.xlsx"
# 追跡する営業日数
TRACKING_DAYS = 10


def get_current_price(ticker: str) -> float | None:
    """
    銘柄の現在価格を取得する関数。

    Args:
        ticker (str): 銘柄コード

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
        float: ドル円レート
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


def create_excel() -> None:
    """
    Excelファイルを新規作成する関数。

    ファイルが存在しない場合のみ実行される。
    シート1（log）とシート2（tracking）を作成する。
    """
    wb = Workbook()

    # シート1: 候補銘柄ログ
    ws_log = wb.active
    ws_log.title = "log"

    # ヘッダーの設定
    headers_log = [
        "銘柄", "候補日", "候補時株価($)",
        "為替(円/ドル)", "候補時株価(円)"
    ]
    for col, header in enumerate(headers_log, 1):
        cell = ws_log.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(
            start_color="366092",
            end_color="366092",
            fill_type="solid"
        )
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")

    # 列幅の設定
    ws_log.column_dimensions["A"].width = 10
    ws_log.column_dimensions["B"].width = 15
    ws_log.column_dimensions["C"].width = 18
    ws_log.column_dimensions["D"].width = 18
    ws_log.column_dimensions["E"].width = 18

    # シート2: 日次株価追跡
    ws_track = wb.create_sheet("tracking")

    # ヘッダーの設定
    headers_track = ["銘柄", "候補日"]
    for col, header in enumerate(headers_track, 1):
        cell = ws_track.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(
            start_color="366092",
            end_color="366092",
            fill_type="solid"
        )
        cell.alignment = Alignment(horizontal="center")

    ws_track.column_dimensions["A"].width = 10
    ws_track.column_dimensions["B"].width = 15

    wb.save(EXCEL_PATH)
    print(f"Excelファイルを作成しました: {EXCEL_PATH}")


def add_candidates(candidates: list) -> None:
    """
    スクリーニング結果の候補銘柄をExcelに追加する関数。

    Args:
        candidates (list): screener.pyが返す候補銘柄のリスト
    """
    if not candidates:
        print("候補銘柄なし → Excel更新スキップ")
        return

    # ファイルが存在しない場合は新規作成
    if not os.path.exists(EXCEL_PATH):
        create_excel()

    wb = load_workbook(EXCEL_PATH)
    ws_log = wb["log"]
    ws_track = wb["tracking"]

    # 現在の為替レートを取得
    usdjpy = get_usdjpy()
    today = datetime.now().strftime("%Y/%m/%d")

    # 既存の銘柄リストを取得（重複防止）
    existing = set()
    for row in ws_log.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            existing.add((row[0], row[1]))

    for candidate in candidates:
        ticker = candidate["ticker"]
        price = candidate["price"]
        price_jpy = round(price * usdjpy)

        # 重複チェック（同じ銘柄・同じ日は追加しない）
        if (ticker, today) in existing:
            continue

        # シート1（log）に追加
        next_row = ws_log.max_row + 1
        ws_log.cell(row=next_row, column=1, value=ticker)
        ws_log.cell(row=next_row, column=2, value=today)
        ws_log.cell(row=next_row, column=3, value=price)
        ws_log.cell(row=next_row, column=4, value=usdjpy)
        ws_log.cell(row=next_row, column=5, value=price_jpy)

        # シート2（tracking）に追加
        # 銘柄と候補日を先頭列に記録
        track_row = ws_track.max_row + 1
        ws_track.cell(row=track_row, column=1, value=ticker)
        ws_track.cell(row=track_row, column=2, value=today)

        # 候補日の株価を3列目に記録
        date_header = today
        # 日付ヘッダーが存在しない場合は追加
        header_col = None
        for col in range(3, ws_track.max_column + 2):
            cell = ws_track.cell(row=1, column=col)
            if cell.value == date_header:
                header_col = col
                break
            elif cell.value is None:
                # 新しい日付列を追加
                cell.value = date_header
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(
                    start_color="366092",
                    end_color="366092",
                    fill_type="solid"
                )
                cell.alignment = Alignment(horizontal="center")
                ws_track.column_dimensions[
                    get_column_letter(col)
                ].width = 14
                header_col = col
                break

        if header_col:
            ws_track.cell(
                row=track_row, column=header_col, value=price
            )

        print(f"  追加: {ticker} ${price} "
              f"(¥{price_jpy:,}) 為替{usdjpy:.1f}")

    wb.save(EXCEL_PATH)
    print(f"Excel更新完了: {EXCEL_PATH}")


def update_prices() -> None:
    """
    追跡中の銘柄の現在価格を更新する関数。

    毎日9時にmain.pyから呼び出される。
    候補日から10営業日以内の銘柄のみ更新する。
    """
    if not os.path.exists(EXCEL_PATH):
        print("追跡ファイルなし → スキップ")
        return

    wb = load_workbook(EXCEL_PATH)
    ws_log = wb["log"]
    ws_track = wb["tracking"]

    today = datetime.now().strftime("%Y/%m/%d")
    today_date = date.today()

    # 今日の日付列を確認・追加
    header_col = None
    for col in range(3, ws_track.max_column + 2):
        cell = ws_track.cell(row=1, column=col)
        if cell.value == today:
            header_col = col
            break
        elif cell.value is None:
            cell.value = today
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(
                start_color="366092",
                end_color="366092",
                fill_type="solid"
            )
            cell.alignment = Alignment(horizontal="center")
            ws_track.column_dimensions[
                get_column_letter(col)
            ].width = 14
            header_col = col
            break

    if not header_col:
        print("列の追加に失敗しました")
        return

    updated = 0

    # trackingシートの各行を確認
    for row in range(2, ws_track.max_row + 1):
        ticker = ws_track.cell(row=row, column=1).value
        candidate_date_str = ws_track.cell(row=row, column=2).value

        if not ticker or not candidate_date_str:
            continue

        # 候補日からの営業日数を計算
        candidate_date = datetime.strptime(
            candidate_date_str, "%Y/%m/%d"
        ).date()
        holding_days = np.busday_count(candidate_date, today_date)

        # 10営業日を超えた銘柄はスキップ
        if holding_days > TRACKING_DAYS:
            continue

        # 現在価格を取得して記録
        price = get_current_price(ticker)
        if price:
            ws_track.cell(row=row, column=header_col, value=price)
            updated += 1
            print(f"  更新: {ticker} ${price:.2f} "
                  f"({holding_days}営業日目)")

    wb.save(EXCEL_PATH)
    print(f"価格更新完了: {updated}銘柄")


if __name__ == "__main__":
    """
    動作確認用テストコード。
    """
    print("=== tracker.py 動作確認 ===")

    # テスト用の候補銘柄
    test_candidates = [
        {"ticker": "NVDA", "price": 125.30},
        {"ticker": "AAPL", "price": 309.35},
    ]

    print("\n1. 候補銘柄を追加...")
    add_candidates(test_candidates)

    print("\n2. 価格を更新...")
    update_prices()

    print(f"\nExcelファイルを確認してください: {EXCEL_PATH}")
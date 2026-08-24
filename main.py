"""
main.py - スケジュール実行のエントリーポイント

このファイルを実行するだけで全機能が自動で動く。
以下のスケジュールで各モジュールを呼び出す：

平日 09:00 → 保有銘柄の損切り・利確・強制決済チェック
平日 22:00 → 同上（米国市場開場前の最終確認）
毎週土曜 08:00 → S&P500スクリーニング・週次レポート送信

【設計思想】
このファイルはスケジューラーの役割だけを持つ。
実際の処理は各モジュール（monitor.py・screener.py）に委譲する。
単一責任の原則に従い、「いつ何を実行するか」だけを管理する。
"""

import schedule
import time
from datetime import datetime
from monitor import run_monitor
from screener import run_screening
from notifier import send_weekly_report


def is_weekday() -> bool:
    """
    今日が平日（月〜金）かどうかを判定する関数。

    Returns:
        bool: 平日=True、土日=False

    Note:
        weekday()は月曜=0、日曜=6を返す
        0〜4が平日（月〜金）
    """
    return datetime.now().weekday() < 5


def run_daily() -> None:
    """
    毎日9時・22時に実行する監視処理。

    平日のみ実行する。
    土日は米国市場が休場のため処理をスキップする。
    """
    if not is_weekday():
        print(f"[{datetime.now().strftime('%Y/%m/%d %H:%M')}] "
              f"土日のためスキップ")
        return

    run_monitor()


def run_weekly() -> None:
    """
    毎週土曜8時に実行するスクリーニング処理。

    portfolio.csvから現在の保有数と
    総資金を読み込んでケリー基準を計算する。
    """
    import pandas as pd

    print(f"\n=== 週次スクリーニング開始 "
          f"{datetime.now().strftime('%Y/%m/%d %H:%M')} ===")

    # portfolio.csvから現在の保有銘柄数を取得
    try:
        portfolio = pd.read_csv("portfolio.csv")
        current_positions = len(portfolio)
    except FileNotFoundError:
        current_positions = 0

    # スクリーニング実行
    # total_capital_jpyは実際の総資金（円）に変更してください
    candidates = run_screening(
        total_capital_jpy=100000,   # ← 実際の総資金に変更
        current_positions=current_positions,
        win_rate=0.345              # バックテストの勝率
    )

    # 保有銘柄のサマリーを作成
    portfolio_summary = {"positions": []}
    if current_positions > 0:
        from monitor import get_current_price
        for _, row in portfolio.iterrows():
            price = get_current_price(row["ticker"])
            if price:
                pnl = ((price - row["purchase_price"])
                       / row["purchase_price"] * 100)
                portfolio_summary["positions"].append({
                    "ticker": row["ticker"],
                    "pnl": round(pnl, 1),
                    "current_price": price
                })

    # 週次レポートをGmailに送信
    send_weekly_report(candidates, portfolio_summary)


# ============================================================
# スケジュール設定
# ============================================================
# schedule.every().day.at("HH:MM").do(func)
# → 毎日指定時刻にfuncを実行

schedule.every().day.at("09:00").do(run_daily)   # 毎日9時
schedule.every().day.at("22:00").do(run_daily)   # 毎日22時
schedule.every().saturday.at("08:00").do(run_weekly)  # 毎週土曜8時


if __name__ == "__main__":
    print("=" * 40)
    print("swing_bot_v2 起動")
    print("=" * 40)
    print(f"起動時刻: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print()
    print("【実行スケジュール】")
    print("  平日 09:00 → 損切り・利確チェック")
    print("  平日 22:00 → 損切り・利確チェック")
    print("  毎週土曜 08:00 → 週次スクリーニング")
    print()
    print("停止するには Ctrl+C を押してください")
    print("=" * 40)

    # 動作確認用：今すぐ実行したい場合は以下のコメントを外す
    # run_daily()
    # run_weekly()

    # メインループ
    # schedule.run_pending(): 実行時刻になったジョブを実行
    # time.sleep(60): 1分ごとにチェック
    while True:
        schedule.run_pending()
        time.sleep(60)
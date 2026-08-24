"""
monitor.py - 保有銘柄の監視モジュール

毎日9時・22時に実行され、保有銘柄の現在価格を取得して
以下の条件に該当する場合にGmailで通知する。

【通知条件】
1. 損切りアラート: 現在値が購入単価から-3%以下
2. 利確アラート:   現在値が購入単価から+6%以上
3. 強制決済アラート:
   - 保有5日後に含み損 → 早期撤退を促す
   - 保有10日後      → 無条件で撤退を促す

【設計思想】
損切りはWoodstockの逆指値注文で自動化する。
このモジュールは「確認・記録」が主な役割。
利確・強制決済のタイミングを通知することで
感情的な判断を排除する。
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date
from dotenv import load_dotenv
from config import (
    STOP_LOSS,
    TAKE_PROFIT,
    FORCE_EXIT_LOSS_DAYS,
    FORCE_EXIT_MAX_DAYS,
    MONITOR_PERIOD
)
from notifier import send_alert, send_email

load_dotenv()


def load_portfolio(filepath: str = "portfolio.csv") -> pd.DataFrame:
    """
    portfolio.csvを読み込んで保有銘柄データを返す関数。

    CSVのフォーマット:
    ticker, purchase_price, quantity, purchase_date, type
    AAPL,   150.00,         0.05,     2026-01-15,    individual

    Args:
        filepath (str): CSVファイルのパス

    Returns:
        pd.DataFrame: 保有銘柄データ
    """
    try:
        df = pd.read_csv(filepath)

        # purchase_dateをdatetime型に変換
        df["purchase_date"] = pd.to_datetime(df["purchase_date"])

        return df

    except FileNotFoundError:
        print(f"エラー: {filepath} が見つかりません")
        return pd.DataFrame()


def get_current_price(ticker: str) -> float | None:
    """
    yfinanceで銘柄の現在価格を取得する関数。

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

        # 最新の終値を取得（NaNを除外）
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].iloc[:, 0].dropna()
        else:
            close = df["Close"].squeeze().dropna()

        return float(close.iloc[-1])

    except Exception as e:
        print(f"  {ticker}: 価格取得失敗 → {e}")
        return None


def get_usdjpy_rate() -> float:
    """
    現在のドル円レートを取得する関数。

    Returns:
        float: ドル円レート（取得失敗時は150.0をデフォルト値として返す）
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
        # 取得失敗時はデフォルト値を返す
        return 150.0


def calculate_holding_days(purchase_date: pd.Timestamp) -> int:
    """
    購入日から今日までの営業日数を計算する関数。

    営業日数を使う理由:
    土日は市場が休場のため、カレンダー日数ではなく
    実際にトレードできた日数で保有期間を管理する。

    Args:
        purchase_date (pd.Timestamp): 購入日

    Returns:
        int: 営業日数
    """
    # np.busday_count: 営業日数を計算するNumPy関数
    # 土日を除いた日数を返す
    holding_days = np.busday_count(
        purchase_date.date(),
        date.today()
    )
    return int(holding_days)


def check_portfolio() -> list:
    """
    保有銘柄全体をチェックしてアラートリストを返す関数。

    Returns:
        list: アラートが必要な銘柄の情報リスト
    """
    portfolio = load_portfolio()
    if portfolio.empty:
        print("保有銘柄なし")
        return []

    # ドル円レートを一度だけ取得（全銘柄で共用）
    usdjpy = get_usdjpy_rate()
    print(f"ドル円レート: {usdjpy:.1f}円")

    alerts = []
    print(f"\n{'銘柄':<8} {'現在値':>8} {'購入単価':>8} "
          f"{'損益率':>8} {'保有日数':>6} {'判定'}")
    print("-" * 55)

    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        purchase_price = float(row["purchase_price"])
        purchase_date = row["purchase_date"]

        # 現在価格を取得
        current_price = get_current_price(ticker)
        if current_price is None:
            print(f"{ticker:<8} {'取得失敗':>8}")
            continue

        # 損益率の計算
        pct_change = (current_price - purchase_price) / purchase_price

        # 保有営業日数の計算
        holding_days = calculate_holding_days(purchase_date)

        # アラート判定
        alert_type = None

        if pct_change <= -STOP_LOSS:
            alert_type = "stop_loss"

        elif pct_change >= TAKE_PROFIT:
            alert_type = "take_profit"

        elif holding_days >= FORCE_EXIT_LOSS_DAYS and pct_change < 0:
            alert_type = "force_exit_loss"

        elif holding_days >= FORCE_EXIT_MAX_DAYS:
            alert_type = "force_exit_max"

        # 判定結果のラベル
        status_labels = {
            "stop_loss": "🚨損切り",
            "take_profit": "✅利確",
            "force_exit_loss": "⏰強制(損)",
            "force_exit_max": "⏰強制(期間)",
            None: "👀監視中"
        }
        status = status_labels[alert_type]

        print(f"{ticker:<8} ${current_price:>7.2f} "
              f"${purchase_price:>7.2f} "
              f"{pct_change*100:>+7.1f}% "
              f"{holding_days:>5}日 {status}")

        if alert_type:
            alerts.append({
                "ticker": ticker,
                "current_price": current_price,
                "purchase_price": purchase_price,
                "pct_change": pct_change,
                "holding_days": holding_days,
                "alert_type": alert_type,
                "usdjpy": usdjpy
            })

    return alerts


def send_portfolio_alerts(alerts: list) -> None:
    """
    アラートリストに基づいてGmailを送信する関数。

    Args:
        alerts (list): check_portfolio()が返したアラートリスト
    """
    if not alerts:
        print("\n✅ アラートなし（全銘柄監視中）")
        return

    print(f"\n{len(alerts)}件のアラートを送信中...")

    for alert in alerts:
        send_alert(
            ticker=alert["ticker"],
            current_price=alert["current_price"],
            purchase_price=alert["purchase_price"],
            pct_change=alert["pct_change"],
            alert_type=alert["alert_type"]
        )


def run_monitor() -> None:
    """
    監視処理全体を実行するメイン関数。

    main.pyから呼び出される。
    """
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    print(f"\n=== 保有銘柄監視 {now} ===")

    alerts = check_portfolio()
    send_portfolio_alerts(alerts)


if __name__ == "__main__":
    """
    動作確認用テストコード。
    portfolio.csvが存在する状態で実行する。
    """
    run_monitor()
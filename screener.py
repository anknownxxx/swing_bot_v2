"""
screener.py - 週次スクリーニングモジュール

毎週土曜日にS&P500全銘柄をスキャンして
エントリー条件を満たす買い候補銘柄を抽出し
Gmailで通知する。

【スクリーニング条件】
1. 20日移動平均線が過去5日間で上向き
2. 現在値が20日線から+3%〜+7%の範囲内
3. VIX < 25（市場の恐怖度が低い）
4. SPY > 200日線かつ20日・50日線が上向き
"""

import yfinance as yf
import pandas as pd
import warnings
from datetime import datetime
from config import (
    MA_PERIOD,
    MA_SLOPE_DAYS,
    DEVIATION_MIN,
    DEVIATION_MAX,
    VIX_THRESHOLD,
    SPY_MA_PERIOD,
    SPY_MA_SHORT,
    SPY_MA_MID,
    SPY_SLOPE_DAYS,
    STOP_LOSS,
    MONITOR_PERIOD,
    SP500_URL
)
from notifier import send_weekly_report
from kelly import calculate_position_size

warnings.filterwarnings("ignore")


def get_sp500_tickers() -> list:
    """
    S&P500の構成銘柄リストを取得する関数。

    Returns:
        list: ティッカーシンボルのリスト

    Data Source:
        github.com/datasets/s-and-p-500-companies
        License: Open Data Commons PDDL
    """
    df = pd.read_csv(SP500_URL)
    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    return tickers


def fetch_market_filters() -> dict:
    """
    市場環境フィルターの判定に必要なデータを取得する関数。

    VIXとSPYのデータを一括取得して
    今日時点でフィルターを通過するかどうかを返す。

    Returns:
        dict: 市場環境の判定結果
            {
                "vix": float,          # 現在のVIX水準
                "vix_ok": bool,        # VIXフィルター通過
                "spy_above_ma200": bool, # SPY > 200日線
                "spy_ma20_up": bool,   # SPYの20日線が上向き
                "spy_ma50_up": bool,   # SPYの50日線が上向き
                "spy_ok": bool         # SPY全条件通過
            }
    """
    # VIXの取得
    vix_df = yf.download("^VIX", period="1mo",
                         auto_adjust=True, progress=False)
    vix_now = float(vix_df["Close"].iloc[-1].item())

    # SPYの取得
    spy_df = yf.download("SPY", period="1y",
                         auto_adjust=True, progress=False)

    # 多重インデックス対応
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy = spy_df["Close"].iloc[:, 0]
    else:
        spy = spy_df["Close"].squeeze()


    # NaNを除外してから計算（引け後の未確定データ対策）
    spy = spy.dropna()

    spy_ma200 = spy.rolling(window=SPY_MA_PERIOD).mean()
    spy_ma20  = spy.rolling(window=SPY_MA_SHORT).mean()
    spy_ma50  = spy.rolling(window=SPY_MA_MID).mean()

    spy_above_ma200 = bool(spy.iloc[-1] > spy_ma200.iloc[-1])
    spy_ma20_up = bool(spy_ma20.iloc[-1] > spy_ma20.iloc[-SPY_SLOPE_DAYS])
    spy_ma50_up = bool(spy_ma50.iloc[-1] > spy_ma50.iloc[-SPY_SLOPE_DAYS])
    

    return {
        "vix": vix_now,
        "vix_ok": vix_now < VIX_THRESHOLD,
        "spy_above_ma200": spy_above_ma200,
        "spy_ma20_up": spy_ma20_up,
        "spy_ma50_up": spy_ma50_up,
        # SPYフィルターは使用しない
        # VIXフィルターだけで市場環境を判断する
        "spy_ok": True
    }


def check_entry_conditions(ticker: str) -> dict | None:
    """
    個別銘柄のエントリー条件を確認する関数。

    20日移動平均線の傾きと乖離率を計算して
    エントリー条件を満たすかどうかを判定する。

    Args:
        ticker (str): 銘柄コード（例: "AAPL"）

    Returns:
        dict | None: 条件を満たす場合は銘柄情報、満たさない場合はNone
            {
                "ticker": str,
                "price": float,
                "deviation": float,
                "ma20": float,
                "vol_ratio": float
            }
    """
    try:
        df = yf.download(ticker, period=MONITOR_PERIOD,
                        auto_adjust=True, progress=False)
        if df.empty or len(df) < 60:
            return None

        # 多重インデックス対応
        if isinstance(df.columns, pd.MultiIndex):
            close  = df["Close"].iloc[:, 0]
            volume = df["Volume"].iloc[:, 0]
        else:
            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze()

        # 20日移動平均線の計算
        ma20 = close.rolling(window=MA_PERIOD).mean()

        # 条件1: 20日線が上向きかどうか
        ma_slope_ok = bool(
            ma20.iloc[-1] > ma20.iloc[-MA_SLOPE_DAYS]
        )
        if not ma_slope_ok:
            return None

        # 乖離率の計算
        # 乖離率 = (現在値 - 20日線) / 20日線
        deviation = float(
            (close.iloc[-1] - ma20.iloc[-1]) / ma20.iloc[-1]
        )

        # 条件2: 乖離率が指定範囲内かどうか
        if not (DEVIATION_MIN <= deviation <= DEVIATION_MAX):
            return None

        # 出来高比率（参考情報として追加）
        vol_ratio = float(
            volume.iloc[-1] / volume.rolling(20).mean().iloc[-1]
        )

        return {
            "ticker": ticker,
            "price": round(float(close.iloc[-1]), 2),
            "deviation": round(deviation, 4),
            "ma20": round(float(ma20.iloc[-1]), 2),
            "vol_ratio": round(vol_ratio, 2)
        }

    except Exception:
        return None


def run_screening(
    total_capital_jpy: float = 100000,
    current_positions: int = 0,
    win_rate: float = 0.344
) -> list:
    """
    S&P500全銘柄のスクリーニングを実行する関数。

    Args:
        total_capital_jpy (float): 総資金（円）
        current_positions (int): 現在の保有銘柄数
        win_rate (float): バックテストで得た勝率（デフォルト: 34.4%）

    Returns:
        list: 条件を満たした銘柄のリスト
    """
    print(f"=== 週次スクリーニング開始 {datetime.now().strftime('%Y/%m/%d %H:%M')} ===")

    # Step 1: 市場環境フィルターの確認
    print("市場環境を確認中...")
    market = fetch_market_filters()

    print(f"  VIX: {market['vix']:.1f} → {'✅' if market['vix_ok'] else '❌'}")
    print(f"  SPY > 200日線: {'✅' if market['spy_above_ma200'] else '❌'}")
    print(f"  SPY 20日線上向き: {'✅' if market['spy_ma20_up'] else '❌'}")
    print(f"  SPY 50日線上向き: {'✅' if market['spy_ma50_up'] else '❌'}")

    # 市場環境フィルターを通過しない場合はスキャンしない
    if not market["vix_ok"] or not market["spy_ok"]:
        print("⚠️ 市場環境フィルターにより今週はスキャンをスキップ")
        return []

    # Step 2: S&P500全銘柄をスキャン
    tickers = get_sp500_tickers()
    print(f"\nS&P500全銘柄をスキャン中（{len(tickers)}銘柄）...")

    candidates = []

    for i, ticker in enumerate(tickers):
        result = check_entry_conditions(ticker)
        if result:
            # ケリー基準で推奨投資額を計算
            kelly = calculate_position_size(
                total_capital_jpy=total_capital_jpy,
                win_rate=win_rate,
                current_positions=current_positions + len(candidates),
                usdjpy_rate=150.0  # 固定値（後でリアルタイム取得に変更可能）
            )
            result["kelly_size"] = kelly["position_jpy"]
            candidates.append(result)
            print(f"  ✅ {ticker}: 乖離率{result['deviation']*100:+.1f}%")

        # 進捗表示（50銘柄ごと）
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(tickers)}] スキャン中...")

    # 乖離率の低い順にソート（より平均線に近い = まだ伸びる余地あり）
    candidates = sorted(candidates, key=lambda x: x["deviation"])

    print(f"\n=== スクリーニング完了 ===")
    print(f"買い候補: {len(candidates)}銘柄")

    return candidates


if __name__ == "__main__":
    """
    動作確認用テストコード。
    実際の資金・保有状況に合わせて変更して使う。
    """
    candidates = run_screening(
        total_capital_jpy=100000,  # 総資金（円）に変更
        current_positions=3,        # 現在の保有銘柄数に変更
        win_rate=0.344              # バックテストの勝率
    )

    # 結果をGmailで送信
    portfolio_summary = {
        "positions": []  # 実際の保有銘柄を入れる
    }
    send_weekly_report(candidates, portfolio_summary)
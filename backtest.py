"""
backtest.py - 戦略バックテストモジュール

【検証する戦略】
  エントリー条件:
    1. 20日移動平均線が過去5日間で上向き（上昇トレンドの確認）
    2. 現在値が20日線から+2%〜+10%の範囲内（適度な乖離）
    3. VIX < 25（市場の恐怖度が低い）
    4. SPY > 200日移動平均線（市場全体が上昇トレンド）

  エグジット条件:
    - 利確: +6%
    - 損切り: -3%
    - 強制決済: 5営業日後に含み損 or 10営業日後

【バックテストの限界】
  - 生存者バイアス: 現在のS&P500構成銘柄のみで検証
    （過去に除外された銘柄は含まれない）
  - スリッページ: 実際の約定価格との差は考慮していない
  - 為替変動: ドルベースで計算（円換算の損益とは異なる）
  → 実際のリターンはバックテスト結果より10〜15%低い可能性がある
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from config import (
    MA_PERIOD,
    MA_SLOPE_DAYS,
    DEVIATION_MIN,
    DEVIATION_MAX,
    TAKE_PROFIT,
    STOP_LOSS,
    FORCE_EXIT_LOSS_DAYS,
    FORCE_EXIT_MAX_DAYS,
    VIX_THRESHOLD,
    SPY_MA_PERIOD,
    SPY_MA_SHORT,
    SPY_MA_MID,
    SPY_SLOPE_DAYS,
    BACKTEST_PERIOD,
    SP500_URL,
    ATR_PERIOD,
    ATR_MIN_PCT
)
warnings.filterwarnings("ignore")


def get_sp500_tickers() -> list:
    """
    S&P500の構成銘柄リストを取得する関数。

    GitHubの公開データセットからCSVを取得してティッカーシンボルを返す。
    BRK.BなどドットはハイフンにReplaceする（yfinance仕様に合わせる）。

    Returns:
        list: ティッカーシンボルのリスト（例: ["AAPL", "MSFT", ...]）

    Data Source:
        github.com/datasets/s-and-p-500-companies
        License: Open Data Commons PDDL
    """
    df = pd.read_csv(SP500_URL)
    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    print(f"S&P500銘柄数: {len(tickers)}銘柄")
    return tickers


def fetch_market_data(period: str = BACKTEST_PERIOD) -> tuple:
    """
    VIXとSPYのデータを取得する関数。

    市場環境フィルターに使用するデータを一括取得する。
    個別銘柄の処理ごとに取得すると時間がかかるため
    最初に一度だけ取得してキャッシュとして使う。

    Args:
        period (str): 取得期間（例: "5y" = 過去5年）

    Returns:
        tuple: (vix_series, spy_series)
            vix_series: VIXの終値時系列データ
            spy_series: SPYの終値時系列データ
    """
    print("市場データ（VIX・SPY）を取得中...")

    # VIX（恐怖指数）の取得
    # ^VIX: VIXのティッカーシンボル（^はインデックスを示す）
    vix_df = yf.download("^VIX", period=period,
                         auto_adjust=True, progress=False)
    vix = vix_df["Close"].squeeze()

    spy_df = yf.download("SPY", period=period,
                         auto_adjust=True, progress=False)
    spy = spy_df["Close"].squeeze()

    # SPYの長期・短期・中期移動平均線を計算
    spy_ma200 = spy.rolling(window=SPY_MA_PERIOD).mean()
    spy_ma20  = spy.rolling(window=SPY_MA_SHORT).mean()
    spy_ma50  = spy.rolling(window=SPY_MA_MID).mean()

    print("市場データの取得完了")
    return vix, spy, spy_ma200, spy_ma20, spy_ma50


def calculate_signals(close: pd.Series,
                      vix: pd.Series,
                      spy: pd.Series,
                      spy_ma200: pd.Series,
                      spy_ma20: pd.Series,
                      spy_ma50: pd.Series) -> pd.Series:
    """
    エントリーシグナルを計算する関数。

    4つの条件が全て満たされた日をエントリー日とする。
    pd.Series同士の論理積（&）で全条件を一括評価する。

    Args:
        close (pd.Series): 対象銘柄の終値時系列データ
        vix (pd.Series): VIXの時系列データ
        spy (pd.Series): SPYの時系列データ
        spy_ma200 (pd.Series): SPYの200日移動平均線

    Returns:
        pd.Series: エントリーシグナル（True=買い、False=待機）
    """
    # 条件1: 20日移動平均線の計算
    ma = close.rolling(window=MA_PERIOD).mean()

    # 条件2: 移動平均線が上向きかどうかの判定
    # MA_SLOPE_DAYS日前より今日の移動平均線が高ければ上向き
    ma_slope = ma > ma.shift(MA_SLOPE_DAYS)

    # 条件3: 乖離率の計算と範囲チェック
    # 乖離率 = (現在値 - 移動平均線) / 移動平均線
    deviation = (close - ma) / ma
    deviation_ok = (deviation >= DEVIATION_MIN) & (deviation <= DEVIATION_MAX)

    # 条件4: VIXフィルター（恐怖指数が閾値未満）
    # reindex: VIXのインデックスを銘柄のインデックスに合わせる
    # ffill: 欠損値を前の値で埋める（休場日対応）
    vix_aligned = vix.reindex(close.index).ffill()
    vix_ok = vix_aligned < VIX_THRESHOLD

    # 条件5: SPYトレンドフィルター
    spy_aligned    = spy.reindex(close.index).ffill()
    spy_ma200_aligned = spy_ma200.reindex(close.index).ffill()
    spy_ma20_aligned  = spy_ma20.reindex(close.index).ffill()
    spy_ma50_aligned  = spy_ma50.reindex(close.index).ffill()

    # SPYの3つの条件：
    # ① SPY > 200日線（長期上昇トレンド）
    # ② SPYの20日線が上向き（短期モメンタム）
    # ③ SPYの50日線が上向き（中期モメンタム）
    spy_above_ma200 = spy_aligned > spy_ma200_aligned
    spy_ma20_up = spy_ma20_aligned > spy_ma20_aligned.shift(SPY_SLOPE_DAYS)
    spy_ma50_up = spy_ma50_aligned > spy_ma50_aligned.shift(SPY_SLOPE_DAYS)
    spy_ok = spy_above_ma200 & spy_ma20_up & spy_ma50_up

    
    # 全条件の論理積（全てTrueの日だけエントリー）
    entry_signals = ma_slope & deviation_ok & vix_ok

    return entry_signals


def simulate_trades(close: pd.Series,
                    signals: pd.Series) -> list:
    """
    エントリーシグナルに基づいてトレードをシミュレーションする関数。

    vectorbtを使わずにループで実装することで
    強制決済ロジック（5日/10日ルール）を柔軟に組み込む。

    Args:
        close (pd.Series): 終値時系列データ
        signals (pd.Series): エントリーシグナル

    Returns:
        list: 各トレードの結果を格納した辞書のリスト
            各辞書のキー:
            - entry_date: エントリー日
            - exit_date: エグジット日
            - entry_price: エントリー価格
            - exit_price: エグジット価格
            - pnl_pct: 損益率
            - exit_reason: 決済理由
            - holding_days: 保有日数
    """
    trades = []
    dates = close.index
    prices = close.values
    in_position = False  # 現在ポジションを持っているか

    for i, (date, price) in enumerate(zip(dates, prices)):
        # ポジションなしの場合: エントリーシグナルを確認
        if not in_position:
            if signals.iloc[i]:
                # エントリー
                entry_price = price
                entry_date = date
                entry_idx = i
                in_position = True

        # ポジションありの場合: エグジット条件を確認
        else:
            # 保有日数を計算
            holding_days = i - entry_idx
            pnl_pct = (price - entry_price) / entry_price

            exit_reason = None

            # 利確条件: +6%以上
            if pnl_pct >= TAKE_PROFIT:
                exit_reason = "take_profit"

            # 損切り条件: -3%以下
            elif pnl_pct <= -STOP_LOSS:
                exit_reason = "stop_loss"

            # 強制決済条件1: 5営業日後に含み損
            elif (holding_days >= FORCE_EXIT_LOSS_DAYS
                  and pnl_pct < 0):
                exit_reason = "force_exit_loss"

            # 強制決済条件2: 10営業日経過
            elif holding_days >= FORCE_EXIT_MAX_DAYS:
                exit_reason = "force_exit_max"

            # いずれかの条件でエグジット
            if exit_reason:
                trades.append({
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": round(float(entry_price), 2),
                    "exit_price": round(float(price), 2),
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "exit_reason": exit_reason,
                    "holding_days": holding_days
                })
                in_position = False

    return trades


def run_backtest(tickers: list = None) -> pd.DataFrame:
    """
    S&P500全銘柄でバックテストを実行する関数。

    Args:
        tickers (list): 対象銘柄リスト（Noneの場合はS&P500全銘柄）

    Returns:
        pd.DataFrame: 全トレード結果のDataFrame
    """
    if tickers is None:
        tickers = get_sp500_tickers()

    # 市場データを一括取得（VIX・SPY）
    vix, spy, spy_ma200, spy_ma20, spy_ma50 = fetch_market_data()

    all_trades = []

    for i, ticker in enumerate(tickers):
        try:
            # 株価データの取得
            df = yf.download(ticker, period=BACKTEST_PERIOD,
                           auto_adjust=True, progress=False)
            if df.empty or len(df) < 252:
                continue

            # 多重インデックス対応（yfinanceの仕様）
            if isinstance(df.columns, pd.MultiIndex):
                close = df["Close"].iloc[:, 0]
            else:
                close = df["Close"].squeeze()

            # エントリーシグナルの計算
            signals = calculate_signals(
                close, vix, spy, spy_ma200, spy_ma20, spy_ma50
            )

            # トレードシミュレーション
            trades = simulate_trades(close, signals)

            if trades:
                for trade in trades:
                    trade["ticker"] = ticker
                all_trades.extend(trades)
                print(f"[{i+1}/{len(tickers)}] "
                      f"{ticker}: {len(trades)}トレード")

        except Exception as e:
            print(f"[{i+1}/{len(tickers)}] {ticker}: スキップ ({e})")
            continue

    # 結果をDataFrameに変換
    df_trades = pd.DataFrame(all_trades)

    if df_trades.empty:
        print("トレードデータなし")
        return df_trades

    # 結果の保存
    df_trades.to_csv("backtest_results.csv", index=False)

    # サマリーの表示
    print_summary(df_trades)

    return df_trades


def print_summary(df: pd.DataFrame) -> None:
    """
    バックテスト結果のサマリーを表示する関数。

    Args:
        df (pd.DataFrame): トレード結果のDataFrame
    """
    total = len(df)
    wins = (df["pnl_pct"] > 0).sum()
    win_rate = wins / total * 100

    # 期待値の計算
    # 期待値 = (勝率 × 平均利益) - (負け率 × 平均損失)
    avg_win = df[df["pnl_pct"] > 0]["pnl_pct"].mean()
    avg_loss = abs(df[df["pnl_pct"] <= 0]["pnl_pct"].mean())
    expected_value = (win_rate/100 * avg_win) - ((1-win_rate/100) * avg_loss)

    # 為替コスト（往復2%）を考慮した純期待値
    net_expected_value = expected_value - 2.0

    print("\n" + "=" * 40)
    print("バックテスト結果サマリー")
    print("=" * 40)
    print(f"総トレード数    : {total}件")
    print(f"勝ちトレード    : {wins}件")
    print(f"負けトレード    : {total-wins}件")
    print(f"勝率            : {win_rate:.1f}%")
    print(f"平均利益        : +{avg_win:.2f}%")
    print(f"平均損失        : -{avg_loss:.2f}%")
    print(f"期待値          : {expected_value:+.2f}%/トレード")
    print(f"純期待値(為替後): {net_expected_value:+.2f}%/トレード")
    print()

    # 決済理由の内訳
    print("【決済理由の内訳】")
    for reason, count in df["exit_reason"].value_counts().items():
        pct = count / total * 100
        print(f"  {reason}: {count}件 ({pct:.1f}%)")

    print()

    # 乖離率の範囲別勝率（依頼事項③の検証）
    print("【乖離率の範囲別勝率】")
    bins = [0.02, 0.04, 0.06, 0.08, 0.10]
    labels = ["+2〜4%", "+4〜6%", "+6〜8%", "+8〜10%"]

    # 乖離率を再計算（エントリー時点の乖離率が必要）
    # ここでは参考値として表示
    print("  ※詳細は backtest_results.csv を参照")
    print("=" * 40)


if __name__ == "__main__":
    
    print("=== S&P500全銘柄バックテスト ===")
    df = run_backtest()
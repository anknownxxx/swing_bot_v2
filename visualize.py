"""
visualize.py - バックテスト結果の可視化

backtest_results.csvを読み込んで
乖離率の範囲別・年別の勝率と期待値をグラフ化する。

なぜ可視化するか：
→ 数字だけでは「たまたまその期間に最適化されてるだけ」
  かどうかがわかりにくい
→ グラフにすると「汎用性があるか」が直感的にわかる
→ 特定の範囲だけ突出してたら過学習の疑いがある
→ 安定して似たような結果なら汎用性が高い
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# 日本語フォントの設定（文字化け対策）
plt.rcParams["font.family"] = "DejaVu Sans"


def load_data(filepath: str = "backtest_results.csv") -> pd.DataFrame:
    """
    CSVファイルを読み込んでデータを整形する関数。

    Args:
        filepath (str): CSVファイルのパス

    Returns:
        pd.DataFrame: 整形済みのトレードデータ
    """
    df = pd.read_csv(filepath)

    # entry_dateをdatetime型に変換
    # pd.to_datetime: 文字列を日付型に変換する関数
    df["entry_date"] = pd.to_datetime(df["entry_date"])

    # 年を新しいカラムとして追加
    df["year"] = df["entry_date"].dt.year

    # 勝敗フラグ（1=勝ち、0=負け）
    df["win"] = (df["pnl_pct"] > 0).astype(int)

    return df


def plot_yearly_stats(df: pd.DataFrame) -> None:
    """
    年別の勝率・期待値・トレード数をグラフ化する関数。

    3つのサブプロットを使って
    「年によって結果が安定してるか」を確認する。

    Args:
        df (pd.DataFrame): トレードデータ
    """
    # 年別集計
    # groupby: 年ごとにグループ化して集計
    yearly = df.groupby("year").agg(
        trades=("pnl_pct", "count"),
        win_rate=("win", "mean"),
        avg_win=("pnl_pct", lambda x: x[x > 0].mean()),
        avg_loss=("pnl_pct", lambda x: abs(x[x <= 0].mean()))
    ).reset_index()

    # 期待値の計算
    yearly["ev"] = (
        yearly["win_rate"] * yearly["avg_win"] -
        (1 - yearly["win_rate"]) * yearly["avg_loss"]
    )

    # グラフの作成
    # figsize: グラフ全体のサイズ（幅12, 高さ10）
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    fig.suptitle("Yearly Performance Analysis", fontsize=14, y=0.98)

    years = yearly["year"].astype(str)
    x = np.arange(len(years))

    # グラフ1: 年別勝率
    # 損益分岐点（33.3%）を赤線で表示
    axes[0].bar(x, yearly["win_rate"] * 100,
                color=["#2ecc71" if v >= 33.3 else "#e74c3c"
                       for v in yearly["win_rate"] * 100],
                alpha=0.8)
    axes[0].axhline(y=33.3, color="red", linestyle="--",
                    linewidth=1.5, label="Break-even (33.3%)")
    axes[0].set_title("Win Rate by Year")
    axes[0].set_ylabel("Win Rate (%)")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(years)
    axes[0].legend()
    axes[0].set_ylim(0, 60)

    # グラフ2: 年別期待値
    # プラスは緑・マイナスは赤で表示
    axes[1].bar(x, yearly["ev"],
                color=["#2ecc71" if v > 0 else "#e74c3c"
                       for v in yearly["ev"]],
                alpha=0.8)
    axes[1].axhline(y=0, color="black", linestyle="-", linewidth=0.8)
    axes[1].set_title("Expected Value by Year (%/trade)")
    axes[1].set_ylabel("Expected Value (%)")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(years)

    # グラフ3: 年別トレード数
    axes[2].bar(x, yearly["trades"],
                color="#3498db", alpha=0.8)
    axes[2].set_title("Number of Trades by Year")
    axes[2].set_ylabel("Trades")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(years)

    plt.tight_layout()
    plt.savefig("yearly_stats.png", dpi=150, bbox_inches="tight")
    print("yearly_stats.png を保存しました")
    plt.show()


def plot_deviation_analysis(df: pd.DataFrame) -> None:
    """
    乖離率の範囲別の勝率・期待値を比較するグラフ。

    「どの乖離率の範囲で勝ちやすいか」を確認する。
    特定の範囲だけ突出してたら過学習の疑いがある。

    Args:
        df (pd.DataFrame): トレードデータ
    """
    # 乖離率ビンの定義
    # pd.cut: 連続値を指定した区間に分類する関数
    bins = [-0.10, 0.00, 0.03, 0.05, 0.08, 0.10, 0.15]
    labels = ["<0%", "0-3%", "3-5%", "5-8%", "8-10%", ">10%"]

    # エントリー時の乖離率が必要だが
    # CSVには保存されていないため
    # pnl_pctの分布で代替分析する
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle("PnL Distribution Analysis", fontsize=14)

    # グラフ1: 損益率の分布ヒストグラム
    # alpha: 透明度（0=透明、1=不透明）
    axes[0].hist(df["pnl_pct"], bins=50,
                 color="#3498db", alpha=0.7, edgecolor="white")
    axes[0].axvline(x=0, color="black", linestyle="-", linewidth=1)
    axes[0].axvline(x=df["pnl_pct"].mean(), color="red",
                    linestyle="--", linewidth=1.5,
                    label=f"Mean: {df['pnl_pct'].mean():.2f}%")
    axes[0].set_title("PnL Distribution")
    axes[0].set_xlabel("PnL (%)")
    axes[0].set_ylabel("Count")
    axes[0].legend()

    # グラフ2: 決済理由の内訳（円グラフ）
    reason_counts = df["exit_reason"].value_counts()
    colors = ["#2ecc71", "#e74c3c", "#f39c12", "#3498db"]
    axes[1].pie(reason_counts.values,
                labels=reason_counts.index,
                colors=colors,
                autopct="%1.1f%%",
                startangle=90)
    axes[1].set_title("Exit Reason Distribution")

    plt.tight_layout()
    plt.savefig("pnl_distribution.png", dpi=150, bbox_inches="tight")
    print("pnl_distribution.png を保存しました")
    plt.show()


def plot_cumulative_pnl(df: pd.DataFrame) -> None:
    """
    累積損益の推移グラフ。

    時系列で「資産がどう増減したか」を可視化する。
    2022年のような悪い年が視覚的にわかる。

    Args:
        df (pd.DataFrame): トレードデータ
    """
    # entry_dateでソートして累積損益を計算
    df_sorted = df.sort_values("entry_date").copy()

    # cumsum(): 累積和を計算する関数
    df_sorted["cumulative_pnl"] = df_sorted["pnl_pct"].cumsum()

    fig, ax = plt.subplots(figsize=(14, 6))

    ax.plot(df_sorted["entry_date"],
            df_sorted["cumulative_pnl"],
            color="#3498db", linewidth=1.5, alpha=0.8)
    ax.axhline(y=0, color="black", linestyle="-", linewidth=0.8)
    ax.fill_between(df_sorted["entry_date"],
                    df_sorted["cumulative_pnl"],
                    0,
                    where=df_sorted["cumulative_pnl"] >= 0,
                    alpha=0.3, color="#2ecc71", label="Profit")
    ax.fill_between(df_sorted["entry_date"],
                    df_sorted["cumulative_pnl"],
                    0,
                    where=df_sorted["cumulative_pnl"] < 0,
                    alpha=0.3, color="#e74c3c", label="Loss")

    ax.set_title("Cumulative PnL Over Time")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative PnL (%)")
    ax.legend()

    # 年の境界線を追加
    for year in df_sorted["year"].unique():
        year_start = pd.Timestamp(f"{year}-01-01")
        ax.axvline(x=year_start, color="gray",
                   linestyle="--", linewidth=0.5, alpha=0.5)
        ax.text(year_start, ax.get_ylim()[1] * 0.95,
                str(year), fontsize=8, color="gray")

    plt.tight_layout()
    plt.savefig("cumulative_pnl.png", dpi=150, bbox_inches="tight")
    print("cumulative_pnl.png を保存しました")
    plt.show()

def calculate_confidence_interval(df: pd.DataFrame) -> None:
    """
    勝率の95%信頼区間を計算する関数。

    二項分布の正規近似を使用する。
    サンプル数が十分大きい（n>30）場合に有効。

    数式:
    CI = p ± 1.96 × √(p(1-p)/n)

    Args:
        df (pd.DataFrame): トレードデータ
    """
    n = len(df)
    p = (df["pnl_pct"] > 0).mean()
    
    # 標準誤差
    # √(p(1-p)/n): 二項分布の標準偏差をサンプル数で割ったもの
    se = np.sqrt(p * (1 - p) / n)
    
    # 95%信頼区間（z=1.96）
    ci_lower = p - 1.96 * se
    ci_upper = p + 1.96 * se
    
    # 損益分岐点
    breakeven = 1 / (1 + TAKE_PROFIT / STOP_LOSS)
    
    print("\n=== 統計的優位性の検証 ===")
    print(f"サンプル数    : {n:,}件")
    print(f"勝率（点推定）: {p*100:.1f}%")
    print(f"95%信頼区間  : {ci_lower*100:.1f}% 〜 {ci_upper*100:.1f}%")
    print(f"損益分岐点   : {breakeven*100:.1f}%")
    print()
    
    if ci_lower > breakeven:
        print(f"✅ 統計的に有意（信頼区間の下限{ci_lower*100:.1f}% > "
              f"損益分岐点{breakeven*100:.1f}%）")
        print(f"→ 95%の確率で勝率は損益分岐点を上回る")
    else:
        print(f"⚠️ 統計的に有意でない可能性")
        print(f"→ 信頼区間が損益分岐点を下回っている")
    
    print()
    print("【限界の明記】")
    print("・生存者バイアス: 現在のS&P500銘柄のみで検証")
    print("・過去への適合: この数字が将来も続く保証はない")
    print("・信頼区間はサンプリング誤差のみを考慮")
    print("  （モデルの誤特定・市場環境の変化は含まない）")


if __name__ == "__main__":
    print("=== バックテスト結果の可視化 ===")

    # データの読み込み
    df = load_data("backtest_results.csv")
    print(f"総トレード数: {len(df)}件")

    # 3種類のグラフを生成
    print("\n1. 年別パフォーマンス...")
    plot_yearly_stats(df)

    print("\n2. 損益分布...")
    plot_deviation_analysis(df)

    print("\n3. 累積損益の推移...")
    plot_cumulative_pnl(df)

    print("\n4. 統計的優位性の検証...")
    from config import TAKE_PROFIT, STOP_LOSS
    calculate_confidence_interval(df)

    print("\n全グラフの生成完了！")
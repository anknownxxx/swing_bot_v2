"""
kelly.py - ケリー基準によるポジションサイズ計算モジュール

ケリー基準とは:
  長期的な資産成長を最大化するための「最適な賭け金の割合」を
  数学的に求める公式。1956年にジョン・ケリーが考案。

  Kelly% = 勝率 - (負け率 / RR比)

  例: 勝率55%・RR比2.0の場合
  Kelly% = 0.55 - (0.45 / 2.0) = 0.325 → 資金の32.5%

なぜハーフケリーを使うか:
  フルケリーは理論上最適だが、実際は以下の問題がある
  - 勝率の推定誤差が大きい（バックテストと実運用は違う）
  - ドローダウンが大きくなりやすい
  - 心理的に耐えにくい
  → 安全のため0.5を掛けた「ハーフケリー」が実務では一般的
"""

from config import (
    KELLY_FRACTION,
    TAKE_PROFIT,
    STOP_LOSS,
    MAX_POSITIONS
)


def calculate_kelly(
    win_rate: float,
    rr_ratio: float,
    kelly_fraction: float = KELLY_FRACTION
) -> float:
    """
    ケリー基準の推奨投資割合を計算する関数。

    Args:
        win_rate (float): 勝率（例: 0.55 = 55%）
        rr_ratio (float): リスクリワード比（例: 2.0 = 利確/損切り）
        kelly_fraction (float): 安全係数（デフォルト: 0.5 = ハーフケリー）

    Returns:
        float: 総資金に対する推奨投資割合（例: 0.15 = 15%）
        
    Note:
        計算結果がマイナスの場合はこの戦略でのトレードを推奨しない
        最大値は1ポジションあたり総資金の20%に制限する
    """
    # 負け率 = 1 - 勝率
    loss_rate: float = 1.0 - win_rate

    # ケリー基準の計算式
    # 勝率が高いほど・RR比が高いほど投資割合が増える
    kelly_pct: float = win_rate - (loss_rate / rr_ratio)

    # マイナスの場合はこの戦略での投資を推奨しない
    if kelly_pct <= 0:
        return 0.0

    # ハーフケリーを適用（安全係数を掛ける）
    adjusted_kelly: float = kelly_pct * kelly_fraction

    # 1ポジションあたりの上限を20%に設定
    # 集中投資によるリスクを避けるため
    MAX_SINGLE_POSITION: float = 0.20
    return min(adjusted_kelly, MAX_SINGLE_POSITION)


def calculate_position_size(
    total_capital_jpy: float,
    win_rate: float,
    current_positions: int,
    usdjpy_rate: float
) -> dict:
    """
    1回のトレードで投資すべき金額を計算する関数。

    ケリー基準に加えて、同時保有銘柄数による分散も考慮する。
    保有銘柄が多いほど1銘柄あたりの投資額を減らす。

    Args:
        total_capital_jpy (float): 総資金（円）
        win_rate (float): バックテストで得た勝率（例: 0.55）
        current_positions (int): 現在の保有銘柄数
        usdjpy_rate (float): 現在のドル円レート

    Returns:
        dict: 推奨投資額の情報
            {
                "kelly_pct": float,      # ケリー基準の投資割合
                "position_jpy": float,   # 推奨投資額（円）
                "position_usd": float,   # 推奨投資額（ドル）
                "max_loss_jpy": float,   # 最大損失額（円）
                "note": str              # 補足メッセージ
            }
    """
    # RR比を config から計算
    # 利確幅 / 損切り幅 = 6% / 3% = 2.0
    rr_ratio: float = TAKE_PROFIT / STOP_LOSS

    # ケリー基準で推奨投資割合を計算
    kelly_pct: float = calculate_kelly(win_rate, rr_ratio)

    if kelly_pct <= 0:
        return {
            "kelly_pct": 0.0,
            "position_jpy": 0.0,
            "position_usd": 0.0,
            "max_loss_jpy": 0.0,
            "note": "⚠️ この戦略の期待値がマイナスのため投資推奨なし"
        }

    # 同時保有銘柄数を考慮した分散調整
    # 例: MAX_POSITIONS=10、現在3銘柄保有の場合
    # 残り枠 = 10 - 3 = 7銘柄
    # 分散係数 = 1 / 10 = 0.1（1銘柄あたり最大10%）
    remaining_slots: int = MAX_POSITIONS - current_positions
    if remaining_slots <= 0:
        return {
            "kelly_pct": 0.0,
            "position_jpy": 0.0,
            "position_usd": 0.0,
            "max_loss_jpy": 0.0,
            "note": f"⚠️ 最大保有数（{MAX_POSITIONS}銘柄）に達しています"
        }

    # 分散投資の観点から1銘柄あたりの上限を設定
    # 総資金をMAX_POSITIONSで割った額が1銘柄あたりの上限
    diversification_pct: float = 1.0 / MAX_POSITIONS

    # ケリー基準と分散投資の小さい方を採用
    # → より保守的な投資額を選ぶ
    final_pct: float = min(kelly_pct, diversification_pct)

    # 円建ての投資額を計算
    position_jpy: float = total_capital_jpy * final_pct

    # ドル建ての投資額を計算（円÷ドル円レート）
    position_usd: float = position_jpy / usdjpy_rate

    # 最大損失額（損切り-3%が発動した場合）
    max_loss_jpy: float = position_jpy * STOP_LOSS

    return {
        "kelly_pct": round(final_pct * 100, 1),
        "position_jpy": round(position_jpy),
        "position_usd": round(position_usd, 2),
        "max_loss_jpy": round(max_loss_jpy),
        "note": (
            f"ケリー基準: {kelly_pct*100:.1f}% / "
            f"分散上限: {diversification_pct*100:.1f}% / "
            f"採用: {final_pct*100:.1f}%"
        )
    }


if __name__ == "__main__":
    """
    動作確認用テストコード。
    """
    print("=== kelly.py 動作確認 ===\n")

    # テストパラメータ
    TOTAL_CAPITAL = 100000    # 総資金10万円
    WIN_RATE = 0.55           # 仮の勝率55%
    CURRENT_POSITIONS = 3     # 現在3銘柄保有
    USDJPY = 150.0            # ドル円レート

    result = calculate_position_size(
        total_capital_jpy=TOTAL_CAPITAL,
        win_rate=WIN_RATE,
        current_positions=CURRENT_POSITIONS,
        usdjpy_rate=USDJPY
    )

    print(f"総資金        : ¥{TOTAL_CAPITAL:,}")
    print(f"勝率          : {WIN_RATE*100:.0f}%")
    print(f"RR比          : {TAKE_PROFIT/STOP_LOSS:.1f}")
    print(f"現在の保有数  : {CURRENT_POSITIONS}銘柄")
    print(f"ドル円レート  : {USDJPY}")
    print()
    print(f"推奨投資割合  : {result['kelly_pct']}%")
    print(f"推奨投資額    : ¥{result['position_jpy']:,}")
    print(f"推奨投資額($) : ${result['position_usd']:,}")
    print(f"最大損失額    : ¥{result['max_loss_jpy']:,}")
    print(f"補足          : {result['note']}")
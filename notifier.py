"""
notifier.py - Gmail通知モジュール

このシステムの「出口」となるモジュール。
他のモジュールが検知した情報をGmailに送信する責務だけを持つ。
通知の種類（損切り・利確・スクリーニング）に関わらず、
すべてこのモジュールを経由することで通知ロジックを一元管理する。
"""

import smtplib
import os
from email.mime.text import MIMEText
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
# 認証情報をコードに直接書くとGitHubに漏洩するリスクがあるため
# 環境変数として外部ファイルで管理する
load_dotenv()

# 環境変数からGmailの認証情報を取得
GMAIL_ADDRESS: str = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")


def send_email(subject: str, body: str) -> bool:
    """
    Gmailでメールを送信する関数。

    SMTPプロトコル（Simple Mail Transfer Protocol）を使用して
    Googleのメールサーバー経由でメールを送信する。
    SSL暗号化（ポート465）を使用してセキュアに通信する。

    Args:
        subject (str): メールの件名
        body (str): メールの本文

    Returns:
        bool: 送信成功=True、失敗=False

    Note:
        Googleアカウントの「アプリパスワード」が必要。
        通常のパスワードでは認証エラーになる。
    """
    # 認証情報が設定されているか確認
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("エラー: .envにGmailの認証情報が設定されていません")
        return False

    # MIMEText: メールの形式を定義するオブジェクト
    # "plain"はプレーンテキスト形式（HTMLなし）
    # "utf-8"は日本語を含む文字コード
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS  # 自分自身に送信

    try:
        # SMTP_SSL: SSL暗号化した状態でSMTPサーバーに接続
        # smtp.gmail.com: GmailのSMTPサーバーアドレス
        # 465: SSL用のポート番号
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)

        print(f"✅ Gmail送信完了: {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("エラー: Gmail認証失敗。アプリパスワードを確認してください")
        return False

    except smtplib.SMTPException as e:
        print(f"エラー: メール送信失敗 → {e}")
        return False


def send_alert(ticker: str, current_price: float,
               purchase_price: float, pct_change: float,
               alert_type: str) -> bool:
    """
    損切り・利確・強制決済のアラートを送信する関数。

    Args:
        ticker (str): 銘柄コード（例: "AAPL"）
        current_price (float): 現在の株価（ドル）
        purchase_price (float): 購入単価（ドル）
        pct_change (float): 購入単価からの変化率（例: -0.03 = -3%）
        alert_type (str): アラートの種類
            "stop_loss"   → 損切りアラート
            "take_profit" → 利確アラート
            "force_exit"  → 強制決済アラート

    Returns:
        bool: 送信成功=True、失敗=False
    """
    # アラートの種類に応じてメッセージを切り替える
    alert_config = {
        "stop_loss": {
            "emoji": "🚨",
            "label": "損切りアラート",
            "action": "Woodstockで売却を検討してください"
        },
        "take_profit": {
            "emoji": "✅",
            "label": "利確アラート",
            "action": "Woodstockで売却を検討してください"
        },
        "force_exit": {
            "emoji": "⏰",
            "label": "強制決済アラート",
            "action": "保有期間超過のため売却を検討してください"
        }
    }

    config = alert_config.get(alert_type, alert_config["stop_loss"])

    subject = f"{config['emoji']} {config['label']}: {ticker}"

    body = f"""
{config['emoji']} {config['label']}
{"─" * 30}
銘柄     : {ticker}
現在値   : ${current_price:.2f}
購入単価 : ${purchase_price:.2f}
損益率   : {pct_change * 100:+.2f}%
{"─" * 30}
{config['action']}
    """.strip()

    return send_email(subject, body)


def send_weekly_report(candidates: list,
                       portfolio_summary: dict) -> bool:
    """
    週次スクリーニング結果と保有銘柄サマリーをGmailで送信する関数。

    Args:
        candidates (list): スクリーニングで抽出した買い候補銘柄のリスト
            各要素は辞書形式:
            {
                "ticker": str,        # 銘柄コード
                "price": float,       # 現在値（ドル）
                "deviation": float,   # 乖離率（例: 0.05 = +5%）
                "vol_ratio": float,   # 出来高比率（例: 1.8 = 1.8倍）
                "kelly_size": float   # 推奨投資額（円）
            }
        portfolio_summary (dict): 保有銘柄の損益サマリー
            {
                "total_jpy": float,   # 総評価額（円）
                "total_pnl": float,   # 総損益率
                "positions": list     # 各保有銘柄の情報
            }

    Returns:
        bool: 送信成功=True、失敗=False
    """
    from datetime import datetime
    today = datetime.now().strftime("%Y/%m/%d")

    subject = f"📊 週次レポート {today} - 買い候補{len(candidates)}銘柄"

    # 保有銘柄サマリーの作成
    body = f"📊 週次レポート {today}\n"
    body += "=" * 35 + "\n\n"

    # 保有銘柄の状況
    body += "【保有銘柄】\n"
    if portfolio_summary.get("positions"):
        for pos in portfolio_summary["positions"]:
            emoji = "✅" if pos["pnl"] >= 0 else "⚠️"
            body += (
                f"{emoji} {pos['ticker']}: "
                f"{pos['pnl']:+.1f}% "
                f"(${pos['current_price']:.2f})\n"
            )
    else:
        body += "保有銘柄なし\n"

    body += "\n" + "─" * 35 + "\n\n"

    # 買い候補銘柄
    body += "【今週の買い候補】\n"
    if candidates:
        for i, c in enumerate(candidates[:10], 1):
            body += (
                f"{i}. {c['ticker']}\n"
                f"   現在値   : ${c['price']:.2f}\n"
                f"   乖離率   : {c['deviation'] * 100:+.1f}%\n"
                f"   出来高比率: {c['vol_ratio']:.1f}x\n"
                f"   推奨投資額: ¥{c['kelly_size']:,.0f}\n"
                f"   損切り目安: ${c['price'] * 0.97:.2f}（-3%）\n\n"
            )
    else:
        body += "今週の買い候補はありません\n"
        body += "（市場環境フィルターにより見送り）\n"

    body += "─" * 35 + "\n"
    body += "※損切りはWoodstockの逆指値注文で設定してください"

    return send_email(subject, body)


if __name__ == "__main__":
    """
    動作確認用のテストコード。
    このファイルを直接実行した時だけ動く（importした時は動かない）。
    """
    print("=== notifier.py 動作確認 ===")

    # テスト1: 損切りアラート
    send_alert(
        ticker="AAPL",
        current_price=145.20,
        purchase_price=150.00,
        pct_change=-0.032,
        alert_type="stop_loss"
    )

    # テスト2: 週次レポート
    test_candidates = [
        {
            "ticker": "MSFT",
            "price": 380.50,
            "deviation": 0.045,
            "vol_ratio": 1.8,
            "kelly_size": 3500
        }
    ]
    test_summary = {
        "positions": [
            {
                "ticker": "AAPL",
                "pnl": -3.2,
                "current_price": 145.20
            }
        ]
    }
    send_weekly_report(test_candidates, test_summary)
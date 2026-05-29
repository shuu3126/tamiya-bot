import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent
)
import anthropic
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

configuration = Configuration(access_token=os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
claude = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

# ユーザーごとの会話履歴（メモリ）
conversations = {}

SYSTEM_PROMPT = """あなたはIT・業務改善の専門家として、企業の業務課題をヒアリングし、最適なICTソリューションを提案するコンサルタントです。

【基本姿勢】
- 丁寧なビジネス敬語を使用する
- 押し売りはしない。相手が自然と「こういうシステムが欲しい」と感じるよう会話を導く
- 共感を示しながら課題を深掘りし、具体的な解決策をイメージさせる

【ヒアリングの進め方】
効率よく情報を集めるため、関連する質問は1〜2つまとめて聞く。全体で4〜5往復を目安にする。

ターン1：プロフィール確認
→ お名前・会社名・業種・役職をまとめて確認

ターン2：業務状況の把握
→ 社員数・現在使用しているITツール・管理方法をまとめて確認

ターン3：シナリオ提示で課題を引き出す
「困っていることは？」と直接聞かない。以下のようなシナリオを2〜3個提示して「当てはまるものはありますか？」と聞く。

業種・規模に合わせて以下から選んで提示する：
・「お客様の情報をエクセルや紙で管理していて、探すのに時間がかかる」
・「見積書・請求書の作成が手作業で、ミスや手間がかかっている」
・「社員の勤怠管理がアナログで、集計が大変」
・「お客様からの問い合わせ対応に追われて、本来の業務が進まない」
・「在庫や発注の管理がバラバラで、気づいたら在庫切れになっていた」
・「スタッフへの連絡がLINEや口頭で、情報共有が抜け漏れる」
・「ホームページがなく、新規のお客様に見つけてもらえない」

相手が「それある！」と反応したら、その課題を深掘りする。

ターン4：理想の確認＋気づきの提供
→ 「それが解決したら、どんなふうに変わりそうですか？」
→ 「実は、そのような場合に使いやすいツールがあります。また、御社に合わせた専用システムを作るという選択肢もございます」と自然につなぐ

ターン5：診断レポートを出力する

【診断レポートの形式】

━━━━━━━━━━━━━━━━━━━━━━
　　業務改善 ICT診断レポート
━━━━━━━━━━━━━━━━━━━━━━

■ ご担当者さま情報
氏名：〇〇 様　／　会社名：〇〇　／　役職：〇〇

■ 現状と課題の整理
（ヒアリング内容をもとに、課題を簡潔に整理）

■ おすすめITツール・サービス

① ツール名
　・推奨理由：
　・期待効果：
　・費用目安：

② ツール名
　・推奨理由：
　・期待効果：
　・費用目安：

■ オーダーメイドシステムのご提案
ヒアリングの内容から、御社の業務に特化した以下のようなシステムを構築することで、より根本的な課題解決が期待できます。

「〇〇管理システム」（例）
　・解決できること：
　・主な機能：
　　- 〇〇
　　- 〇〇
　・導入することで：（ビフォーアフターを簡潔に）

ご興味がございましたら、詳細なご提案・お見積りをさせていただきます。お気軽にご連絡ください。

■ 推奨する最初のステップ
〇〇から着手されることをおすすめいたします。

━━━━━━━━━━━━━━━━━━━━━━

【厳守事項】
- 回答は簡潔にまとめ、不要な繰り返しをしない
- 専門用語は使わず、平易な言葉で説明する
- レポート出力後は「ご不明な点はございますか？」と一言添える"""

GREETING = """はじめまして。業務改善・ICT活用の無料診断サービスです。

いくつかご質問させていただき、御社の業務効率化に役立つツールやシステムをご提案いたします。

まず、お名前・会社名・業種・ご役職を教えていただけますか？"""


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    conversations[user_id] = []
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message_with_http_info(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=GREETING)]
            )
        )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    # リセットコマンド
    if user_message.strip() in ['リセット', 'reset', 'Reset']:
        conversations[user_id] = []
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text='会話をリセットしました！\n\n' + GREETING)]
                )
            )
        return

    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({
        "role": "user",
        "content": user_message
    })

    recent = conversations[user_id][-10:]
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=recent
    )

    reply_text = response.content[0].text

    conversations[user_id].append({
        "role": "assistant",
        "content": reply_text
    })

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


@app.route("/", methods=['GET'])
def index():
    return 'Bot is running!'


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

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

SYSTEM_PROMPT = """あなたは企業の業務課題をヒアリングする優秀なITコンサルタントAIです。
フレンドリーで親しみやすい口調で会話しながら、以下の情報を自然に引き出してください：

1. 会社の事業内容・業種
2. 社員数・規模
3. 今困っていること・課題（業務の非効率、情報管理、顧客対応、売上など）
4. 現在使っているITツール・システム（エクセル、紙管理、特定のソフトなど）
5. 特に時間がかかっている業務
6. 将来の目標・やりたいこと

ルール：
- 質問は必ず1つずつ、会話の流れに合わせて自然に聞く
- 相手の回答に共感・リアクションしてから次の質問へつなぐ
- 5〜7往復で十分な情報が集まったら「診断レポート」を出す
- レポートは以下の形式で出す：

---
📋 業務改善 診断レポート
---
【御社の状況まとめ】
（ヒアリング内容を簡潔にまとめる）

【おすすめシステム・ソフト・HP】
① xxxxxx
　→ 理由：〜〜〜
　→ 期待効果：〜〜〜

② xxxxxx
　→ 理由：〜〜〜
　→ 期待効果：〜〜〜

（3〜5個提案）

【優先度が高いもの】
まず〜〜から始めることをおすすめします。
---"""

GREETING = """はじめまして！業務改善AI診断ボットです😊

御社に合ったシステム・ソフト・ホームページを無料で診断します。
いくつか質問させてください！

まず教えてください👇
どんなお仕事をされている会社ですか？"""


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

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=conversations[user_id]
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

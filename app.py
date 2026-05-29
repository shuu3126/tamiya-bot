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

SYSTEM_PROMPT = """あなたは中小企業のICT活用を支援する、経験豊富なITコンサルタントです。
まだデジタル化があまり進んでいない企業を主な対象とし、業務上の悩みや非効率を丁寧にヒアリングしながら、実用的なICTソリューションを提案します。

【ヒアリング手順】
以下の項目を、会話の流れに沿って自然に引き出してください。順番は柔軟に調整してかまいません。

① 担当者プロフィール（お名前・会社名・役職）
② 業種・事業内容
③ 会社の規模（社員数・拠点数など）
④ 現在の業務で最も支障を感じていること（具体的なエピソードを引き出す）
⑤ 現在使用しているITツール・管理方法（エクセル・紙・特定ソフトなど）
⑥ 理想の状態・解決したいこと

【会話ルール】
- 質問は必ず1つずつ行い、相手の回答に対して共感や確認を示してから次の質問へ進む
- 「それは大変でしたね」「具体的にはどんな場面ですか？」など、相手の話を深掘りする
- 相手が課題を話してくれたら「実はそういったお悩みを解決できるツールがあります」と自然につなぐ
- 6〜8往復で必要な情報が揃ったら診断レポートを出力する

【診断レポートの形式】
必ず以下の構成で出力してください。文体は丁寧なビジネス敬語を使用すること。

━━━━━━━━━━━━━━━━━━━━━━
　　業務改善 ICT診断レポート
━━━━━━━━━━━━━━━━━━━━━━

■ ご担当者さま情報
氏名：〇〇 様
会社名：株式会社〇〇
役職：〇〇

■ 御社の現状と課題
（ヒアリング内容をもとに、課題を整理して記述）

■ おすすめICTソリューション

【既存ツール・サービスの活用】
① ツール名
　・おすすめ理由：
　・導入効果：
　・目安費用：

② ツール名
　・おすすめ理由：
　・導入効果：
　・目安費用：

【カスタムシステム開発のご提案】
現状の課題を踏まえると、以下のようなシステムがあると業務効率が大幅に向上すると考えられます。

「〇〇管理システム」（仮称）
　・概要：（どんなシステムか）
　・解決できること：（具体的に）
　・想定機能：（箇条書き）

■ 優先アクション
まず〇〇から着手されることをおすすめいたします。
ご不明な点がございましたら、お気軽にご相談ください。

━━━━━━━━━━━━━━━━━━━━━━"""

GREETING = """はじめまして。業務改善ICT診断サービスをご利用いただきありがとうございます。

当サービスでは、いくつかのご質問を通じて御社の現状と課題を把握し、業務効率化に役立つITツールやシステムを無料でご提案いたします。

まず、担当者さまのお名前と会社名を教えていただけますか？"""


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

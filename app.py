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

SYSTEM_PROMPT = """あなたはIT・システム開発に詳しい、気さくで頼れる相談役です。
堅苦しくなく、でも的確。友人のIT詳しい人に相談している感覚で話せるのがあなたの強みです。

【あなたのゴール】
相手が「こんなシステムがあったら最高だ」と感じ、自然に相談・依頼につながること。
売り込みは絶対にしない。相手が自分で「欲しい」と思うように会話を進める。

【会話の進め方】

STEP1：まず仲良くなる
- 相手の名前・会社・仕事を聞く
- 「どんなお仕事されてるんですか？」くらいの気軽さで

STEP2：日常の大変さを引き出す
- 「最近、仕事でこれがしんどいな〜ってことありますか？」
- 「一番時間かかってる作業ってどんなことですか？」
- 相手が話したことに「あーそれわかります」「それは大変ですね」と共感してから深掘り
- 「具体的にどんな場面で困りますか？」「今はどうやって対応してますか？」

STEP3：気づきを与える（ここが一番大事）
相手が課題を話してくれたら、押し付けず「もしこういう仕組みがあったら」と想像させる。
例：
- 「あ、それって実は、〇〇を自動化できるシステムがあれば一発で解決するんですよね」
- 「そういう場合、〇〇みたいな機能があると、毎日30分は楽になりそうですよね」
- 「〇〇ってソフト、ご存知ですか？まさにそれ向けで使いやすいんですよ」

STEP4：既存ツール＋オーダーメイドの両方を提案
- まず使えるソフト・サービスを紹介（具体名・料金感・効果）
- そのあと「でも正直、御社の業務に完全に合わせたシステムを作るのが一番スッキリするかもしれないですね」と自然につなぐ

STEP5：診断レポートを出す（8往復前後で）
情報が揃ったら以下の形式でレポートを出力する。

━━━━━━━━━━━━━━━━━━━━━━
業務改善レポート
━━━━━━━━━━━━━━━━━━━━━━

お話を伺って、整理してみました！

【お聞きした内容】
・（名前・会社・仕事の内容をまとめる）

【一番の課題】
・（相手が話してくれた悩みを具体的に整理）

【すぐ使えるツール】
① ツール名
　→ なぜおすすめか（1〜2行）
　→ 月額費用の目安

② ツール名
　→ なぜおすすめか
　→ 月額費用の目安

【こんなシステムがあったら最強です】
「〇〇自動化システム」（仮称）
→ これがあると：（具体的なビフォーアフター）
→ 主な機能イメージ：
　・〇〇
　・〇〇
　・〇〇
→ 「これ、作れます」系のシステムです。ご興味があればぜひ一度ちゃんとお話しましょう！

【まず一歩】
〇〇から始めてみるのがおすすめです。
何か気になる点があれば、引き続き何でも聞いてください！

━━━━━━━━━━━━━━━━━━━━━━

【絶対守ること】
- 質問は1回に1つだけ
- 相手の言葉を受け止めてから次へ進む
- 「売ります」感を出さない。あくまで相談に乗るスタンス
- 専門用語は使わない。小学生でもわかる言葉で"""

GREETING = """こんにちは！業務の効率化やIT活用について、気軽に相談できるサービスです😊

「こんなこと聞いていいの？」ってことでも全然OKなので、ざっくばらんに話しましょう！

まず、どんなお仕事をされているか教えてもらえますか？"""


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

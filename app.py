import os
import json
import re
from datetime import datetime
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
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = '12-QXsEG7m0SqLi7ZXJ67b5yl84-SbMdFE1pt9GCYueo'

def get_sheet():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        return None
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).get_worksheet(0)

def save_lead(reply_text, history):
    try:
        ws = get_sheet()
        if not ws:
            return
        name = company = role = industry = headcount = issue = numbers = proposal = ''
        for line in reply_text.split('\n'):
            if '氏名：' in line:
                name = line.split('氏名：')[-1].split('　')[0].replace('様', '').strip()
            elif '会社名：' in line:
                company = line.split('会社名：')[-1].split('　')[0].strip()
            elif '役職：' in line:
                role = line.split('役職：')[-1].strip()
        for msg in history:
            if msg['role'] == 'user':
                text = msg['content']
                if any(k in text for k in ['業', '会社', '仕事']):
                    industry = text[:30]
        numbers_match = re.findall(r'週\S+時間|年間\S+時間|\d+時間', reply_text)
        numbers = ' / '.join(numbers_match[:3])
        issue_start = reply_text.find('現状と課題')
        proposal_start = reply_text.find('オーダーメイドシステム')
        if issue_start != -1:
            issue = reply_text[issue_start:issue_start+100].replace('\n', ' ').strip()
        if proposal_start != -1:
            proposal = reply_text[proposal_start:proposal_start+80].replace('\n', ' ').strip()
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        ws.append_row([now, name, company, role, industry, headcount, issue, numbers, proposal, '未対応'])
    except Exception as e:
        print(f'スプレッドシート書き込みエラー: {e}')

app = Flask(__name__)

configuration = Configuration(access_token=os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
claude = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

# ユーザーごとの会話履歴（メモリ）
conversations = {}

SYSTEM_PROMPT = """あなたは中小企業の業務改善・システム開発を専門とするITコンサルタントです。
丁寧なビジネス敬語で話しながら、相手の業務の痛みを具体的な数字で引き出し、最終的に「30分の無料相談」のアポを獲得することがゴールです。

【会話の流れ（全5ターン厳守）】

▼ターン1：プロフィール確認
お名前・会社名・業種・役職・社員数をまとめて確認する。

▼ターン2：現状把握
以下を1つのメッセージでまとめて聞く。
「現在、業務管理にはどんなツールをお使いですか？（エクセル・紙・専用ソフトなど）また、社内でデジタル化が進んでいない部分はどのあたりでしょうか？」

▼ターン3：シナリオ提示で課題を引き出す
「困っていることは？」と直接聞かず、業種に合わせて以下から2〜3個を選んで提示する。

・顧客情報をエクセルや紙で管理していて、探すのに時間がかかる
・見積書・請求書の作成が手作業で、ミスや確認作業が多い
・勤怠管理がアナログで、月末の集計が大変
・問い合わせ対応に追われて、本来の業務が進まない
・在庫・発注管理がバラバラで、欠品やロスが起きやすい
・スタッフへの連絡や情報共有が口頭・LINEで、抜け漏れがある
・ホームページがなく、新規顧客に見つけてもらえない

「このうち、心当たりのあるものはございますか？」と聞く。

▼ターン4：痛みを数値化して深掘りする
相手が課題を話してくれたら、以下で必ず数値を引き出す。
・「それは週にどのくらいの時間がかかっていますか？」
・「ミスや抜け漏れが起きたとき、対応にどのくらいかかりますか？」
・「もし今の状態が続くと、どんな影響が出そうですか？」

数値が出たら「週〇時間 × 52週 = 年間〇〇時間のロスになりますね」と換算して見せる。
そのうえで「実は、そのような課題を丸ごと解決できる専用システムを構築することが可能です」と自然につなぐ。

▼ターン5：診断レポート＋アポ獲得
以下の形式でレポートを出力する。

━━━━━━━━━━━━━━━━━━━━━━
　　業務改善 ICT診断レポート
━━━━━━━━━━━━━━━━━━━━━━

■ ご担当者さま情報
氏名：〇〇 様　／　会社名：〇〇　／　役職：〇〇

■ 現状と課題
（ヒアリング内容を整理。数値を必ず含める）
例：「〇〇の管理に週〇時間、年間約〇〇時間のコストが発生しています」

■ 御社に最適なシステムのご提案
「〇〇自動化システム」（仮称）

解決できること：
・〇〇が自動化され、週〇時間の削減が見込めます
・〇〇のミスがなくなり、確認作業が不要になります

主な機能：
・〇〇
・〇〇
・〇〇

導入後のイメージ：
現在：〇〇に毎週〇時間 → 導入後：ボタン1つで完了

■ 次のステップ
御社の業務に合わせた詳細なご提案と概算お見積りを、30分の無料オンライン相談でご説明いたします。

👉 ご相談のご予約はこちら
CALENDAR_URL

ご都合のよい日時をお選びいただくだけで、担当者からご連絡いたします。

━━━━━━━━━━━━━━━━━━━━━━

【厳守事項】
- 1ターンに聞くことは最大2項目まで
- 必ず数値（時間・回数・コスト）を引き出してからレポートを出す
- 専門用語は使わない
- レポートのCALENDAR_URLは必ずそのまま出力する（置き換えない）"""

GREETING = """はじめまして。業務改善・システム開発の無料診断サービスです。

いくつかご質問させていただき、御社の課題に合ったシステムをご提案いたします。所要時間は5分程度です。

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

    if '診断レポート' in reply_text:
        save_lead(reply_text, conversations[user_id])

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

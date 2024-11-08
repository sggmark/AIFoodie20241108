#要改的地方
#104行的aifoodie_url = 'https://www.google.com.tw/'  #這裡要改成LEO的網站網址
#153行的 static/richmenu_1.jpg 這裡可以改成你的richmenu圖片
#200~201 行  AI的提示語可以改成你想要的

import os
import sys
import tempfile
from configparser import ConfigParser
from flask import Flask, request, abort

from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    TemplateMessage,
    ButtonsTemplate,
    MessageAction,
    URIAction,
    MessagingApiBlob,
    MessageAction,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    CameraAction,
    CameraRollAction,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
    FollowEvent,
)
# Azure OpenAI
from openai import AzureOpenAI
import requests
import json
# Azure Computer Vision
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import VisualFeatureTypes, OperationStatusCodes
from msrest.authentication import CognitiveServicesCredentials


#取得所有環境變數 KEY 的值
config = ConfigParser()
config.read("config.ini")

app = Flask(__name__)
#LINE BOT 設定
CHANNEL_ACCESS_TOKEN = config['Line']['CHANNEL_ACCESS_TOKEN']
CHANNEL_SECRET = config['Line']['CHANNEL_SECRET']
if CHANNEL_SECRET is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if CHANNEL_ACCESS_TOKEN is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)
handler = WebhookHandler(CHANNEL_SECRET)
Configuration = Configuration(
    access_token=CHANNEL_ACCESS_TOKEN
)
#Azure OpenAI Key 設定
client = AzureOpenAI(
    api_key=config["AzureOpenAI_GPT4"]["KEY"],
    api_version=config["AzureOpenAI_GPT4"]["VERSION"],
    azure_endpoint=config["AzureOpenAI_GPT4"]["ENDPOINT"],
)

# Azure Compuer Vision 設定
vision_region = config["AzureComputerVision"]["REGION"]
vision_key = config["AzureComputerVision"]["KEY"]
vision_credentials = CognitiveServicesCredentials(vision_key)
vision_client = ComputerVisionClient(
    endpoint="https://" + vision_region + ".api.cognitive.microsoft.com/",
    credentials=vision_credentials,
)

UPLOAD_FOLDER = "static"

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# 加入好友事件
@handler.add(FollowEvent)
def handle_follow(event):
    print(f'Got {event.type} event')

# 訊息事件
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text
    
    if user_message == '@聊聊美食':
        reply_text = '歡迎使用AIFoodie智慧點餐機器人\n您可以問我任何美食相關的話題'
        with ApiClient(Configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
    elif user_message == '@掃描菜單':
        quickreply(event)
    else:
        reply_text=azure_openai(user_message)
        with ApiClient(Configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                )
            )

# 處理用戶上傳菜單圖片事件
@handler.add(MessageEvent, message=ImageMessageContent)
def message_image(event):
    with ApiClient(Configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        message_content = line_bot_blob_api.get_message_content(
            message_id=event.message.id
        )
        with tempfile.NamedTemporaryFile(
            dir=UPLOAD_FOLDER, prefix="", delete=False
        ) as tf:
            tf.write(message_content)
            tempfile_path = tf.name

    original_file_name = os.path.basename(tempfile_path)
    os.replace(
        UPLOAD_FOLDER + "/" + original_file_name,
        UPLOAD_FOLDER + "/" + "output.jpg",
    )
    global vision_result
    vision_result = azure_vision_get_text()
    gpt4v_result = openai_gpt4v_sdk(vision_result)
    #prompt_vision_result =  vision_result
    with ApiClient(Configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=gpt4v_result)
                    #TextMessage(text='請輸入菜單的語言，例如 英文、韓文、日文、俄文、泰文...。'),
                    #TextMessage(text='AI 正在快馬加鞭解析菜單圖片'+"\U0001F680"+'，請稍後...'),
                    ]
            )
        )

#rich_menu 圖文選單
def create_rich_menu():
    with ApiClient(Configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_blob_api = MessagingApiBlob(api_client)

        # Create rich menu
        aifoodie_url = " https://93c6-1-164-224-106.ngrok-free.app"  #這裡要改成LEO的網站網址
        headers = {
            'Authorization': 'Bearer ' + CHANNEL_ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        body = {
            "size": {
                "width": 2500,
                "height": 843
            },
            "selected": True,
            "name": "功能選單",
            "chatBarText": "功能選單",
            "areas": [
                {
                    "bounds": {
                        "x": 0,
                        "y": 0,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "uri",
                        "uri": aifoodie_url
                    },
                },
                {
                    "bounds": {
                        "x": 833,
                        "y": 0,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "@掃描菜單"
                    }
                },
                {
                    "bounds": {
                        "x": 1666,
                        "y": 0,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "@聊聊美食"
                    }
                },

            ]
        }

        response = requests.post('https://api.line.me/v2/bot/richmenu', headers=headers, data=json.dumps(body).encode('utf-8'))
        response = response.json()
        #
        # print(response)
        rich_menu_id = response["richMenuId"]
        
        # Upload rich menu image
        with open('static/richmenu_3.jpg', 'rb') as image:  #這裡可以改成你的richmenu圖片
            line_bot_blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=bytearray(image.read()),
                _headers={'Content-Type': 'image/jpeg'}
            )

        line_bot_api.set_default_rich_menu(rich_menu_id)
create_rich_menu()


#Azure OpenAI 處理@聊聊美食
def azure_openai(user_message):
    message_text = [
        {
            "role": "system",
            "content": "你是一個美食專家,你了解各種菜餚食譜、料理方式以及,搭配的佐料、飲料和酒類，請一律用繁體中文回答。"
        },
        {
            "role": "user", 
            "content": user_message
        },
    ]
    completion = client.chat.completions.create(
        model=config["AzureOpenAI_GPT4"]["GPT4V_DEPLOYMENT_NAME"],
        messages=message_text,
        temperature=0.4,
        max_tokens=800,
        top_p=0.95,
        frequency_penalty=0,
        presence_penalty=0,
        stop=None,
    )
    #print(completion)
    return completion.choices[0].message.content





#quickreply 處理用戶拍照或上傳圖片
def quickreply(event):
    with ApiClient(Configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        quickReply = QuickReply(
            items=[
                QuickReplyItem(
                    action=CameraAction(label="開啟鏡頭")
                ),
                QuickReplyItem(
                    action=CameraRollAction(label="選擇圖片")
                ),
            ]
        )        
    line_bot_api.reply_message(
            ReplyMessageRequest(#
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                    text='請選擇拍照或上傳圖片',
                    quick_reply=quickReply
                )
                ]
            )
        )
    
#處理電腦視覺獲得文字後，使用AI翻譯並整理清單
def openai_gpt4v_sdk(vision_result):
    #user_image_url = f"{config['Deploy']['WEBSITE']}/static/output.jpg"
    message_text = [
        {
            "role": "system",
            "content": "你是一個翻譯助理，你會將資料依照要求的格式翻譯並整理，使用繁體中文回答。"
            #"content": """你觀察入微，擅長觀察圖像，並詳細描述內容。使用繁體中文回答。"""
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f'這份資料，{vision_result}，請翻譯後並依格式 原文餐點名稱/ 中文餐點名稱/ $價格 整理成一份清單，一列一項餐點。'

                },
                ],
        },
    ]

    try:
        response = client.chat.completions.create(
            model=config["AzureOpenAI_GPT4"]["GPT4V_DEPLOYMENT_NAME"],
            messages=message_text,
            max_tokens=800,
            top_p=0.95,
        )
        #print(response)
        return response.choices[0].message.content
    except Exception as error:
        print("Error:", error)
        return "系統異常，請再試一次。"

#處理用戶拍照上傳
def azure_vision_get_text():
    url = config["Deploy"]["WEBSITE"] + "/static/" + "output.jpg"
    raw = True
    numberOfCharsInOperationId = 36

    # SDK call
    rawHttpResponse = vision_client.read(url, language="zh", raw=raw)

    # Get ID from returned headers
    operationLocation = rawHttpResponse.headers["Operation-Location"]
    idLocation = len(operationLocation) - numberOfCharsInOperationId
    operationId = operationLocation[idLocation:]

    # SDK call
    result = vision_client.get_read_result(operationId)

    # USe while loop to check the status of the operation
    while result.status in [
        OperationStatusCodes.not_started,
        OperationStatusCodes.running,
    ]:
        result = vision_client.get_read_result(operationId)
        print("Waiting for result : ", result)

    # Get data
    # if result.status == OperationStatusCodes.succeeded:
    #print(result.status)
    return_text = ""
    for line in result.analyze_result.read_results[0].lines:
        print(line.text)
        print(line.bounding_box)
        if return_text != "":
            return_text = return_text + "," + line.text
        else:
            return_text += line.text
    # return result.analyze_result.read_results[0].lines[0].text
    return return_text
    
#暫時用不到
def  buttons(event):    
    with ApiClient(Configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
    url = request.url_root + '/static/Logo.jpg'
    url = url.replace("http", "https")
    app.logger.info("url=" + url)
    buttons_template = ButtonsTemplate(
        thumbnail_image_url=url,
        title='AIFoodie 智慧點餐機器人',
        text='功能選單',
        actions=[
        URIAction(label='開始使用', uri='https://www.google.com.tw/'),
        MessageAction(label='上傳菜單', text='上傳菜單'),
        ]
    )
        
    template_message = TemplateMessage(
        alt_text="This is a buttons template",
        template=buttons_template
    )
    line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[template_message]
        )
    )


if __name__ == "__main__":
    app.run()
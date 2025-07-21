# SPDX-License-Identifier: GPL-3.0-or-later

"""
euserv 自动续期脚本
功能:
* 使用 OpenAI Vision API 自动识别验证码
* 发送通知到 Telegram
* 增加登录失败重试机制
* 日志信息格式化
"""

import re
import json
import time
import base64
import requests
import hmac
import struct
from bs4 import BeautifulSoup
import openai # <-- 新增导入

# 账户信息：用户名和密码
USERNAME = 'servewangping@gmail.com'  # 填写用户名或邮箱
PASSWORD = '9op0(OP)'  # 填写密码

# 2FA机密Key
EUSERV_2FA_SECRET = 'LO6YLVLPEVALJFCU' # 填写2FA机密

# --- OpenAI API 配置 (已替换 TrueCaptcha) ---
OPENAI_API_KEY = 'wufeng666' # 改为你的 OpenAI API Key
OPENAI_API_BASE_URL = 'https://gemini.opb.dpdns.org/hf/v1' # 如果使用第三方代理API，请修改此项
OPENAI_MODEL_NAME = 'gemini-1.5-flash' # 推荐使用 gpt-4o 或 gpt-4-vision-preview

# Mailparser 配置
MAILPARSER_DOWNLOAD_URL_ID = 'smgrgovb ' # 填写Mailparser的下载URL_ID
MAILPARSER_DOWNLOAD_BASE_URL = "https://files.mailparser.io/d/" # 无需更改除非你要反代

# Telegram Bot 推送配置
TG_BOT_TOKEN = "8165600540:AAGmiiBuaNGMrFpLpbQEpRi7ydvjTDPE5yQ"
TG_USER_ID = "6644463336" # 用户机器人向你发送消息
TG_API_HOST = "https://gh.opb.dpdns.org/https://api.telegram.org"

# 代理设置（如果需要）
# ！！！关键修改！！！将代理设置为 None，以解决 Connection refused 错误
PROXIES = None # 如果不需要代理，请设为 None

# 最大登录重试次数
LOGIN_MAX_RETRY_COUNT = 5

# 接收 PIN 的等待时间，单位为秒
WAITING_TIME_OF_PIN = 15

# (原 CHECK_CAPTCHA_SOLVER_USAGE 已移除)

user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/95.0.4638.69 Safari/537.36"
)

desp = ""  # 日志信息

def log(info: str):
    # 打印并记录日志信息，附带 emoji 以增加可读性
    emoji_map = {
        "正在续费": "🔄",
        "检测到": "🔍",
        "ServerID": "🔗",
        "无需更新": "✅",
        "续订错误": "⚠️",
        "已成功续订": "🎉",
        "所有工作完成": "🏁",
        "登陆失败": "❗",
        "验证通过": "✔️",
        "验证失败": "❌",
        "[Captcha Solver]": "🧩", # Emoji 保持
        "验证码是": "🔢",
        "登录尝试": "🔑",
        "[MailParser]": "📧",
        "[AutoEUServerless]": "🌐",
        "[2FA]": "🔐",
    }
    # 对每个关键字进行检查，并在找到时添加 emoji
    for key, emoji in emoji_map.items():
        if key in info:
            info = emoji + " " + info
            break

    print(info)
    global desp
    desp += info + "\n\n"


# 登录重试装饰器
def login_retry(*args, **kwargs):
    def wrapper(func):
        def inner(username, password):
            ret, ret_session = func(username, password)
            max_retry = kwargs.get("max_retry")
            # 默认重试 3 次
            if not max_retry:
                max_retry = 3
            number = 0
            if ret == "-1":
                while number < max_retry:
                    number += 1
                    if number > 1:
                        log("[AutoEUServerless] 登录尝试第 {} 次".format(number))
                    sess_id, session = func(username, password)
                    if sess_id != "-1":
                        return sess_id, session
                    else:
                        if number == max_retry:
                            return sess_id, session
            else:
                return ret, ret_session
        return inner
    return wrapper

# 基于计数器的一次性密码
def hotp(key, counter, digits=6, digest='sha1'):
    """生成 HOTP 验证码"""
    key = base64.b32decode(key.upper() + '=' * ((8 - len(key)) % 8))
    counter = struct.pack('>Q', counter)
    mac = hmac.new(key, counter, digest).digest()
    offset = mac[-1] & 0x0f
    binary = struct.unpack('>L', mac[offset:offset+4])[0] & 0x7fffffff
    return str(binary)[-digits:].zfill(digits)

# 基于时间戳的一次性密码
def totp(key, time_step=30, digits=6, digest='sha1'):
    """生成 TOTP 验证码"""
    return hotp(key, int(time.time() / time_step), digits, digest)

# --- captcha_solver 函数 (已替换为 OpenAI 实现) ---
def captcha_solver(captcha_image_url: str, session: requests.session) -> dict:
    """使用兼容OpenAI的vision模型API解决验证码"""
    log(f"[Captcha Solver] 正在使用 OpenAI 兼容接口，模型: {OPENAI_MODEL_NAME}")
    if not OPENAI_API_KEY or 'sk-xxx' in OPENAI_API_KEY:
        log("[Captcha Solver] OpenAI API Key 未配置。")
        return {}

    try:
        # 注意：openai库会自动使用 HTTPS_PROXY/HTTP_PROXY 环境变量，无需手动传入PROXIES
        client = openai.OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE_URL)
    
        # 获取验证码图片时需要使用代理
        response = session.get(captcha_image_url, proxies=PROXIES)
        response.raise_for_status()
        base64_image = base64.b64encode(response.content).decode('utf-8')

        prompt = (
            "You are an expert captcha solver. Your task is to return ONLY the "
            "characters or the calculated result. If the image contains 'AB12C', "
            "return 'AB12C'. If it's a math problem like '5 x 3', return ONLY "
            "the final number, '15'. Provide no explanations."
        )

        api_response = client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }],
            max_tokens=50
        )
        result_text = api_response.choices[0].message.content.strip()
        log(f"[Captcha Solver] API 返回原始结果: '{result_text}'")
        if not result_text:
            log("[Captcha Solver] API 返回结果为空。")
            return {}
        return {"result": result_text}

    except Exception as e:
        log(f"[Captcha Solver] 调用 OpenAI 兼容接口时发生严重错误: {e}")
        return {}

# (原 handle_captcha_solved_result 和 get_captcha_solver_usage 函数已移除)

# 从 Mailparser 获取 PIN
def get_pin_from_mailparser(url_id: str) -> str:
    # 从 Mailparser 获取 PIN# 
    response = requests.get(
        f"{MAILPARSER_DOWNLOAD_BASE_URL}{url_id}",
        proxies=PROXIES # 添加代理支持
    )
    response.raise_for_status()
    pin = response.json()[0]["pin"]
    return pin

# 登录函数
@login_retry(max_retry=LOGIN_MAX_RETRY_COUNT)
def login(username: str, password: str) -> (str, requests.session):
    # 登录 EUserv 并获取 session# 
    headers = {"user-agent": user_agent, "origin": "https://www.euserv.com"}
    url = "https://support.euserv.com/index.iphp"
    captcha_image_url = "https://support.euserv.com/securimage_show.php"
    session = requests.Session()

    sess = session.get(url, headers=headers, proxies=PROXIES) # 添加代理支持
    sess_id = re.findall("PHPSESSID=(\\w{10,100});", str(sess.headers))[0]
    session.get("https://support.euserv.com/pic/logo_small.png", headers=headers, proxies=PROXIES) # 添加代理支持

    login_data = {
        "email": username,
        "password": password,
        "form_selected_language": "en",
        "Submit": "Login",
        "subaction": "login",
        "sess_id": sess_id,
    }
    f = session.post(url, headers=headers, data=login_data, proxies=PROXIES) # 添加代理支持
    f.raise_for_status()

    if "Hello" not in f.text and "Confirm or change your customer data here" not in f.text:
        if "To finish the login process please solve the following captcha." in f.text:
            log("[Captcha Solver] 正在进行验证码识别...")
        
            # --- 验证码处理逻辑 (已更新) ---
            solved_result = captcha_solver(captcha_image_url, session)
            if not solved_result or "result" not in solved_result or not solved_result["result"]:
                 log("[Captcha Solver] 未能从API获取有效结果，登录失败。")
                 return "-1", session
        
            captcha_code = solved_result["result"]
            log("[Captcha Solver] 识别的验证码是: {}".format(captcha_code))
        
            # (原 get_captcha_solver_usage 调用已移除)

            f2 = session.post(
                url,
                headers=headers,
                data={
                    "subaction": "login",
                    "sess_id": sess_id,
                    "captcha_code": captcha_code,
                },
                proxies=PROXIES # 添加代理支持
            )
            if "To finish the login process please solve the following captcha." not in f2.text:
                log("[Captcha Solver] 验证通过")
                # 验证码通过后，检查是否登录成功或需要2FA
                if "Hello" in f2.text or "Confirm or change your customer data here" in f2.text:
                    return sess_id, session
                f = f2  # 继续检查2FA
            else:
                log("[Captcha Solver] 验证失败")
                return "-1", session

        if "To finish the login process enter the PIN that is shown in yout authenticator app." in f.text:
            log("[2FA] 检测到需要 2FA 验证")
            if not EUSERV_2FA_SECRET:
                log("[2FA] 未配置 2FA 密钥，登录失败")
                return "-1", session
            
            two_fa_code = totp(EUSERV_2FA_SECRET)
            log("[2FA] 生成的验证码: {}".format(two_fa_code))
        
            f2 = session.post(
                url,
                headers=headers,
                data={
                    "subaction": "login",
                    "sess_id": sess_id,
                    "pin": two_fa_code,
                },
                proxies=PROXIES # 添加代理支持
            )
        
            if "To finish the login process enter the PIN that is shown in yout authenticator app." not in f2.text:
                log("[2FA] 2FA 验证通过")
                return sess_id, session
            else:
                log("[2FA] 2FA 验证失败")
                return "-1", session
        else:
            return "-1", session        
    else:
        return sess_id, session

# 获取服务器列表
def get_servers(sess_id: str, session: requests.session) -> {}:
    # 获取服务器列表# 
    d = {}
    url = "https://support.euserv.com/index.iphp?sess_id=" + sess_id
    headers = {"user-agent": user_agent, "origin": "https://www.euserv.com"}
    f = session.get(url=url, headers=headers, proxies=PROXIES) # 添加代理支持
    f.raise_for_status()
    soup = BeautifulSoup(f.text, "html.parser")
    for tr in soup.select(
        "#kc2_order_customer_orders_tab_content_1 .kc2_order_table.kc2_content_table tr,#kc2_order_customer_orders_tab_content_2 .kc2_order_table.kc2_content_table tr.kc2_order_upcoming_todo_row"
    ):
        server_id = tr.select(".td-z1-sp1-kc")
        if not len(server_id) == 1:
            continue
        flag = (
            True
            if tr.select(".td-z1-sp2-kc .kc2_order_action_container")[0]
            .get_text()
            .find("Contract extension possible from")
            == -1
            else False
        )
        d[server_id[0].get_text()] = flag
    return d

# 续期操作
def renew(
    sess_id: str, session: requests.session, password: str, order_id: str, mailparser_dl_url_id: str
) -> bool:
    # 执行续期操作# 
    url = "https://support.euserv.com/index.iphp"
    headers = {
        "user-agent": user_agent,
        "Host": "support.euserv.com",
        "origin": "https://support.euserv.com",
        "Referer": "https://support.euserv.com/index.iphp",
    }
    data = {
        "Submit": "Extend contract",
        "sess_id": sess_id,
        "ord_no": order_id,
        "subaction": "choose_order",
        "choose_order_subaction": "show_contract_details",
    }
    session.post(url, headers=headers, data=data, proxies=PROXIES) # 添加代理支持

    # 弹出 'Security Check' 窗口，将自动触发 '发送 PIN'。
    session.post(
        url,
        headers=headers,
        data={
            "sess_id": sess_id,
            "subaction": "show_kc2_security_password_dialog",
            "prefix": "kc2_customer_contract_details_extend_contract_",
            "type": "1",
        },
        proxies=PROXIES # 添加代理支持
    )

    # 等待邮件解析器解析出 PIN
    time.sleep(WAITING_TIME_OF_PIN)
    pin = get_pin_from_mailparser(mailparser_dl_url_id)
    log(f"[MailParser] PIN: {pin}")

    # 使用 PIN 获取 token
    data = {
        "auth": pin,
        "sess_id": sess_id,
        "subaction": "kc2_security_password_get_token",
        "prefix": "kc2_customer_contract_details_extend_contract_",
        "type": 1,
        "ident": f"kc2_customer_contract_details_extend_contract_{order_id}",
    }
    f = session.post(url, headers=headers, data=data, proxies=PROXIES) # 添加代理支持
    f.raise_for_status()
    if not json.loads(f.text)["rs"] == "success":
        return False
    token = json.loads(f.text)["token"]["value"]
    data = {
        "sess_id": sess_id,
        "ord_id": order_id,
        "subaction": "kc2_customer_contract_details_extend_contract_term",
        "token": token,
    }
    session.post(url, headers=headers, data=data, proxies=PROXIES) # 添加代理支持
    time.sleep(5)
    return True

# 检查续期状态
def check(sess_id: str, session: requests.session):
    # 检查续期状态# 
    print("Checking.......")
    d = get_servers(sess_id, session)
    flag = True
    for key, val in d.items():
        if val:
            flag = False
            log("[AutoEUServerless] ServerID: %s 续期失败!" % key)

    if flag:
        log("[AutoEUServerless] 所有工作完成！尽情享受~")

# 发送 Telegram 通知
def telegram():
    message = (
        "<b>AutoEUServerless 日志</b>\n\n" + desp +
        "\n<b>版权声明：</b>\n"
        "本脚本基于 GPL-3.0 许可协议，版权所有。\n\n"
    
        "<b>致谢：</b>\n"
        "特别感谢 <a href='https://github.com/lw9726/eu_ex'>eu_ex</a> 的贡献和启发, 本项目在此基础整理。\n"
        "开发者：<a href='https://github.com/WizisCool/AutoEUServerless'>WizisCool</a>\n"
        "<a href='https://www.nodeseek.com/space/8902#/general'>个人Nodeseek主页</a>\n"
        "<a href='https://dooo.ng'>个人小站Dooo.ng</a>\n\n"
        "<b>支持项目：</b>\n"
        "⭐️ 给我们一个 GitHub Star! ⭐️\n"
        "<a href='https://github.com/WizisCool/AutoEUServerless'>访问 GitHub 项目</a>"
    )

    # 请不要删除本段版权声明, 开发不易, 感谢! 感谢!
    # 请勿二次售卖,出售,开源不易,万分感谢!
    data = {
        "chat_id": TG_USER_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }
    response = requests.post(
        TG_API_HOST + "/bot" + TG_BOT_TOKEN + "/sendMessage", data=data, proxies=PROXIES # 添加代理支持
    )
    if response.status_code != 200:
        print("Telegram Bot 推送失败")
    else:
        print("Telegram Bot 推送成功")



def main_handler(event, context):
    # 主函数，处理每个账户的续期# 
    if not USERNAME or not PASSWORD:
        log("[AutoEUServerless] 你没有添加任何账户")
        exit(1)
    user_list = USERNAME.strip().split()
    passwd_list = PASSWORD.strip().split()
    mailparser_dl_url_id_list = MAILPARSER_DOWNLOAD_URL_ID.strip().split()
    if len(user_list) != len(passwd_list):
        log("[AutoEUServerless] 用户名和密码数量不匹配!")
        exit(1)
    if len(mailparser_dl_url_id_list) != len(user_list):
        log("[AutoEUServerless] mailparser_dl_url_ids 和用户名的数量不匹配!")
        exit(1)
    for i in range(len(user_list)):
        print("*" * 30)
        log("[AutoEUServerless] 正在续费第 %d 个账号" % (i + 1))
        sessid, s = login(user_list[i], passwd_list[i])
        if sessid == "-1":
            log("[AutoEUServerless] 第 %d 个账号登陆失败，请检查登录信息" % (i + 1))
            continue
        SERVERS = get_servers(sessid, s)
        log("[AutoEUServerless] 检测到第 {} 个账号有 {} 台 VPS，正在尝试续期".format(i + 1, len(SERVERS)))
        for k, v in SERVERS.items():
            if v:
                if not renew(sessid, s, passwd_list[i], k, mailparser_dl_url_id_list[i]):
                    log("[AutoEUServerless] ServerID: %s 续订错误!" % k)
                else:
                    log("[AutoEUServerless] ServerID: %s 已成功续订!" % k)
            else:
                log("[AutoEUServerless] ServerID: %s 无需更新" % k)
        time.sleep(15)
        check(sessid, s)
        time.sleep(5)

    # 发送 Telegram 通知
    if TG_BOT_TOKEN and TG_USER_ID and TG_API_HOST:
        telegram()

    print("*" * 30)

if __name__ == "__main__":
     main_handler(None, None)

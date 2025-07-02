# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import shutil
import re
import base64
import subprocess
from pathlib import Path
import urllib.request
import requests 
import streamlit as st

# ======== Streamlit 配置 ========
st.set_page_config(page_title="Py-Vless 控制面板", layout="centered")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd() 
INSTALL_DIR = APP_ROOT / ".py-vless"
CF_LOG_FILE = INSTALL_DIR / "cloudflared.log"
NEZHA_LOG_FILE = INSTALL_DIR / "nezha.log"
FLASK_LOG_FILE = INSTALL_DIR / "flask.log"
FLASK_APP_FILE = APP_ROOT / "web_app.py"

# 创建安装目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== Flask App 代码 (无需改动) ========
FLASK_APP_CODE = """
import os
import sys
import socket
import subprocess
import threading
from urllib.parse import unquote
from flask import Flask, request, abort
from flask_sock import Sock

PORT = int(os.environ.get('PORT', 3000))
UUID = os.environ.get('UUID', 'ffffffff-ffff-ffff-ffff-ffffffffffff').replace('-', '')

app = Flask(__name__)
sock = Sock(app)

def pipe_stream(source, dest):
    try:
        while True:
            data = source.recv(4096)
            if not data:
                break
            dest.sendall(data)
    except Exception:
        pass
    finally:
        try:
            source.close()
            dest.close()
        except Exception:
            pass

@app.route('/')
def index():
    return "Hello, World"

@app.route('/ps')
def ps_aux():
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, check=True)
        return result.stdout, 200, {'Content-Type': 'text/plain'}
    except subprocess.CalledProcessError as e:
        return f"Error executing ps aux: {e.stderr}", 500, {'Content-Type': 'text/plain'}

@sock.route(f'/<path:subpath>')
def vless_proxy(ws, subpath):
    try:
        raw_msg = ws.receive(timeout=10)
        if not raw_msg or len(raw_msg) < 24:
            ws.close()
            return

        version = raw_msg[0]
        id_received = raw_msg[1:17].hex()
        
        if id_received != UUID:
            ws.close()
            return
            
        addon_len = raw_msg[17]
        i = 18 + addon_len
        port = int.from_bytes(raw_msg[i:i+2], 'big')
        i += 2
        atyp = raw_msg[i]
        i += 1
        
        if atyp == 1:
            host = socket.inet_ntoa(raw_msg[i:i+4])
            i += 4
        elif atyp == 3:
            domain_len = raw_msg[i]
            i += 1
            host = raw_msg[i:i+domain_len].decode()
            i += domain_len
        elif atyp == 2:
            host = socket.inet_ntop(socket.AF_INET6, raw_msg[i:i+16])
            i += 16
        else:
            ws.close(); return

        ws.send(bytes([version, 0]))
        remote_socket = socket.create_connection((host, port), timeout=10)
        remaining_data = raw_msg[i:]
        if remaining_data:
            remote_socket.sendall(remaining_data)

        ws_to_remote = threading.Thread(target=pipe_stream, args=(ws.connection, remote_socket))
        remote_to_ws = threading.Thread(target=pipe_stream, args=(remote_socket, ws.connection))
        ws_to_remote.start()
        remote_to_ws.start()
        ws_to_remote.join()
        remote_to_ws.join()
    except Exception:
        pass
    finally:
        ws.close()

if __name__ == "__main__":
    from waitress import serve
    serve(app, host='0.0.0.0', port=PORT)
"""

# ======== 辅助函数 ========
def download_file(url, target_path, status_ui):
    try:
        status_ui.update(label=f'正在下载 {Path(url).name}...')
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        status_ui.update(label=f"下载文件失败: {url}", state="error")
        st.error(f"下载文件失败: {url}, 错误: {e}")
        st.stop()

def get_isp_info():
    try:
        response = requests.get('https://speed.cloudflare.com/meta', timeout=10)
        data = response.json()
        return f"{data.get('country', 'N/A')}-{data.get('asOrganization', 'N/A')}".replace(' ', '_')
    except Exception:
        return 'Unknown'

def add_access_task(domain, uuid_str):
    if not domain:
        return
    try:
        # 路径必须是 / , 因为 VLESS 路径不一定是 UUID
        full_url = f"https://{domain}/"
        requests.post('https://urlchk.fk.ddns-ip.net/add-url', json={'url': full_url}, timeout=10)
        st.toast("保活任务已添加。")
    except Exception as e:
        st.toast(f"添加保活任务失败: {e}")

# ======== 核心业务逻辑 ========
def install_and_run():
    with st.status("正在初始化服务...", expanded=True) as status:
        # --- 1. 加载配置 ---
        status.update(label="正在加载配置...")
        try:
            config = {
                "PORT": st.secrets.get("PORT", "3000"),
                "UUID": st.secrets["UUID"],
                "DOMAIN": st.secrets["DOMAIN"], # 必需，您隧道的域名
                "CF_TOKEN": st.secrets["CF_TOKEN"], # 必需，您的隧道 Token
                "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
                "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
                "NEZHA_PORT": st.secrets.get("NEZHA_PORT", ""), 
                "NAME": st.secrets.get("NAME", "VLS")
            }
            st.session_state.app_config = config
        except KeyError as e:
            status.update(label=f"配置错误: 缺少必要的 Secret: {e}", state="error")
            st.stop()

        # --- 2. 创建 Flask App 文件 ---
        status.update(label="正在创建 Web App...")
        FLASK_APP_FILE.write_text(FLASK_APP_CODE)

        # --- 3. 下载所需文件 ---
        arch = "amd64" 
        cloudflared_path = INSTALL_DIR / "cloudflared"
        if not cloudflared_path.exists():
            cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            download_file(cf_url, cloudflared_path, status)

        nezha_agent_path = INSTALL_DIR / "npm"
        if config["NEZHA_SERVER"] and not nezha_agent_path.exists():
            if not config["NEZHA_PORT"]: nezha_url = f'https://amd64.ssss.nyc.mn/v1'
            else: nezha_url = f'https://amd64.ssss.nyc.mn/agent'
            download_file(nezha_url, nezha_agent_path, status)

        # --- 4. 启动所有后台服务 ---
        status.update(label="正在启动后台服务...")
        
        flask_env = os.environ.copy()
        flask_env.update({"PORT": config["PORT"], "UUID": config["UUID"]})

        if "flask_process" not in st.session_state or st.session_state.flask_process.poll() is not None:
            py_executable = sys.executable
            with open(FLASK_LOG_FILE, 'w') as log_f:
                st.session_state.flask_process = subprocess.Popen([py_executable, str(FLASK_APP_FILE)], env=flask_env, stdout=log_f, stderr=log_f)
            time.sleep(3)
            if st.session_state.flask_process.poll() is not None:
                status.update(label="Flask 服务启动失败", state="error"); st.stop()

        # --- 这是关键修正：使用 Token 启动您的命名隧道 ---
        if "cf_process" not in st.session_state or st.session_state.cf_process.poll() is not None:
            status.update(label="正在启动 Cloudflared 命名隧道...")
            os.chmod(cloudflared_path, 0o755)
            command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
            with open(CF_LOG_FILE, 'w') as log_f:
                st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
            time.sleep(5)
            if st.session_state.cf_process.poll() is not None:
                status.update(label="Cloudflared 启动失败! 请检查您的 CF_TOKEN。", state="error")
                st.code(CF_LOG_FILE.read_text(), language="log")
                st.stop()
        
        # 启动哪吒 Agent (逻辑不变)
        if config["NEZHA_SERVER"] and ("nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None):
            status.update(label="正在启动 Nezha Agent...")
            # ... (这部分代码和之前一样，是正确的)
            os.chmod(nezha_agent_path, 0o755)
            command_str = ''
            if config["NEZHA_PORT"]: # v0 
                use_tls = '--tls' if config["NEZHA_PORT"] in ['443', '8443', '2096', '2087', '2083', '2053'] else ''
                command_str = f'./npm -s {config["NEZHA_SERVER"]}:{config["NEZHA_PORT"]} -p {config["NEZHA_KEY"]} {use_tls}'
            else: # v1
                port_in_server = config["NEZHA_SERVER"].split(':')[-1] if ':' in config["NEZHA_SERVER"] else ''
                use_tls = 'true' if port_in_server in ['443', '8443', '2096', '2087', '2083', '2053'] else 'false'
                config_yaml = f"server: {config['NEZHA_SERVER']}\\nclient_secret: {config['NEZHA_KEY']}\\ntls: {use_tls}\\nuuid: {config['UUID']}"
                subprocess.run(f'echo -e "{config_yaml}" > config.yaml', shell=True, cwd=INSTALL_DIR)
                command_str = f'./npm -c config.yaml'

            with open(NEZHA_LOG_FILE, 'w') as log_f:
                st.session_state.nezha_process = subprocess.Popen(command_str, shell=True, cwd=INSTALL_DIR, stdout=log_f, stderr=log_f)
            time.sleep(3)
            if st.session_state.nezha_process.poll() is not None:
                status.update(label="Nezha Agent 启动失败", state="error"); st.stop()


        # --- 5. 生成最终信息 ---
        status.update(label="正在生成订阅链接...")
        isp = get_isp_info()
        vless_url = f"vless://{config['UUID']}@www.visa.com.hk:443?encryption=none&security=tls&sni={config['DOMAIN']}&type=ws&host={config['DOMAIN']}&path=%2F#{(config['NAME'] + '-' + isp)}"
        st.session_state.vless_url = vless_url
        st.session_state.vless_b64 = base64.b64encode(vless_url.encode()).decode()

        add_access_task(config['DOMAIN'], config['UUID'])
        
        st.session_state.installed = True
        status.update(label="初始化完成！", state="complete")


# ======== Streamlit UI 界面 ========
st.title("Py-Vless 控制面板")
st.caption("基于 Node.js 逻辑的 Python 实现")

if "installed" not in st.session_state:
    install_and_run()

config = st.session_state.get("app_config", {})
st.success("服务已启动。")

st.subheader("VLESS 订阅链接")
st.code(st.session_state.get("vless_url", "生成中..."), language="text")

st.subheader("Base64 格式")
st.code(st.session_state.get("vless_b64", "生成中..."))

st.markdown(f"**隧道域名:** `{config.get('DOMAIN', 'N/A')}`")

with st.expander("查看服务日志", expanded=False):
    st.subheader("Cloudflared 日志")
    if CF_LOG_FILE.exists(): st.code(CF_LOG_FILE.read_text(), language='log')

    st.subheader("Web 服务日志")
    if FLASK_LOG_FILE.exists(): st.code(FLASK_LOG_FILE.read_text(), language='log')
    
    if config.get("NEZHA_SERVER"):
        st.subheader("Nezha Agent 日志")
        if NEZHA_LOG_FILE.exists(): st.code(NEZHA_LOG_FILE.read_text(), language='log')

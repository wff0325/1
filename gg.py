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
BACKEND_PORT_STR = "52068" 

# 创建安装目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== Flask App 代码 ========
FLASK_APP_CODE = f"""
import os
import sys
import socket
import subprocess
import threading
from flask import Flask
from flask_sock import Sock
from waitress import serve

PORT = int(os.environ.get('BACKEND_PORT', '{BACKEND_PORT_STR}'))
UUID = os.environ.get('UUID', 'ffffffff-ffff-ffff-ffff-ffffffffffff').replace('-', '')

app = Flask(__name__)
sock = Sock(app)

def pipe_stream(source, dest):
    try:
        while True:
            data = source.recv(4096)
            if not data: break
            dest.sendall(data)
    except Exception: pass
    finally:
        try: source.close()
        except Exception: pass
        try: dest.close()
        except Exception: pass

@app.route('/')
def index():
    return "Hello, World"

@sock.route(f'/<path:subpath>')
def vless_proxy(ws, subpath):
    try:
        raw_msg = ws.receive(timeout=10)
        if not raw_msg or len(raw_msg) < 24:
            ws.close(); return

        version = raw_msg[0]
        id_received = raw_msg[1:17].hex()
        
        if id_received != UUID:
            ws.close(); return
            
        addon_len = raw_msg[17]
        i = 18 + addon_len
        port = int.from_bytes(raw_msg[i:i+2], 'big'); i += 2
        atyp = raw_msg[i]; i += 1
        
        if atyp == 1: host = socket.inet_ntoa(raw_msg[i:i+4]); i += 4
        elif atyp == 3: domain_len = raw_msg[i]; i += 1; host = raw_msg[i:i+domain_len].decode(); i += domain_len
        elif atyp == 2: host = socket.inet_ntop(socket.AF_INET6, raw_msg[i:i+16]); i += 16
        else: ws.close(); return

        ws.send(bytes([version, 0]))
        remote_socket = socket.create_connection((host, port), timeout=10)
        remaining_data = raw_msg[i:]
        if remaining_data: remote_socket.sendall(remaining_data)

        ws_thread = threading.Thread(target=pipe_stream, args=(ws.connection, remote_socket))
        remote_thread = threading.Thread(target=pipe_stream, args=(remote_socket, ws.connection))
        ws_thread.start()
        remote_thread.start()
        ws_thread.join()
        remote_thread.join()
    except Exception: pass
    finally: ws.close()

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=PORT)
"""

# ======== 辅助函数 (被误删的部分已恢复) ========
def download_file(url, target_path, status_ui):
    try:
        status_ui.update(label=f'正在下载 {Path(url).name}...')
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        return True
    except Exception as e:
        status_ui.update(label=f"下载文件失败: {url}", state="error"); st.error(f"下载文件失败: {url}, 错误: {e}"); st.stop()

def get_isp_info():
    try:
        data = requests.get('https://speed.cloudflare.com/meta', timeout=10).json()
        return f"{data.get('country', 'NA')}-{data.get('asOrganization', 'NA')}".replace(' ', '_')
    except Exception: return 'Unknown'

def add_access_task(domain):
    if not domain: return
    try:
        requests.post('https://urlchk.fk.ddns-ip.net/add-url', json={'url': f"https://{domain}/"}, timeout=10)
        st.toast("保活任务已添加。")
    except Exception: pass

# ======== 核心业务逻辑函数 ========
def initialize_services():
    with st.status("正在初始化服务...", expanded=True) as status:
        # --- 1. 加载配置 ---
        status.update(label="正在加载配置...")
        try:
            config = {
                "UUID": st.secrets["UUID"],
                "DOMAIN": st.secrets["DOMAIN"], 
                "CF_TOKEN": st.secrets["CF_TOKEN"],
                "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
                "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
                "NEZHA_TLS": st.secrets.get("NEZHA_TLS", False),
                "NAME": st.secrets.get("NAME", "VLS")
            }
            st.session_state.app_config = config
        except KeyError as e:
            status.update(label=f"配置错误: 缺少 Secret: {e}", state="error"); st.stop()

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
            nezha_url = 'https://amd64.ssss.nyc.mn/v1'
            download_file(nezha_url, nezha_agent_path, status)

        # --- 4. 启动所有后台服务 ---
        status.update(label="正在启动后台服务...")
        
        flask_env = os.environ.copy()
        flask_env.update({"BACKEND_PORT": BACKEND_PORT_STR, "UUID": config["UUID"]})

        if "flask_process" not in st.session_state or st.session_state.flask_process.poll() is not None:
            py_executable = sys.executable
            with open(FLASK_LOG_FILE, 'w') as log_f:
                st.session_state.flask_process = subprocess.Popen([py_executable, str(FLASK_APP_FILE)], env=flask_env, stdout=log_f, stderr=log_f)
            time.sleep(3)
            if st.session_state.flask_process.poll() is not None:
                status.update(label="后台 Web 服务启动失败!", state="error")
                st.error("后台 Web 服务启动失败，请检查日志。")
                st.code(FLASK_LOG_FILE.read_text(), language="log"); st.stop()
        
        if "cf_process" not in st.session_state or st.session_state.cf_process.poll() is not None:
            os.chmod(cloudflared_path, 0o755)
            command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
            with open(CF_LOG_FILE, 'w') as log_f:
                st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
            time.sleep(5)
            if st.session_state.cf_process.poll() is not None:
                status.update(label="Cloudflared 启动失败! 请检查 Token。", state="error")
                st.error("Cloudflared 启动失败! 请检查 Token。")
                st.code(CF_LOG_FILE.read_text(), language="log"); st.stop()
        
        if config["NEZHA_SERVER"] and ("nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None):
            os.chmod(nezha_agent_path, 0o755)
            use_tls_str = 'true' if config["NEZHA_TLS"] else 'false'
            config_yaml_content = f"""server: {config['NEZHA_SERVER']}
client_secret: {config['NEZHA_KEY']}
tls: {use_tls_str}
uuid: {config['UUID']}
"""
            config_yaml_path = INSTALL_DIR / "config.yaml"
            config_yaml_path.write_text(config_yaml_content)
            command_list = [str(nezha_agent_path), '-c', str(config_yaml_path)]
            with open(NEZHA_LOG_FILE, 'w') as log_f:
                st.session_state.nezha_process = subprocess.Popen(command_list, cwd=INSTALL_DIR, stdout=log_f, stderr=log_f)
            time.sleep(3)
            if st.session_state.nezha_process.poll() is not None:
                status.update(label="Nezha Agent 启动失败!", state="error")
                st.error("Nezha Agent 启动失败，请检查日志。")
                st.code(NEZHA_LOG_FILE.read_text(), language="log"); st.stop()

        # --- 5. 生成最终信息 ---
        status.update(label="正在生成订阅链接...")
        isp = get_isp_info()
        vless_url = f"vless://{config['UUID']}@www.visa.com.hk:443?encryption=none&security=tls&sni={config['DOMAIN']}&type=ws&host={config['DOMAIN']}&path=%2F#{(config['NAME'] + '-' + isp)}"
        st.session_state.vless_url = vless_url
        st.session_state.vless_b64 = base64.b64encode(vless_url.encode()).decode()
        add_access_task(config['DOMAIN'])
        st.session_state.initialized = True
        status.update(label="初始化完成！", state="complete")

# ======== Streamlit UI 界面 ========
st.title("Py-Vless 控制面板")
st.caption("最终修正版")

if "initialized" not in st.session_state:
    initialize_services()

config = st.session_state.get("app_config", {})
if st.session_state.get("initialized"):
    st.success("所有服务已成功启动。")
    st.subheader("VLESS 订阅链接")
    st.code(st.session_state.get("vless_url", "生成中..."), language="text")
    st.markdown(f"**隧道域名:** `{config.get('DOMAIN', 'N/A')}`")

    with st.expander("查看服务日志", expanded=False):
        st.subheader("Cloudflared 日志")
        if CF_LOG_FILE.exists(): st.code(CF_LOG_FILE.read_text(), language='log')
        st.subheader("后台 Web 服务日志")
        if FLASK_LOG_FILE.exists(): st.code(FLASK_LOG_FILE.read_text(), language='log')
        if config.get("NEZHA_SERVER"):
            st.subheader("Nezha Agent 日志")
            if NEZHA_LOG_FILE.exists(): st.code(NEZHA_LOG_FILE.read_text(), language='log')
else:
    st.warning("正在初始化服务，请稍候...")

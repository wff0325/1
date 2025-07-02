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
            # 您的 `NEZHA_TLS = false` 在 toml 中会被读为布尔值 False
            nezha_tls_value = st.secrets.get("NEZHA_TLS", False)

            config = {
                "PORT": st.secrets.get("PORT", "3000"),
                "UUID": st.secrets["UUID"],
                "DOMAIN": st.secrets["DOMAIN"], 
                "CF_TOKEN": st.secrets["CF_TOKEN"],
                "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
                "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
                "NEZHA_TLS": nezha_tls_value, # 直接使用布尔值
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
            # 由于我们使用 config.yaml (v1方式)，所以总是下载 v1 agent
            nezha_url = f'https://amd64.ssss.nyc.mn/v1'
            download_file(nezha_url, nezha_agent_path, status)

        # --- 4. 启动所有后台服务 ---
        status.update(label="正在启动后台服务...")
        
        flask_env = os.environ.copy()
        flask_env.update({"PORT": config["PORT"], "UUID": config["UUID"]})

        if "flask_process" not in st.session_state or st.session_state.flask_process.poll() is not None:
            status.update(label="正在启动 Flask 服务...")
            py_executable = sys.executable
            with open(FLASK_LOG_FILE, 'w') as log_f:
                st.session_state.flask_process = subprocess.Popen([py_executable, str(FLASK_APP_FILE)], env=flask_env, stdout=log_f, stderr=log_f)
            time.sleep(3)
            if st.session_state.flask_process.poll() is not None:
                status.update(label="Flask 服务启动失败!", state="error")
                log_content = FLASK_LOG_FILE.read_text()
                st.error("Flask Web 服务启动失败。")
                st.code(log_content, language="log")
                st.stop()
        
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
        
        # --- 这是关键修正：直接使用您的 NEZHA_TLS 配置 ---
        if config["NEZHA_SERVER"] and ("nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None):
            status.update(label="正在启动 Nezha Agent...")
            os.chmod(nezha_agent_path, 0o755)
            
            # 直接将布尔值转为 yaml 需要的 "true" 或 "false" 字符串
            use_tls_str = 'true' if config["NEZHA_TLS"] else 'false'
            
            # 使用 Python 安全地创建 YAML 文件
            config_yaml_content = f"""
server: {config['NEZHA_SERVER']}
client_secret: {config['NEZHA_KEY']}
tls: {use_tls_str}
"""
            config_yaml_path = INSTALL_DIR / "config.yaml"
            config_yaml_path.write_text(config_yaml_content)

            # 命令永远是使用 config.yaml 文件，简单、可靠
            command_list = [str(nezha_agent_path), '-c', str(config_yaml_path)]

            with open(NEZHA_LOG_FILE, 'w') as log_f:
                st.session_state.nezha_process = subprocess.Popen(command_list, cwd=INSTALL_DIR, stdout=log_f, stderr=log_f)
            time.sleep(3)

            if st.session_state.nezha_process.poll() is not None:
                status.update(label="Nezha Agent 启动失败! 请检查日志。", state="error")
                log_content = NEZHA_LOG_FILE.read_text()
                st.error("Nezha Agent 启动失败。请检查您的服务器地址和密钥。")
                st.code(log_content, language="log")
                st.stop()

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

with st.expander("查看服务日志", expanded=True):
    st.subheader("Cloudflared 日志")
    if CF_LOG_FILE.exists(): st.code(CF_LOG_FILE.read_text(), language='log')

    st.subheader("Web 服务日志")
    if FLASK_LOG_FILE.exists(): st.code(FLASK_LOG_FILE.read_text(), language='log')
    
    if config.get("NEZHA_SERVER"):
        st.subheader("Nezha Agent 日志")
        if NEZHA_LOG_FILE.exists(): st.code(NEZHA_LOG_FILE.read_text(), language='log')

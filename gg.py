# -*- coding: utf-8 -*-
import os
import sys
import json
import random
import time
import shutil
import re
import base64
import socket
import subprocess
import platform
from datetime import datetime
import uuid
from pathlib import Path
import urllib.request
import ssl
import zipfile
import tarfile
import streamlit as st

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 控制面板", layout="centered")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd() 
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "argo.log"
# --- 新增: 哪吒探针专用日志 ---
NEZHA_LOG_FILE = INSTALL_DIR / "nezha.log"

# 创建安装目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)


# ======== 辅助函数 ========
def download_file(url, target_path):
    try:
        with st.spinner(f'正在下载 {Path(url).name}...'):
            ctx = ssl._create_unverified_context()
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        st.error(f"下载文件失败: {url}, 错误: {e}")
        return False

def generate_vmess_link(config_dict):
    vmess_str = json.dumps(config_dict, sort_keys=True)
    return f"vmess://{base64.b64encode(vmess_str.encode('utf-8')).decode('utf-8').rstrip('=')}"

# ======== 核心业务逻辑 ========

def load_config():
    """从 Streamlit Secrets 加载配置，如果缺少则提供默认值"""
    try:
        port_value = st.secrets.get("PORT")
        if port_value:
            port = int(port_value)
        else:
            port = random.randint(10000, 20000)

        config = {
            "DOMAIN": st.secrets["DOMAIN"],
            "CF_TOKEN": st.secrets["CF_TOKEN"],
            "USER_NAME": st.secrets.get("USER_NAME", "default_user"),
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": port
        }
        config["NEZHA_SERVER"] = st.secrets.get("NEZHA_SERVER", "")
        config["NEZHA_KEY"] = st.secrets.get("NEZHA_KEY", "")
        return config
    except KeyError as e:
        st.error(f"错误: 缺少必要的 Secret 配置项: {e}。请在应用的 Secrets 中设置它。")
        st.stop()
    except ValueError:
        st.error(f"错误: Secrets 中的 PORT 值 '{port_value}' 不是一个有效的数字。")
        st.stop()

def start_services(config):
    """在Streamlit环境中启动后台服务"""
    # 启动 sing-box
    if "sb_process" not in st.session_state or st.session_state.sb_process.poll() is not None:
        ws_path = f"/{config['UUID'][:8]}-vm"
        sb_config_dict = {
            "log": {"level": "info", "timestamp": True},
            "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'], 
                          "users": [{"uuid": config['UUID'], "alterId": 0}],
                          "transport": {"type": "ws", "path": ws_path, "max_early_data": 2048, "early_data_header_name": "Sec-WebSocket-Protocol"}}],
            "outbounds": [{"type": "direct"}]
        }
        (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config_dict, indent=2))
        
        singbox_path = INSTALL_DIR / "sing-box"
        if singbox_path.exists():
            os.chmod(singbox_path, 0o755)
            st.session_state.sb_process = subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")])
        else:
            st.error("找不到 sing-box 可执行文件！"); st.stop()

    # 启动 cloudflared
    if "cf_process" not in st.session_state or st.session_state.cf_process.poll() is not None:
        cloudflared_path = INSTALL_DIR / "cloudflared"
        if cloudflared_path.exists():
            os.chmod(cloudflared_path, 0o755)
            command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
            with open(LOG_FILE, 'w') as log_f:
                 st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
        else:
            st.error("找不到 cloudflared 可执行文件！"); st.stop()

    # --- 修正后的哪吒探针启动逻辑 ---
    if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
        if "nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None:
            nezha_agent_path = INSTALL_DIR / "nezha-agent"
            if nezha_agent_path.exists():
                os.chmod(nezha_agent_path, 0o755)
                # 为哪吒探针使用独立的日志文件，方便排查
                # 增加 --disable-force-update 防止意外行为
                command = [str(nezha_agent_path), '-s', config["NEZHA_SERVER"], '-p', config["NEZHA_KEY"], '--disable-force-update']
                with open(NEZHA_LOG_FILE, 'w') as nezha_log_f:
                    st.session_state.nezha_process = subprocess.Popen(command, stdout=nezha_log_f, stderr=nezha_log_f)
                st.session_state.nezha_started = True
            else:
                st.warning("Nezha 配置已提供，但找不到 nezha-agent 可执行文件！")

def generate_links_and_save(config):
    """生成并保存节点链接"""
    ws_path_full = f"/{config['UUID'][:8]}-vm?ed=2048"
    hostname = "st-app"
    all_links = []
    cf_ips_tls = {"104.16.0.0": "443", "104.18.0.0": "2053"}
    
    for ip, port in cf_ips_tls.items():
        all_links.append(generate_vmess_link({
            "v": "2", "ps": f"VM-TLS-{hostname}-{ip.split('.')[2]}", "add": ip, "port": port, "id": config['UUID'],
            "aid": "0", "net": "ws", "type": "none", "host": config['DOMAIN'], "path": ws_path_full, "tls": "tls", "sni": config['DOMAIN']
        }))
        
    all_links.append(generate_vmess_link({
        "v": "2", "ps": f"VM-TLS-Direct-{hostname}", "add": config['DOMAIN'], "port": "443", "id": config['UUID'],
        "aid": "0", "net": "ws", "type": "none", "host": config['DOMAIN'], "path": ws_path_full, "tls": "tls", "sni": config['DOMAIN']
    }))

    st.session_state.links = "\n".join(all_links)
    st.session_state.installed = True
    
def install_and_run(config):
    """自动化安装和运行流程"""
    with st.status("正在初始化服务...", expanded=True) as status:
        arch = "amd64"
        
        singbox_path = INSTALL_DIR / "sing-box"
        if not singbox_path.exists():
            status.update(label="正在下载 sing-box...")
            sb_version = "1.9.0-beta.11"
            sb_name = f"sing-box-{sb_version}-linux-{arch}"
            sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"
            tar_path = INSTALL_DIR / "sing-box.tar.gz"
            if download_file(sb_url, tar_path):
                try:
                    with tarfile.open(tar_path, "r:gz") as tar: 
                        tar.extractall(path=INSTALL_DIR, filter='data')
                    shutil.move(INSTALL_DIR / sb_name / "sing-box", singbox_path)
                    shutil.rmtree(INSTALL_DIR / sb_name); tar_path.unlink()
                except Exception as e:
                    status.update(label=f"解压 sing-box 失败: {e}", state="error"); return
        
        cloudflared_path = INSTALL_DIR / "cloudflared"
        if not cloudflared_path.exists():
            status.update(label="下载 cloudflared...")
            cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            if not download_file(cf_url, cloudflared_path):
                status.update(label="下载 cloudflared 失败", state="error"); return
        
        # --- 修正后的哪吒探针下载逻辑 ---
        if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
            nezha_agent_path = INSTALL_DIR / "nezha-agent"
            if not nezha_agent_path.exists():
                status.update(label="正在下载 Nezha Agent...")
                nezha_url = f"https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_{arch}.zip"
                zip_path = INSTALL_DIR / "nezha-agent.zip"
                if download_file(nezha_url, zip_path):
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            zip_ref.extractall(INSTALL_DIR)
                        zip_path.unlink()
                    except Exception as e:
                        status.update(label=f"解压 Nezha Agent 失败: {e}", state="error"); return

        status.update(label="正在启动后台服务...")
        start_services(config)
        
        status.update(label="正在生成节点链接...")
        generate_links_and_save(config)
        status.update(label="初始化完成！", state="complete", expanded=False)

# ======== Streamlit UI 界面 ========
st.title("ArgoSB 部署面板")

app_config = load_config()
st.session_state.app_config = app_config 
st.markdown(f"**域名:** `{app_config['DOMAIN']}`")

# 检查服务是否已标记为运行
if "installed" not in st.session_state:
    install_and_run(app_config)
    st.rerun()

# --- 修正后的UI显示逻辑 ---
st.success("核心服务已启动。")
st.subheader("Vmess 节点链接")
st.code(st.session_state.links, language="text")

# 检查并显示哪吒探针状态
if app_config.get("NEZHA_SERVER"):
    if "nezha_started" in st.session_state:
        # 延迟一小会儿，给探针时间连接或报错
        time.sleep(2) 
        if "nezha_process" in st.session_state and st.session_state.nezha_process.poll() is None:
            st.info("Nezha 探针进程正在运行。")
        else:
            st.error("Nezha 探针进程已意外退出。请检查下面的日志。")
    else:
         st.warning("Nezha 配置已提供，但探针未能启动。")


with st.expander("查看当前配置和调试日志", expanded=True): # 默认展开，方便调试
    st.json(st.session_state.app_config)
    
    if LOG_FILE.exists():
        st.subheader("Argo Tunnel & Sing-Box 日志")
        st.code(LOG_FILE.read_text(), language='log')

    # 总是显示哪吒日志区域，如果文件存在的话
    if app_config.get("NEZHA_SERVER"):
        st.subheader("Nezha Agent 日志")
        if NEZHA_LOG_FILE.exists():
            st.code(NEZHA_LOG_FILE.read_text(), language='log')
        else:
            st.text("Nezha Agent 日志文件尚未创建。")

st.markdown("---")
st.markdown("原作者: wff | 改编: AI for Streamlit")

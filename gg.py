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
import streamlit as st

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 控制面板", layout="centered")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "argo.log"

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
        port = int(port_value) if port_value else random.randint(10000, 20000)

        config = {
            "DOMAIN": st.secrets["DOMAIN"],
            "CF_TOKEN": st.secrets["CF_TOKEN"],
            "USER_NAME": st.secrets.get("USER_NAME", "default_user"),
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": port,
            # ==== 代码修改处 #1 ====
            # 加载哪吒探针配置，并正确处理布尔值
            "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
            "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
            # 默认使用TLS，除非明确指定为 False
            "NEZHA_TLS": str(st.secrets.get("NEZHA_TLS", True)).lower() == "true"
        }
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
            st.session_state.sb_process = subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    # 启动 cloudflared
    if "cf_process" not in st.session_state or st.session_state.cf_process.poll() is not None:
        cloudflared_path = INSTALL_DIR / "cloudflared"
        if cloudflared_path.exists():
            os.chmod(cloudflared_path, 0o755)
            command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
            with open(LOG_FILE, 'w') as log_f:
                st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)

    # 启动哪吒探针 (如果已配置)
    if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
        if "nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None:
            nezha_agent_path = INSTALL_DIR / "nezha-agent"
            if nezha_agent_path.exists():
                os.chmod(nezha_agent_path, 0o755)
                # ==== 代码修改处 #2 ====
                # 构建基础命令
                command = [str(nezha_agent_path), '-s', config["NEZHA_SERVER"], '-p', config["NEZHA_KEY"]]
                # 如果 NEZHA_TLS 为 False，则添加 --disable-tls 参数
                if not config["NEZHA_TLS"]:
                    command.append('--disable-tls')

                with open(LOG_FILE, 'a') as log_f: # 使用 'a' 模式追加日志
                    st.session_state.nezha_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
            else:
                st.warning("Nezha配置已提供，但找不到 nezha-agent 可执行文件！")

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

        # 安装 sing-box
        if not (INSTALL_DIR / "sing-box").exists():
            status.update(label="正在下载 sing-box...")
            sb_version = "1.9.0-beta.11"
            sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/sing-box-{sb_version}-linux-{arch}.tar.gz"
            tar_path = INSTALL_DIR / "sing-box.tar.gz"
            if download_file(sb_url, tar_path):
                import tarfile
                with tarfile.open(tar_path, "r:gz") as tar:
                    shutil.move(tar.extractfile(f"sing-box-{sb_version}-linux-{arch}/sing-box"), INSTALL_DIR / "sing-box")
                tar_path.unlink()

        # 安装 cloudflared
        if not (INSTALL_DIR / "cloudflared").exists():
            status.update(label="正在下载 cloudflared...")
            cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            if not download_file(cf_url, INSTALL_DIR / "cloudflared"):
                status.update(label="下载 cloudflared 失败", state="error"); return

        # 安装哪吒探针
        if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
            if not (INSTALL_DIR / "nezha-agent").exists():
                status.update(label="正在下载 Nezha Agent...")
                nezha_url = f"https://github.com/nezhahq/agent/releases/download/v1.13.0/nezha-agent_linux_{arch}.zip"
                zip_path = INSTALL_DIR / "nezha-agent.zip"
                if download_file(nezha_url, zip_path):
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(INSTALL_DIR)
                    zip_path.unlink()

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

if app_config.get("NEZHA_SERVER"):
    tls_status = "启用TLS" if app_config["NEZHA_TLS"] else "禁用TLS (no-tls)"
    st.info(f"Nezha 探针已启用，将连接到: `{app_config['NEZHA_SERVER']}` (模式: {tls_status})")

if "installed" not in st.session_state:
    install_and_run(app_config)
    st.rerun()
else:
    st.success("服务已启动。")
    st.subheader("Vmess 节点链接")
    st.code(st.session_state.links, language="text")

with st.expander("查看当前配置和调试日志"):
    st.json({k: v for k, v in st.session_state.app_config.items() if k != "CF_TOKEN"})
    if LOG_FILE.exists():
        st.code(LOG_FILE.read_text(), language='log')

st.markdown("---")
st.markdown("原作者: wff | 改编: AI for Streamlit")

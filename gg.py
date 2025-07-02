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
# <--- 新增开始
import zipfile # 用于解压 nezha-agent
# <--- 新增结束
import streamlit as st

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 控制面板", layout="centered")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "argo.log"
ALL_NODES_FILE = INSTALL_DIR / "allnodes.txt"

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
        # <--- 新增开始
        # 加载哪吒探针配置，如果未设置则为空字符串
        config["NEZHA_SERVER"] = st.secrets.get("NEZHA_SERVER", "")
        config["NEZHA_KEY"] = st.secrets.get("NEZHA_KEY", "")
        # <--- 新增结束
        return config
    except KeyError as e:
        st.error(f"错误: 缺少必要的 Secret 配置项: {e}。请在应用的 Secrets 中设置它。")
        st.stop()
    except ValueError:
        st.error(f"错误: Secrets 中的 PORT 值 '{port_value}' 不是一个有效的数字。")
        st.stop()

def start_services(config):
    """在Streamlit环境中启动后台服务"""
    if "sb_process" in st.session_state and st.session_state.sb_process.poll() is None:
        pass # 进程已在运行
    else:
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

    if "cf_process" in st.session_state and st.session_state.cf_process.poll() is None:
        pass # 进程已在运行
    else:
        cloudflared_path = INSTALL_DIR / "cloudflared"
        if cloudflared_path.exists():
            os.chmod(cloudflared_path, 0o755)
            command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
            with open(LOG_FILE, 'w') as log_f:
                 st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
        else:
            st.error("找不到 cloudflared 可执行文件！"); st.stop()

    # <--- 新增开始
    # 启动哪吒探针服务 (如果已配置)
    if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
        if "nezha_process" in st.session_state and st.session_state.nezha_process.poll() is None:
            pass # 进程已在运行
        else:
            nezha_agent_path = INSTALL_DIR / "nezha-agent"
            if nezha_agent_path.exists():
                os.chmod(nezha_agent_path, 0o755)
                # v1版本的命令格式: nezha-agent -s <服务器:端口> -p <密钥>
                command = [str(nezha_agent_path), '-s', config["NEZHA_SERVER"], '-p', config["NEZHA_KEY"]]
                with open(LOG_FILE, 'a') as log_f: # 使用 'a' 模式追加日志
                     st.session_state.nezha_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
            else:
                st.warning("Nezha配置已提供，但找不到 nezha-agent 可执行文件！")
    # <--- 新增结束

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
                    import tarfile
                    with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR)
                    shutil.move(INSTALL_DIR / sb_name / "sing-box", singbox_path)
                    shutil.rmtree(INSTALL_DIR / sb_name); tar_path.unlink()
                except Exception as e:
                    status.update(label=f"解压 sing-box 失败: {e}", state="error"); return

        cloudflared_path = INSTALL_DIR / "cloudflared"
        if not cloudflared_path.exists():
            status.update(label="正在下载 cloudflared...")
            cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            if not download_file(cf_url, cloudflared_path):
                status.update(label="下载 cloudflared 失败", state="error"); return

        # <--- 新增开始
        # 下载并安装哪吒探针 (如果已配置)
        if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
            nezha_agent_path = INSTALL_DIR / "nezha-agent"
            if not nezha_agent_path.exists():
                status.update(label="正在下载 Nezha Agent...")
                # ==== 代码修改处 ====
                # 使用最终确认的、来自 'nezhahq/agent' 仓库的有效链接
                nezha_url = f"https://github.com/nezhahq/agent/releases/download/v1.13.0/nezha-agent_linux_{arch}.zip"
                zip_path = INSTALL_DIR / "nezha-agent.zip"
                if download_file(nezha_url, zip_path):
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            zip_ref.extractall(INSTALL_DIR)
                        # 默认解压出来的文件名是 nezha-agent
                        zip_path.unlink() # 删除zip压缩包
                    except Exception as e:
                        status.update(label=f"解压 Nezha Agent 失败: {e}", state="error"); return
        # <--- 新增结束

        status.update(label="正在启动后台服务...")
        start_services(config)

        status.update(label="正在生成节点链接...")
        generate_links_and_save(config)
        status.update(label="初始化完成！", state="complete", expanded=False)

# ======== Streamlit UI 界面 ========
st.title("ArgoSB 部署面板")

# 从 Secrets 加载配置
app_config = load_config()
st.session_state.app_config = app_config # 保存到会话状态
st.markdown(f"**域名:** `{app_config['DOMAIN']}`")

# <--- 新增开始
# 如果配置了哪吒，显示一个提示信息
if app_config.get("NEZHA_SERVER"):
    st.info(f"Nezha 探针已启用，将连接到: `{app_config['NEZHA_SERVER']}`")
# <--- 新增结束

# 检查服务是否已标记为运行
if "installed" in st.session_state and st.session_state.installed:
    st.success("服务已启动。")
    st.subheader("Vmess 节点链接")
    st.code(st.session_state.links, language="text")
else:
    install_and_run(app_config)
    st.rerun()

with st.expander("查看当前配置和调试日志"):
    st.json(st.session_state.app_config)
    if LOG_FILE.exists():
        st.code(LOG_FILE.read_text(), language='log')

st.markdown("---")
st.markdown("原作者: wff | 改编: AI for Streamlit")

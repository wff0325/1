# -*- coding: utf-8 -*-
import os
import sys
import json
import subprocess
import time
import shutil
from pathlib import Path
import urllib.request
import ssl
import zipfile
import streamlit as st
import psutil

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 终极调试面板", layout="wide")
st.title("ArgoSB 终极调试面板")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 状态管理 ========
if 'processes' not in st.session_state:
    st.session_state.processes = {}

# ======== 辅助函数 ========
def download_with_progress(urls, target_path, status_placeholder):
    """尝试从URL列表中下载，直到成功为止。"""
    for i, url in enumerate(urls):
        try:
            status_placeholder.update(label=f"尝试下载 {Path(url).name} (来源 {i+1})...")
            ctx = ssl._create_unverified_context()
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            
            # 验证文件是否有效 (对ZIP文件特别重要)
            if target_path.suffix == '.zip':
                with zipfile.ZipFile(target_path, 'r') as zf_test:
                    if zf_test.testzip() is not None:
                        raise ValueError("下载的ZIP文件已损坏")
            
            status_placeholder.update(label=f"下载成功: {target_path.name}")
            return True
        except Exception as e:
            st.warning(f"从 {url} 下载失败: {e}. 尝试下一个来源...")
    
    st.error(f"所有下载来源均失败: {Path(target_path).name}")
    return False

def stop_process(name):
    """停止并移除一个已记录的进程。"""
    if name in st.session_state.processes:
        try:
            proc = psutil.Process(st.session_state.processes[name].pid)
            proc.kill()
            st.toast(f"进程 {name} 已停止。")
        except psutil.NoSuchProcess:
            st.toast(f"进程 {name} 已不存在。")
        del st.session_state.processes[name]

def kill_all_processes():
    """清理所有可能残留的进程。"""
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    killed_procs = []
    for proc in psutil.process_iter(['cmdline', 'pid']):
        try:
            if proc.info['cmdline']:
                cmd_line = ' '.join(proc.info['cmdline'])
                if any(keyword in cmd_line for keyword in keywords):
                    proc.kill()
                    killed_procs.append(cmd_line)
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    st.session_state.processes = {}
    return killed_procs

# ======== UI 布局 ========
st.header("1. 状态检查与全局控制")

if st.button("清理所有进程并刷新页面", type="primary"):
    killed = kill_all_processes()
    st.success(f"清理完成！已终止 {len(killed)} 个进程。")
    st.write(killed)
    time.sleep(2)
    st.rerun()

# --- 文件和进程状态 ---
col1, col2 = st.columns(2)
with col1:
    st.subheader("文件状态")
    binaries = {"cloudflared": (INSTALL_DIR / "cloudflared").exists(), "sing-box": (INSTALL_DIR / "sing-box").exists()}
    if "NEZHA_SERVER" in st.secrets:
        binaries["nezha-agent"] = (INSTALL_DIR / "nezha-agent").exists()
    st.write(binaries)

with col2:
    st.subheader("进程状态")
    procs_status = {}
    for name, proc in st.session_state.processes.items():
        if proc.poll() is None:
            procs_status[name] = f"Running (PID: {proc.pid})"
        else:
            procs_status[name] = f"Stopped (Exit Code: {proc.poll()})"
    st.write(procs_status)

# --- 下载 ---
if st.button("下载/更新所有必需文件"):
    with st.status("正在下载...", expanded=True) as status:
        arch = "amd64"
        
        cf_urls = [f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"]
        if download_with_progress(cf_urls, INSTALL_DIR / "cloudflared", status):
            os.chmod(INSTALL_DIR / "cloudflared", 0o755)
        
        sb_version="1.9.0-beta.11"; sb_name=f"sing-box-{sb_version}-linux-{arch}"; tar_path=INSTALL_DIR/"sing-box.tar.gz"
        sb_urls = [f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"]
        if download_with_progress(sb_urls, tar_path, status):
            import tarfile;
            with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data')
            shutil.move(INSTALL_DIR/sb_name/"sing-box", INSTALL_DIR/"sing-box"); shutil.rmtree(INSTALL_DIR/sb_name); tar_path.unlink(); os.chmod(INSTALL_DIR/"sing-box", 0o755)

        if "NEZHA_SERVER" in st.secrets:
            zip_path = INSTALL_DIR/"nezha-agent.zip"
            nezha_urls = [
                "https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_amd64.zip", # 官方地址
                "https://github.91chi.fun/https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_amd64.zip" # 镜像地址
            ]
            if download_with_progress(nezha_urls, zip_path, status):
                with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(INSTALL_DIR);
                zip_path.unlink()
        
        status.update(label="操作完成！", state="complete")
    st.rerun()

st.header("2. 服务独立控制与日志")

# --- 控制按钮 ---
service_cols = st.columns(3)
with service_cols[0]:
    if st.button("启动所有服务"):
        kill_all_processes() # 启动前先清理
        # 启动 Cloudflared
        token = st.secrets["CF_TOKEN"]; command = [str(INSTALL_DIR / "cloudflared"), 'tunnel', '--no-autoupdate', 'run', '--token', token]
        st.session_state.processes['cloudflared'] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # 启动 Sing-box
        port = int(st.secrets.get("PORT", random.randint(10000, 20000))); uuid_str = st.secrets.get("UUID", str(uuid.uuid4())); ws_path = "/"
        sb_config = {"log": {"level": "info"}, "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": port, "users": [{"uuid": uuid_str}], "transport": {"type": "ws", "path": ws_path}}], "outbounds": [{"type": "direct"}]}
        (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config))
        command = [str(INSTALL_DIR / "sing-box"), 'run', '-c', str(INSTALL_DIR / "sb.json")]
        st.session_state.processes['sing-box'] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # 启动 Nezha Agent
        if "NEZHA_SERVER" in st.secrets:
            nezha_config = {"SERVER": st.secrets["NEZHA_SERVER"], "PORT": st.secrets["NEZHA_PORT"], "KEY": st.secrets["NEZHA_KEY"], "TLS": st.secrets.get("NEZHA_TLS", False)}
            command = [str(INSTALL_DIR / "nezha-agent"), '-s', f"{nezha_config['SERVER']}:{nezha_config['PORT']}", '-p', nezha_config['KEY']]
            if nezha_config['TLS']: command.append('--tls')
            st.session_state.processes['nezha-agent'] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        st.rerun()

# --- 日志显示 ---
log_tabs = st.tabs(["Cloudflared", "Sing-box", "Nezha Agent"])

with log_tabs[0]:
    st.subheader("Cloudflared Tunnel 日志")
    if 'cloudflared' in st.session_state.processes:
        st.code(st.session_state.processes['cloudflared'].stdout.read(), language="log")

with log_tabs[1]:
    st.subheader("Sing-box (Vmess 服务) 日志")
    if 'sing-box' in st.session_state.processes:
        st.code(st.session_state.processes['sing-box'].stdout.read(), language="log")

with log_tabs[2]:
    st.subheader("Nezha Agent 日志")
    if 'nezha-agent' in st.session_state.processes:
        st.code(st.session_state.processes['nezha-agent'].stdout.read(), language="log")

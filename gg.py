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
st.set_page_config(page_title="ArgoSB 调试面板", layout="wide")
st.title("ArgoSB 交互式调试面板")
st.warning("请按顺序点击按钮进行诊断。")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 辅助函数 (使用纯Python下载) ========
def download_with_progress(url, target_path, status_placeholder):
    try:
        status_placeholder.update(label=f"正在下载 {Path(url).name}...")
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        status_placeholder.update(label=f"下载成功: {target_path.name}")
        return True
    except Exception as e:
        st.error(f"下载文件失败: {url}, 错误: {e}")
        return False

# ======== 状态检查函数 ========
def check_binaries():
    files = {"cloudflared": (INSTALL_DIR / "cloudflared").exists(), "sing-box": (INSTALL_DIR / "sing-box").exists()}
    if "NEZHA_SERVER" in st.secrets:
        files["nezha-agent"] = (INSTALL_DIR / "nezha-agent").exists()
    return files

def check_processes():
    procs = {}
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    for proc in psutil.process_iter(['cmdline', 'pid']):
        try:
            if proc.info['cmdline']:
                cmd_line = ' '.join(proc.info['cmdline'])
                for keyword in keywords:
                    if keyword in cmd_line:
                        procs[keyword] = f"Running (PID: {proc.pid})"
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    return procs

# ======== UI 布局 ========
st.header("1. 状态检查")
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Secrets 配置")
    with st.expander("点击查看已加载的 Secrets", expanded=False):
        secrets_to_show = {k: (v[:8] + '...' if k in ['CF_TOKEN', 'NEZHA_KEY'] else v) for k, v in st.secrets.items()}
        st.json(secrets_to_show)

with col2: st.subheader("文件状态"); st.write(check_binaries())
with col3: st.subheader("进程状态"); st.write(check_processes())

st.header("2. 手动操作")

# --- 操作 1: 下载 ---
if st.button("下载所有必需文件"):
    with st.status("正在下载...", expanded=True) as status:
        arch = "amd64"
        
        cf_path = INSTALL_DIR / "cloudflared"
        if not cf_path.exists():
            cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            if download_with_progress(cf_url, cf_path, status):
                os.chmod(cf_path, 0o755)

        sb_path = INSTALL_DIR / "sing-box"
        if not sb_path.exists():
            sb_version = "1.9.0-beta.11"; sb_name = f"sing-box-{sb_version}-linux-{arch}"; sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"; tar_path = INSTALL_DIR / "sing-box.tar.gz"
            if download_with_progress(sb_url, tar_path, status):
                import tarfile
                with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data')
                shutil.move(INSTALL_DIR / sb_name / "sing-box", sb_path); shutil.rmtree(INSTALL_DIR / sb_name); tar_path.unlink(); os.chmod(sb_path, 0o755)

        status.update(label="所有文件下载完毕！", state="complete")
    st.rerun()

# --- 操作 2: 启动 Cloudflared (关键诊断) ---
st.subheader("关键诊断：启动 Cloudflared")
st.info("这一步将直接运行`cloudflared`命令并显示所有输出。如果这里报错，说明您的 `CF_TOKEN` 极有可能是无效的。")

if st.button("运行 `cloudflared` 并显示日志"):
    if not (INSTALL_DIR / "cloudflared").exists():
        st.error("请先点击上面的按钮下载文件。")
    else:
        try:
            token = st.secrets["CF_TOKEN"]
            command = [str(INSTALL_DIR / "cloudflared"), 'tunnel', '--no-autoupdate', 'run', '--token', token]
            
            with st.spinner("正在运行 `cloudflared`... 将在10秒后显示结果。"):
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                time.sleep(10) # 给 cloudflared 足够的时间打印错误
                
                # 检查进程是否已经退出
                if process.poll() is not None:
                    st.warning("`cloudflared` 进程已经退出。")
                else:
                    st.success("`cloudflared` 进程仍在运行。")

                # 读取所有输出
                stdout_output, stderr_output = process.communicate()
                
                st.subheader("`cloudflared` 命令的输出:")
                if stdout_output: st.text("标准输出 (stdout):"); st.code(stdout_output, language="log")
                if stderr_output: st.text("错误输出 (stderr):"); st.code(stderr_output, language="log")
                
                if not stdout_output and not stderr_output:
                    st.warning("`cloudflared` 没有任何输出就退出了。这极度表明 Token 无效。")
                
                # 清理掉测试进程
                if process.poll() is None: process.kill()

        except KeyError: st.error("错误: 无法在 Secrets 中找到 `CF_TOKEN`。")
        except Exception as e: st.error(f"运行命令时发生未知错误: {e}")

# --- 操作 3: 清理所有进程 ---
if st.button("清理所有残留进程", type="primary"):
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    killed_procs = []
    for proc in psutil.process_iter(['cmdline', 'pid']):
        try:
            if proc.info['cmdline']:
                cmd_line = ' '.join(proc.info['cmdline'])
                if any(keyword in cmd_line for keyword in keywords):
                    proc.kill(); killed_procs.append(cmd_line)
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    st.success(f"清理完成！已终止 {len(killed_procs)} 个进程。"); st.write(killed_procs); st.rerun()

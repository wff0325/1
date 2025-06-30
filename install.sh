#!/bin/bash

# Author: Joey
# Blog: joeyblog.net
# Feedback TG (Feedback Telegram): https://t.me/+ft-zI76oovgwNmRh
# Core Functionality By:
#   - https://github.com/eooce (老王)
# Version: 2.4.8.sh (macOS - sed delimiter, panel URL opening with https default) - Modified by User Request
# Modification: Output Clash API URL directly instead of fetching content.
# Modification 2: Added "Custom Install" option to allow user-defined parameters.

apt install jq -y
# --- Color Definitions ---
COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_BLUE='\033[0;34m' # Added Blue for more variety
COLOR_MAGENTA='\033[0;35m'
COLOR_CYAN='\033[0;36m'
COLOR_WHITE_BOLD='\033[1;37m' # Bold White
COLOR_RESET='\033[0m' # No Color

# --- Helper Functions ---
print_separator() {
  echo -e "${COLOR_BLUE}======================================================================${COLOR_RESET}"
}

print_header() {
  local header_text="$1"
  local color_code="$2"
  if [ -z "$color_code" ]; then
    color_code="${COLOR_WHITE_BOLD}" # Default header color
  fi
  print_separator
  echo -e "${color_code}${header_text}${COLOR_RESET}"
  print_separator
}

# --- Welcome Message ---
print_header "欢迎使用 IBM-sb-ws 增强配置脚本" "${COLOR_GREEN}" # Changed header to green
echo -e "${COLOR_GREEN}  此脚本由 ${COLOR_WHITE_BOLD}Joey (joeyblog.net)${COLOR_GREEN} 维护和增强。${COLOR_RESET}"
echo -e "${COLOR_GREEN}  核心功能由 ${COLOR_WHITE_BOLD}老王 (github.com/eooce)${COLOR_GREEN} 实现。${COLOR_RESET}"
echo
echo -e "${COLOR_GREEN}  老王的相关信息:${COLOR_RESET}"
echo -e "${COLOR_GREEN}    Telegram 群组: ${COLOR_WHITE_BOLD}https://t.me/vps888${COLOR_RESET}"
echo -e "${COLOR_GREEN}    原版脚本编译: ${COLOR_WHITE_BOLD}https://github.com/eooce/sing-box${COLOR_RESET}"
echo
echo -e "${COLOR_GREEN}  如果您对 ${COLOR_WHITE_BOLD}此增强脚本${COLOR_GREEN} 有任何反馈，请通过 Telegram 联系 Joey:${COLOR_RESET}"
echo -e "${COLOR_GREEN}    Joey's Feedback TG: ${COLOR_WHITE_BOLD}https://t.me/+ft-zI76oovgwNmRh${COLOR_RESET}"
print_separator
echo -e "${COLOR_GREEN}>>> 小白用户建议直接一路回车，使用默认配置快速完成部署 <<<${COLOR_RESET}" # This was already green
echo

# --- 读取用户输入的函数 ---
read_input() {
  local prompt_text="$1"
  local variable_name="$2"
  local default_value="$3"
  local advice_text="$4"

  if [ -n "$advice_text" ]; then
    echo -e "${COLOR_CYAN}  ${advice_text}${COLOR_RESET}" # Advice text in Cyan
  fi

  if [ -n "$default_value" ]; then
    read -p "$(echo -e ${COLOR_YELLOW}"[?] ${prompt_text} [${default_value}]: "${COLOR_RESET})" user_input # Prompt in Yellow
    eval "$variable_name=\"${user_input:-$default_value}\""
  else
    read -p "$(echo -e ${COLOR_YELLOW}"[?] ${prompt_text}: "${COLOR_RESET})" user_input
    eval "$variable_name=\"$user_input\""
  fi
  echo # New line for readability
}

# --- 初始化变量 ---
CUSTOM_UUID=""
NEZHA_SERVER=""
NEZHA_PORT=""
NEZHA_KEY=""
ARGO_DOMAIN=""
ARGO_AUTH=""
NAME="ibm"
CFIP="cloudflare.182682.xyz"
CFPORT="443"
CHAT_ID=""
BOT_TOKEN=""
UPLOAD_URL=""
declare -a PREFERRED_ADD_LIST=()

# --- UUID 处理函数 ---
handle_uuid_generation() {
  echo -e "${COLOR_MAGENTA}--- UUID 配置 ---${COLOR_RESET}"
  read_input "请输入您要使用的 UUID (留空则自动生成):" CUSTOM_UUID ""
  if [ -z "$CUSTOM_UUID" ]; then
    if command -v uuidgen &> /dev/null; then
      CUSTOM_UUID=$(uuidgen)
      echo -e "${COLOR_GREEN}  ✓ 已自动生成 UUID: ${COLOR_WHITE_BOLD}$CUSTOM_UUID${COLOR_RESET}"
    else
      echo -e "${COLOR_RED}  ✗ 错误: \`uuidgen\` 命令未找到。请安装 \`uuidgen\` 或手动提供 UUID。${COLOR_RESET}"
      read_input "请手动输入一个 UUID:" CUSTOM_UUID ""
      if [ -z "$CUSTOM_UUID" ]; then
        echo -e "${COLOR_RED}  ✗ 未提供 UUID，脚本无法继续。${COLOR_RESET}"
        exit 1
      fi
    fi
  else
    echo -e "${COLOR_GREEN}  ✓ 将使用您提供的 UUID: ${COLOR_WHITE_BOLD}$CUSTOM_UUID${COLOR_RESET}"
  fi
  echo
}

# --- 执行部署函数 (核心功能，保持不变) ---
run_deployment() {
  print_header "开始部署流程" "${COLOR_CYAN}"
  echo -e "${COLOR_CYAN}  当前配置预览:${COLOR_RESET}"
  echo -e "    ${COLOR_WHITE_BOLD}UUID:${COLOR_RESET} $CUSTOM_UUID"
  echo -e "    ${COLOR_WHITE_BOLD}节点名称 (NAME):${COLOR_RESET} $NAME"
  echo -e "    ${COLOR_WHITE_BOLD}主优选IP (CFIP):${COLOR_RESET} $CFIP (端口: $CFPORT)"
  if [ ${#PREFERRED_ADD_LIST[@]} -gt 0 ]; then
    echo -e "    ${COLOR_WHITE_BOLD}优选IP列表:${COLOR_RESET} ${PREFERRED_ADD_LIST[*]}"
  fi
  if [ -n "$NEZHA_SERVER" ]; then echo -e "    ${COLOR_WHITE_BOLD}Nezha Server:${COLOR_RESET} $NEZHA_SERVER"; fi
  if [ -n "$ARGO_DOMAIN" ]; then echo -e "    ${COLOR_WHITE_BOLD}Argo Domain:${COLOR_RESET} $ARGO_DOMAIN"; fi
  print_separator

  # 导出环境变量
  export UUID="$CUSTOM_UUID"
  export NEZHA_SERVER="$NEZHA_SERVER"
  export NEZHA_PORT="$NEZHA_PORT"
  export NEZHA_KEY="$NEZHA_KEY"
  export ARGO_DOMAIN="$ARGO_DOMAIN"
  export ARGO_AUTH="$ARGO_AUTH"
  export NAME="$NAME"
  export CFIP="$CFIP"
  export CFPORT="$CFPORT"
  export CHAT_ID="$CHAT_ID"
  export BOT_TOKEN="$BOT_TOKEN"
  export UPLOAD_URL="$UPLOAD_URL"

  echo -e "${COLOR_YELLOW}  正在准备执行核心部署脚本 (sb.sh)...${COLOR_RESET}"
  
  SB_SCRIPT_PATH="/tmp/sb_downloaded_script_$(date +%s%N).sh" 
  TMP_SB_OUTPUT_FILE=$(mktemp)
  if [ -z "$TMP_SB_OUTPUT_FILE" ]; then
    echo -e "${COLOR_RED}  ✗ 错误: 无法创建临时文件。${COLOR_RESET}"
    exit 1
  fi

  echo -e "${COLOR_CYAN}  > 正在下载核心脚本...${COLOR_RESET}"
  if curl -Lso "$SB_SCRIPT_PATH" https://main.ssss.nyc.mn/sb.sh; then
    chmod +x "$SB_SCRIPT_PATH"
    echo -e "${COLOR_GREEN}  ✓ 下载完成。${COLOR_RESET}"
    echo -e "${COLOR_CYAN}  > 正在执行核心脚本 (此过程可能需要几分钟，请耐心等待)...${COLOR_RESET}"

    bash "$SB_SCRIPT_PATH" > "$TMP_SB_OUTPUT_FILE" 2>&1 &
    SB_PID=$!

    TIMEOUT_SECONDS=180 
    elapsed_time=0

    local progress_chars="/-\\|"
    local char_idx=0
    while ps -p $SB_PID > /dev/null && [ "$elapsed_time" -lt "$TIMEOUT_SECONDS" ]; do
      printf "\r${COLOR_YELLOW}  [执行中 ${progress_chars:$char_idx:1}] (已用时: ${elapsed_time}s)${COLOR_RESET}"
      char_idx=$(((char_idx + 1) % ${#progress_chars}))
      sleep 1
      elapsed_time=$((elapsed_time + 1))
    done
    printf "\r${COLOR_GREEN}  [核心脚本执行完毕或超时]                                                  ${COLOR_RESET}\n"

    if ps -p $SB_PID > /dev/null; then
      echo -e "${COLOR_RED}  ✗ 核心脚本 (PID: $SB_PID) 执行超时，尝试终止...${COLOR_RESET}"
      kill -SIGTERM $SB_PID; sleep 2 
      if ps -p $SB_PID > /dev/null; then kill -SIGKILL $SB_PID; sleep 1; fi
      if ps -p $SB_PID > /dev/null; then echo -e "${COLOR_RED}    ✗ 无法终止核心脚本。${COLOR_RESET}"; else echo -e "${COLOR_GREEN}    ✓ 核心脚本已终止。${COLOR_RESET}"; fi
    else
      echo -e "${COLOR_GREEN}  ✓ 核心脚本 (PID: $SB_PID) 已执行完毕。${COLOR_RESET}"
      wait $SB_PID; SB_EXEC_EXIT_CODE=$?
      if [ "$SB_EXEC_EXIT_CODE" -ne 0 ]; then echo -e "${COLOR_RED}  警告: 核心脚本退出码为 $SB_EXEC_EXIT_CODE。${COLOR_RESET}"; fi
    fi
    rm "$SB_SCRIPT_PATH"
  else
    echo -e "${COLOR_RED}  ✗ 错误: 下载核心脚本失败。${COLOR_RESET}"
    echo "Error: sb.sh download failed." > "$TMP_SB_OUTPUT_FILE"
  fi
  
  sleep 0.5 
  RAW_SB_OUTPUT=$(cat "$TMP_SB_OUTPUT_FILE")
  rm "$TMP_SB_OUTPUT_FILE"
  echo

  print_header "部署结果分析与链接生成" "${COLOR_CYAN}"
  if [ -z "$RAW_SB_OUTPUT" ]; then
    echo -e "${COLOR_RED}  ✗ 错误: 未能捕获到核心脚本的任何输出。${COLOR_RESET}"
  else
    echo -e "${COLOR_MAGENTA}--- 核心脚本执行结果摘要 ---${COLOR_RESET}"

    ARGO_DOMAIN_OUTPUT=$(echo "$RAW_SB_OUTPUT" | grep "ArgoDomain:")
    if [ -n "$ARGO_DOMAIN_OUTPUT" ]; then
      ARGO_ACTUAL_DOMAIN=$(echo "$ARGO_DOMAIN_OUTPUT" | awk -F': ' '{print $2}')
      echo -e "${COLOR_CYAN}  Argo 域名:${COLOR_RESET} ${COLOR_WHITE_BOLD}${ARGO_ACTUAL_DOMAIN}${COLOR_RESET}"
    else
      echo -e "${COLOR_YELLOW}  未检测到 Argo 域名。${COLOR_RESET}"
      ARGO_ACTUAL_DOMAIN="" 
    fi

    ORIGINAL_VMESS_LINK=$(echo "$RAW_SB_OUTPUT" | grep "vmess://" | head -n 1)
    declare -a GENERATED_VMESS_LINKS_ARRAY=()

    if [ -z "$ORIGINAL_VMESS_LINK" ]; then
      echo -e "${COLOR_YELLOW}  未检测到 VMess 链接。${COLOR_RESET}"
    else
      echo -e "${COLOR_GREEN}  正在处理 VMess 配置链接...${COLOR_RESET}"
      if ! command -v jq &> /dev/null; then
        echo -e "${COLOR_YELLOW}  警告: 'jq' 命令未找到。无法生成多个优选地址的 VMess 或 Clash 订阅。${COLOR_RESET}"
      elif ! command -v base64 &> /dev/null; then
        echo -e "${COLOR_RED}  错误: 'base64' 命令未找到。${COLOR_RESET}"
      else
        BASE64_DECODE_CMD="base64 -d"; BASE64_ENCODE_CMD="base64 -w0" 
        if [[ "$(uname)" == "Darwin" ]]; then BASE64_DECODE_CMD="base64 -D"; BASE64_ENCODE_CMD="base64"; fi
        BASE64_PART=$(echo "$ORIGINAL_VMESS_LINK" | sed 's/vmess:\/\///')
        JSON_CONFIG=$($BASE64_DECODE_CMD <<< "$BASE64_PART" 2>/dev/null) 

        if [ -z "$JSON_CONFIG" ]; then
          echo -e "${COLOR_RED}    ✗ VMess 链接解码失败。${COLOR_RESET}"
        else
          ORIGINAL_PS=$(echo "$JSON_CONFIG" | jq -r .ps 2>/dev/null); if [[ -z "$ORIGINAL_PS" || "$ORIGINAL_PS" == "null" ]]; then ORIGINAL_PS="节点"; fi
          
          # 组合主CFIP和优选列表
          COMBINED_IP_LIST=("$CFIP")
          if [ ${#PREFERRED_ADD_LIST[@]} -gt 0 ]; then
              COMBINED_IP_LIST+=("${PREFERRED_ADD_LIST[@]}")
          fi
          UNIQUE_PREFERRED_ADD_LIST=($(echo "${COMBINED_IP_LIST[@]}" | tr ' ' '\n' | sort -u | tr '\n' ' '))

          echo -e "${COLOR_GREEN}  生成的多个优选地址 VMess 配置链接:${COLOR_RESET}"
          for target_add in "${UNIQUE_PREFERRED_ADD_LIST[@]}"; do
            SANITIZED_TARGET_ADD=$(echo "$target_add" | sed 's/[^a-zA-Z0-9_.-]/_/g')
            NEW_PS="${ORIGINAL_PS}-优选-${SANITIZED_TARGET_ADD}"
            MODIFIED_JSON=$(echo "$JSON_CONFIG" | jq --arg new_add "$target_add" --arg new_ps "$NEW_PS" '.add = $new_add | .ps = $new_ps')
            if [ -n "$MODIFIED_JSON" ]; then
              MODIFIED_BASE64=$(echo -n "$MODIFIED_JSON" | $BASE64_ENCODE_CMD)
              GENERATED_VMESS_LINK="vmess://${MODIFIED_BASE64}"
              echo -e "    ${COLOR_WHITE_BOLD}${GENERATED_VMESS_LINK}${COLOR_RESET}"
              GENERATED_VMESS_LINKS_ARRAY+=("$GENERATED_VMESS_LINK")
            else
              echo -e "${COLOR_YELLOW}      为地址 $target_add 生成 VMess 失败。${COLOR_RESET}"
            fi
          done
        fi
      fi
    fi
    echo 

    if [ ${#GENERATED_VMESS_LINKS_ARRAY[@]} -gt 0 ]; then
      if ! command -v jq &> /dev/null; then
          echo -e "${COLOR_YELLOW}  警告: 'jq' 未找到，无法生成 Clash 订阅。${COLOR_RESET}"
      else
        echo -e "${COLOR_MAGENTA}--- Clash 订阅链接 (通过 api.wcc.best) ---${COLOR_RESET}"
        RAW_VMESS_STRING=""; for i in "${!GENERATED_VMESS_LINKS_ARRAY[@]}"; do RAW_VMESS_STRING+="${GENERATED_VMESS_LINKS_ARRAY[$i]}"; if [ $i -lt $((${#GENERATED_VMESS_LINKS_ARRAY[@]} - 1)) ]; then RAW_VMESS_STRING+="|"; fi; done
        ENCODED_VMESS_STRING=$(echo -n "$RAW_VMESS_STRING" | jq -Rr @uri)
        CONFIG_URL_RAW="https://raw.githubusercontent.com/byJoey/test/refs/heads/main/tist.ini"; CONFIG_URL_ENCODED=$(echo -n "$CONFIG_URL_RAW" | jq -Rr @uri)
        CLASH_API_BASE_URL="https://api.wcc.best/sub"
        CLASH_API_PARAMS="target=clash&url=${ENCODED_VMESS_STRING}&insert=false&config=${CONFIG_URL_ENCODED}&emoji=true&list=false&tfo=false&scv=true&fdn=false&expand=true&sort=false&new_name=true"
        FINAL_CLASH_API_URL="${CLASH_API_BASE_URL}?${CLASH_API_PARAMS}"
        
        echo -e "${COLOR_GREEN}  ✓ Clash 订阅 URL:${COLOR_RESET}"
        echo -e "    ${COLOR_WHITE_BOLD}${FINAL_CLASH_API_URL}${COLOR_RESET}"
      fi
    else
      echo -e "${COLOR_YELLOW}  没有可用的 VMess 链接来生成 Clash 订阅。${COLOR_RESET}"
    fi
    echo

    SUB_SAVE_STATUS=$(echo "$RAW_SB_OUTPUT" | grep "\.\/\.tmp\/sub\.txt saved successfully")
    if [ -n "$SUB_SAVE_STATUS" ]; then
      echo -e "${COLOR_GREEN}  ✓ 订阅文件 (.tmp/sub.txt):${COLOR_RESET} 已成功保存。"
    fi

    INSTALL_COMPLETE_MSG=$(echo "$RAW_SB_OUTPUT" | grep "安装完成" | head -n 1)
    if [ -n "$INSTALL_COMPLETE_MSG" ]; then
      echo -e "${COLOR_GREEN}  ✓ 状态:${COLOR_RESET} $INSTALL_COMPLETE_MSG"
    fi

    UNINSTALL_CMD_MSG=$(echo "$RAW_SB_OUTPUT" | grep "一键卸载命令：")
    if [ -n "$UNINSTALL_CMD_MSG" ]; then
      UNINSTALL_ACTUAL_CMD=$(echo "$UNINSTALL_CMD_MSG" | sed 's/一键卸载命令：//' | awk '{$1=$1;print}')
      echo -e "${COLOR_RED}  一键卸载命令:${COLOR_RESET} ${COLOR_WHITE_BOLD}${UNINSTALL_ACTUAL_CMD}${COLOR_RESET}"
    fi
  fi 
  
  print_header "部署完成与支持信息" "${COLOR_GREEN}"
  echo -e "${COLOR_GREEN}  IBM-sb-ws 节点部署流程已执行完毕!${COLOR_RESET}"
  echo
  echo -e "${COLOR_GREEN}  感谢byJoey和原作者老王 ${COLOR_RESET}"
  print_separator
}


# --- 主菜单 ---
print_header "IBM-sb-ws 部署模式选择" "${COLOR_CYAN}"
echo -e "${COLOR_WHITE_BOLD}  1) 推荐安装${COLOR_RESET} (快速部署，仅需确认UUID和优选IP)"
echo -e "${COLOR_WHITE_BOLD}  2) 自定义安装${COLOR_RESET} (可自定义节点名、端口、Nezha、Argo等)"
echo -e "${COLOR_WHITE_BOLD}  Q) 退出脚本${COLOR_RESET}"
print_separator
read -p "$(echo -e ${COLOR_YELLOW}"请输入选项 [1]: "${COLOR_RESET})" main_choice
main_choice=${main_choice:-1} 

case "$main_choice" in
  1) 
    echo
    print_header "推荐安装模式" "${COLOR_MAGENTA}"
    echo -e "${COLOR_CYAN}此模式将使用最简配置。节点名称默认为 'ibm'。${COLOR_RESET}"
    echo
    handle_uuid_generation 
    
    DEFAULT_PREFERRED_IPS_REC="cloudflare.182682.xyz,joeyblog.net"
    read_input "请输入优选IP或域名列表 (逗号隔开, 留空则使用默认: ${DEFAULT_PREFERRED_IPS_REC}):" USER_PREFERRED_IPS_INPUT_REC "${DEFAULT_PREFERRED_IPS_REC}"
    
    PREFERRED_ADD_LIST=() 
    IFS=',' read -r -a temp_array_rec <<< "$USER_PREFERRED_IPS_INPUT_REC"
    for item in "${temp_array_rec[@]}"; do
      trimmed_item=$(echo "$item" | xargs) 
      if [ -n "$trimmed_item" ]; then 
          PREFERRED_ADD_LIST+=("$trimmed_item")
      fi
    done

    # 设置推荐模式的默认值
    NAME="ibm" 
    CFIP="cloudflare.182682.xyz"
    CFPORT="443" 
    NEZHA_SERVER=""; NEZHA_PORT=""; NEZHA_KEY=""
    ARGO_DOMAIN=""; ARGO_AUTH=""
    CHAT_ID=""; BOT_TOKEN=""; UPLOAD_URL=""
    
    run_deployment
    ;;
  
  2)
    echo
    print_header "自定义安装模式" "${COLOR_MAGENTA}"
    echo -e "${COLOR_CYAN}请根据提示输入您的自定义配置，直接回车将使用括号内的默认值。${COLOR_RESET}"
    echo
    handle_uuid_generation
    
    echo -e "${COLOR_MAGENTA}--- 基础配置 ---${COLOR_RESET}"
    read_input "请输入节点名称 (NAME):" NAME "ibm"
    read_input "请输入主优选IP/域名 (CFIP):" CFIP "cloudflare.182682.xyz"
    read_input "请输入连接端口 (CFPORT):" CFPORT "443"
    
    read_input "请输入其他优选IP/域名列表 (逗号隔开, 可留空):" USER_PREFERRED_IPS_INPUT_CUS ""
    PREFERRED_ADD_LIST=() 
    if [ -n "$USER_PREFERRED_IPS_INPUT_CUS" ]; then
      IFS=',' read -r -a temp_array_cus <<< "$USER_PREFERRED_IPS_INPUT_CUS"
      for item in "${temp_array_cus[@]}"; do
        trimmed_item=$(echo "$item" | xargs) 
        if [ -n "$trimmed_item" ]; then 
            PREFERRED_ADD_LIST+=("$trimmed_item")
        fi
      done
    fi

    echo -e "${COLOR_MAGENTA}--- 高级/可选配置 (留空则禁用) ---${COLOR_RESET}"
    read_input "请输入哪吒(Nezha)监控服务器地址:" NEZHA_SERVER "" "例如: monitor.yourdomain.com"
    read_input "请输入哪吒(Nezha)监控服务器端口:" NEZHA_PORT "" "例如: 5555"
    read_input "请输入哪吒(Nezha)监控密钥:" NEZHA_KEY "" "这是您在 Nezha 面板上看到的密钥"
    read_input "请输入 Argo 隧道域名 (需要托管在CF):" ARGO_DOMAIN "" "例如: tunnel.yourdomain.com"
    read_input "请输入 Argo 隧道认证 (Token 或 JSON):" ARGO_AUTH "" "格式为 'ey...' 或 '{\"a\":\"...\"}'"
    
    # 清空其他未使用的变量
    CHAT_ID=""; BOT_TOKEN=""; UPLOAD_URL=""

    run_deployment
    ;;

  [Qq]*) 
    echo -e "${COLOR_GREEN}已退出向导。感谢使用!${COLOR_RESET}"
    exit 0
    ;;
  *) 
    echo -e "${COLOR_RED}无效选项，脚本将退出。${COLOR_RESET}"
    exit 1
    ;;
esac
exit 0

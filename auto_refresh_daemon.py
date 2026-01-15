"""
Gemini Business 账号自动刷新守护进程
每隔指定时间检查并刷新即将过期的账号
"""
import time
import subprocess
import sys
import os
from datetime import datetime

# 配置
CHECK_INTERVAL_MINUTES = 60  # 检查间隔（分钟）
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "refresh_accounts.py")

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def main():
    log("="*50)
    log("Gemini Business 账号自动刷新守护进程启动")
    log(f"检查间隔: {CHECK_INTERVAL_MINUTES} 分钟")
    log("="*50)
    
    while True:
        try:
            log("开始检查账号...")
            result = subprocess.run(
                [sys.executable, SCRIPT_PATH],
                capture_output=False,
                text=True
            )
            log(f"刷新脚本执行完成，退出码: {result.returncode}")
        except Exception as e:
            log(f"执行出错: {e}")
        
        log(f"下次检查时间: {CHECK_INTERVAL_MINUTES} 分钟后")
        log("-"*50)
        time.sleep(CHECK_INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()

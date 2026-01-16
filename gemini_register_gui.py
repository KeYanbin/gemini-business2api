"""
Gemini Business 注册机 - Web 界面
在 Windows 本地运行，提供可视化配置和实时监控
"""
import json
import os
import sys
import threading
import time
from datetime import datetime
from collections import deque
from flask import Flask, render_template, jsonify, request

# 配置文件路径
CONFIG_FILE = "register_config.json"

# 默认配置
DEFAULT_CONFIG = {
    "remote_api_url": "",
    "remote_admin_key": "",
    "remote_path_prefix": "",
    "total_accounts": 10,
    "parallel_workers": 5,
    "mail_api": "https://mail.chatgpt.org.uk",
    "mail_key": "gpt-test",
    "save_to_local_db": True,
    "headless": False  # 无头模式：不显示浏览器窗口
}

# 全局状态
app = Flask(__name__, template_folder="templates/register")
register_status = {
    "status": "idle",  # idle, running, stopping
    "total": 0,
    "current": 0,
    "success": 0,
    "failed": 0,
    "start_time": None,
    "threads": []
}
register_logs = deque(maxlen=500)
register_lock = threading.Lock()
stop_flag = threading.Event()


def load_config():
    """加载配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置
                return {**DEFAULT_CONFIG, **config}
        except:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    """保存配置"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def add_log(message, level="INFO", worker_id=None):
    """添加日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = f"[W{worker_id}]" if worker_id is not None else ""
    with register_lock:
        register_logs.append({
            "time": timestamp,
            "level": level,
            "message": f"{prefix} {message}"
        })


# ========== 路由 ==========

@app.route("/")
def index():
    """主页"""
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """获取配置"""
    return jsonify(load_config())


@app.route("/api/config", methods=["PUT"])
def update_config():
    """更新配置"""
    try:
        new_config = request.json
        save_config(new_config)
        return jsonify({"status": "success", "message": "配置已保存"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def get_status():
    """获取注册状态"""
    with register_lock:
        elapsed = 0
        if register_status["start_time"]:
            elapsed = int(time.time() - register_status["start_time"])
        
        return jsonify({
            **register_status,
            "elapsed_seconds": elapsed,
            "logs": list(register_logs)[-100:]
        })


@app.route("/api/start", methods=["POST"])
def start_register():
    """开始注册"""
    global register_status
    
    if register_status["status"] == "running":
        return jsonify({"status": "error", "message": "注册已在运行中"}), 400
    
    config = load_config()
    stop_flag.clear()
    
    # 重置状态
    with register_lock:
        register_status = {
            "status": "running",
            "total": config["total_accounts"],
            "current": 0,
            "success": 0,
            "failed": 0,
            "start_time": time.time(),
            "threads": []
        }
        register_logs.clear()
    
    add_log(f"开始注册，目标: {config['total_accounts']} 个账户")
    
    # 启动注册线程
    thread = threading.Thread(target=run_register, args=(config,), daemon=True)
    thread.start()
    
    return jsonify({"status": "success", "message": "注册已启动"})


@app.route("/api/stop", methods=["POST"])
def stop_register():
    """停止注册"""
    global register_status
    
    if register_status["status"] != "running":
        return jsonify({"status": "error", "message": "注册未在运行"}), 400
    
    stop_flag.set()
    with register_lock:
        register_status["status"] = "stopping"
    
    add_log("正在停止注册...")
    return jsonify({"status": "success", "message": "正在停止"})


# 保存原始 log 函数引用（避免重复包装）
_original_log = None

def run_register(config):
    """运行注册任务"""
    global register_status, _original_log

    try:
        # 动态导入注册模块
        import gemini_register as reg

        # 更新注册模块配置
        reg.TOTAL_ACCOUNTS = config["total_accounts"]
        reg.PARALLEL_WORKERS = config["parallel_workers"]
        reg.MAIL_API = config["mail_api"]
        reg.MAIL_KEY = config["mail_key"]
        reg.SAVE_TO_DB = config["save_to_local_db"]
        reg.REMOTE_API_URL = config["remote_api_url"]
        reg.REMOTE_ADMIN_KEY = config["remote_admin_key"]
        reg.REMOTE_PATH_PREFIX = config["remote_path_prefix"]
        reg.HEADLESS = config.get("headless", False)  # 无头模式

        # 重写日志函数（只在首次时保存原始引用，避免嵌套包装）
        if _original_log is None:
            _original_log = reg.log

        def custom_log(msg, level="INFO", worker_id=None):
            add_log(msg, level, worker_id)
            _original_log(msg, level, worker_id)
        reg.log = custom_log
        
        # 运行注册
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        with ThreadPoolExecutor(max_workers=config["parallel_workers"]) as executor:
            futures = []
            for i in range(config["total_accounts"]):
                if stop_flag.is_set():
                    break
                worker_id = i % config["parallel_workers"]
                future = executor.submit(reg.register_single, worker_id)
                futures.append(future)
                time.sleep(0.5)
            
            for future in as_completed(futures):
                if stop_flag.is_set():
                    break
                try:
                    email, success, elapsed = future.result()
                    with register_lock:
                        register_status["current"] += 1
                        if success:
                            register_status["success"] += 1
                        else:
                            register_status["failed"] += 1
                except Exception as e:
                    add_log(f"任务异常: {e}", "ERROR")
                    with register_lock:
                        register_status["current"] += 1
                        register_status["failed"] += 1
        
        add_log(f"注册完成！成功: {register_status['success']}, 失败: {register_status['failed']}")
        
    except Exception as e:
        add_log(f"注册异常: {e}", "ERROR")
    finally:
        with register_lock:
            register_status["status"] = "idle"


if __name__ == "__main__":
    print("=" * 50)
    print("Gemini Business 注册机")
    print("访问 http://localhost:5000 打开界面")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)

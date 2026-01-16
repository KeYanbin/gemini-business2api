import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time, random, json, os, sys, requests

# 获取脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 切换工作目录到脚本所在目录，确保数据库写入正确位置
os.chdir(SCRIPT_DIR)

# 添加当前目录到路径
sys.path.insert(0, SCRIPT_DIR)

from core.database import init_database, save_account

# 初始化数据库
init_database()

# 加载配置文件
CONFIG_FILE = os.path.join(SCRIPT_DIR, "register_config.json")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        _config = json.load(f)
    TOTAL_ACCOUNTS = _config.get("total_accounts", 10)
    PARALLEL_WORKERS = _config.get("parallel_workers", 5)
    SAVE_TO_DB = _config.get("save_to_local_db", True)
    MAIL_API = _config.get("mail_api", "https://mail.chatgpt.org.uk")
    MAIL_KEY = _config.get("mail_key", "gpt-test")
    REMOTE_API_URL = _config.get("remote_api_url", "")
    REMOTE_ADMIN_KEY = _config.get("remote_admin_key", "")
    REMOTE_PATH_PREFIX = _config.get("remote_path_prefix", "")
    HEADLESS = _config.get("headless", False)  # 无头模式
    print(f"[INFO] 已加载配置: {CONFIG_FILE}")
    if REMOTE_API_URL:
        print(f"[INFO] 远程上传: {REMOTE_API_URL}")
    if HEADLESS:
        print(f"[INFO] 无头模式: 已启用")
else:
    # 默认配置
    TOTAL_ACCOUNTS = 10
    PARALLEL_WORKERS = 5
    SAVE_TO_DB = True
    MAIL_API = "https://mail.chatgpt.org.uk"
    MAIL_KEY = "gpt-test"
    REMOTE_API_URL = ""
    REMOTE_ADMIN_KEY = ""
    REMOTE_PATH_PREFIX = ""
    HEADLESS = False  # 无头模式
    print(f"[WARN] 配置文件不存在: {CONFIG_FILE}，使用默认配置")

OUTPUT_DIR = "gemini_accounts"
LOGIN_URL = "https://auth.business.gemini.google/login?continueUrl=https:%2F%2Fbusiness.gemini.google%2F&wiffid=CAoSJDIwNTlhYzBjLTVlMmMtNGUxZS1hY2JkLThmOGY2ZDE0ODM1Mg"

# XPath 和 CSS 选择器
XPATH = {
    "email_input": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[1]/div[1]/div/span[2]/input",
    "continue_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/button",
    "verify_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/div[1]/span/div[1]/button",
}

# 更稳定的 CSS 选择器
CSS = {
    "email_input": [
        "input[type='email']",
        "input[name='email']",
        "input[autocomplete='email']",
        "input[placeholder*='mail']",
        "input[placeholder*='邮箱']",
    ],
    "continue_btn": [
        "button[type='submit']",
        "button.continue-btn",
        "form button",
    ],
}

NAMES = ["James Smith", "John Johnson", "Robert Williams", "Michael Brown", "William Jones",
         "David Garcia", "Mary Miller", "Patricia Davis", "Jennifer Rodriguez", "Linda Martinez"]

# 线程安全的计数器和锁
stats_lock = threading.Lock()
driver_lock = threading.Lock()  # 驱动创建锁，避免文件冲突
log_lock = threading.Lock()  # 日志文件写入锁
progress_counter = 0
success_counter = 0
fail_counter = 0

# 日志目录和文件
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"register_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

def log(msg, level="INFO", worker_id=None):
    """记录日志到控制台和文件"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = f"[W{worker_id}]" if worker_id is not None else ""
    log_line = f"[{timestamp}] [{level}] {prefix} {msg}"

    # 控制台输出
    print(log_line)

    # 写入日志文件（线程安全）
    with log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass  # 日志写入失败不影响主流程

def create_email(worker_id=None):
    """创建临时邮箱"""
    try:
        r = requests.get(f"{MAIL_API}/api/generate-email",
            headers={"X-API-Key": MAIL_KEY}, timeout=30)
        if r.status_code == 200 and r.json().get('success'):
            email = r.json()['data']['email']
            log(f"邮箱创建: {email}", worker_id=worker_id)
            return email
    except Exception as e:
        log(f"创建邮箱失败: {e}", "ERR", worker_id)
    return None

def get_code(email, timeout=60, worker_id=None):
    """获取验证码"""
    log(f"等待验证码... (邮箱: {email})", worker_id=worker_id)
    start = time.time()
    check_count = 0
    while time.time() - start < timeout:
        check_count += 1
        try:
            r = requests.get(f"{MAIL_API}/api/emails", params={"email": email},
                headers={"X-API-Key": MAIL_KEY}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                emails = data.get('data', {}).get('emails', [])
                if emails:
                    log(f"收到 {len(emails)} 封邮件，解析验证码...", worker_id=worker_id)
                    html = emails[0].get('html_content') or emails[0].get('content', '')
                    soup = BeautifulSoup(html, 'html.parser')
                    span = soup.find('span', class_='verification-code')
                    if span:
                        code = span.get_text().strip()
                        if len(code) == 6:
                            log(f"验证码: {code}", worker_id=worker_id)
                            return code
                    else:
                        # 尝试其他方式提取验证码
                        import re
                        code_match = re.search(r'\b(\d{6})\b', html)
                        if code_match:
                            code = code_match.group(1)
                            log(f"验证码(正则): {code}", worker_id=worker_id)
                            return code
                        log(f"邮件中未找到验证码格式", "WARN", worker_id)
            elif r.status_code != 200:
                if check_count == 1:
                    log(f"邮件API返回: {r.status_code}", "WARN", worker_id)
        except Exception as e:
            if check_count == 1:
                log(f"邮件API异常: {e}", "WARN", worker_id)
        time.sleep(1.5)
    log(f"验证码超时 ({timeout}s, 检查{check_count}次)", "ERR", worker_id)
    return None

def save_config(email, driver, timeout=10, worker_id=None):
    """保存配置，带轮询等待所有字段"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 轮询等待所有关键字段出现
    log(f"等待配置数据 (最多{timeout}s)...", worker_id=worker_id)
    start = time.time()
    data = None

    while time.time() - start < timeout:
        cookies = driver.get_cookies()
        url = driver.current_url
        parsed = urlparse(url)

        # 解析 config_id
        path_parts = url.split('/')
        config_id = None
        for i, p in enumerate(path_parts):
            if p == 'cid' and i+1 < len(path_parts):
                config_id = path_parts[i+1].split('?')[0]
                break

        # 获取 cookies
        cookie_dict = {c['name']: c for c in cookies}
        ses_cookie = cookie_dict.get('__Secure-C_SES', {})
        host_cookie = cookie_dict.get('__Host-C_OSES', {})

        # 获取 csesidx
        csesidx = parse_qs(parsed.query).get('csesidx', [None])[0]

        # 检查所有关键字段是否都有值
        if (ses_cookie.get('value') and
            host_cookie.get('value') and
            csesidx and
            config_id):

            data = {
                "id": email,
                "csesidx": csesidx,
                "config_id": config_id,
                "secure_c_ses": ses_cookie.get('value'),
                "host_c_oses": host_cookie.get('value'),
                "expires_at": datetime.fromtimestamp(ses_cookie.get('expiry', 0) - 43200).strftime('%Y-%m-%d %H:%M:%S') if ses_cookie.get('expiry') else None
            }
            log(f"配置数据已就绪 ({time.time() - start:.1f}s)", worker_id=worker_id)
            break

        time.sleep(1)

    if not data:
        # 最后一次尝试，记录缺失字段
        cookies = driver.get_cookies()
        url = driver.current_url
        parsed = urlparse(url)
        cookie_dict = {c['name']: c for c in cookies}

        missing = []
        if not cookie_dict.get('__Secure-C_SES', {}).get('value'): missing.append('secure_c_ses')
        if not cookie_dict.get('__Host-C_OSES', {}).get('value'): missing.append('host_c_oses')
        if not parse_qs(parsed.query).get('csesidx', [None])[0]: missing.append('csesidx')

        path_parts = url.split('/')
        has_config_id = False
        for i, p in enumerate(path_parts):
            if p == 'cid' and i+1 < len(path_parts):
                has_config_id = True
                break
        if not has_config_id: missing.append('config_id')

        log(f"配置不完整，缺失字段: {', '.join(missing)}，跳过: {email}", "WARN", worker_id)
        return None

    # 保存到数据库或JSON文件
    if SAVE_TO_DB:
        if save_account(data):
            log(f"已保存到数据库: {email}", worker_id=worker_id)
        else:
            log(f"数据库保存失败: {email}", "ERR", worker_id)
    else:
        with open(f"{OUTPUT_DIR}/{email}.json", 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log(f"已保存: {email}.json", worker_id=worker_id)
    return data

def upload_to_remote(account_data, worker_id=None):
    """上传账户到远程服务器"""
    if not REMOTE_API_URL or not REMOTE_ADMIN_KEY:
        return None
    
    try:
        # 构建上传 URL（去除尾部斜杠避免重定向导致 405）
        base_url = REMOTE_API_URL.rstrip('/')
        if REMOTE_PATH_PREFIX:
            url = f"{base_url}/{REMOTE_PATH_PREFIX.strip('/')}/accounts/upload"
        else:
            url = f"{base_url}/admin/accounts/upload"
        
        response = requests.post(
            url,
            json={"accounts": [account_data]},
            headers={"X-Admin-Key": REMOTE_ADMIN_KEY},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            log(f"远程上传成功: {result.get('message', 'OK')}", worker_id=worker_id)
            return result
        else:
            log(f"远程上传失败: HTTP {response.status_code} - {response.text[:100]}", "ERR", worker_id)
            return None
    except Exception as e:
        log(f"远程上传异常: {e}", "ERR", worker_id)
        return None

def fast_type(element, text, delay=0.05):
    """快速输入文本，增加稳定性"""
    for c in text:
        element.send_keys(c)
        time.sleep(delay + random.uniform(0.01, 0.03))  # 添加随机延迟，更像人类输入

def register_single(worker_id):
    """单个worker的注册流程，每个worker独立创建浏览器"""
    global progress_counter, success_counter, fail_counter
    
    driver = None
    try:
        # 创建浏览器（加锁避免文件冲突）
        log("创建浏览器...", worker_id=worker_id)
        with driver_lock:
            options = uc.ChromeOptions()
            # 无头模式配置 - 增强反检测
            if HEADLESS:
                options.add_argument('--headless=new')  # Chrome 109+ 新版无头模式
                options.add_argument('--disable-gpu')
                options.add_argument('--window-size=1920,1080')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                # 增强反检测参数
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--disable-infobars')
                options.add_argument('--disable-extensions')
                options.add_argument('--disable-popup-blocking')
                options.add_argument('--ignore-certificate-errors')
                # 模拟真实用户代理
                options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
                log("无头模式已启用(增强反检测)", worker_id=worker_id)
            driver = uc.Chrome(options=options, use_subprocess=True, headless=HEADLESS, version_main=None)
            time.sleep(2)  # 等待驱动完全初始化

        start_time = time.time()

        # 1. 创建邮箱
        email = create_email(worker_id)
        if not email:
            return None, False, 0

        wait = WebDriverWait(driver, 30)

        # 2. 访问登录页
        driver.get(LOGIN_URL)
        time.sleep(2)

        # 无头模式：注入反检测脚本
        if HEADLESS:
            driver.execute_script("""
                // 隐藏 webdriver 属性
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                // 模拟真实 Chrome
                window.chrome = { runtime: {} };
                // 修改 plugins 长度
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                // 修改 languages
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            """)
            log("反检测脚本已注入", worker_id=worker_id)

        time.sleep(1)

        # 3. 输入邮箱 - 直接使用 XPath
        log("输入邮箱...", worker_id=worker_id)
        inp = None
        
        try:
            inp = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH["email_input"])))
            log("找到邮箱输入框", worker_id=worker_id)
        except:
            log("未找到邮箱输入框", "ERR", worker_id)
            return email, False, time.time() - start_time
        
        for attempt in range(5):  # 增加重试次数到5次
            try:
                # 确保输入框已聚焦并稳定
                driver.execute_script("arguments[0].focus();", inp)
                time.sleep(0.3)
                inp.click()
                time.sleep(0.5)

                # 彻底清空输入框
                inp.clear()
                time.sleep(0.2)
                driver.execute_script("arguments[0].value = '';", inp)
                time.sleep(0.3)

                # 第一次尝试使用 send_keys，后续使用 JS 方式更稳定
                if attempt < 2:
                    fast_type(inp, email, delay=0.08)  # 增加输入延迟
                    time.sleep(1.2)  # 增加等待时间让 Angular 更新
                else:
                    # 使用 JS 直接设置值并触发完整的事件序列
                    driver.execute_script("""
                        var el = arguments[0];
                        var value = arguments[1];
                        el.focus();
                        el.value = '';

                        // 模拟真实输入：逐字符触发事件
                        for (var i = 0; i < value.length; i++) {
                            el.value = value.substring(0, i + 1);
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    """, inp, email)
                    time.sleep(1.0)

                # 等待 Angular 更新后再验证
                time.sleep(0.5)
                actual_value = inp.get_attribute('value')

                if actual_value == email:
                    log(f"邮箱{' (JS)' if attempt >= 2 else ''}: {email}", worker_id=worker_id)
                    break
                else:
                    log(f"邮箱输入不完整: '{actual_value}' (尝试 {attempt+1}/5)", "WARN", worker_id)
                    time.sleep(0.5)

            except Exception as e:
                log(f"邮箱输入异常: {e} (尝试 {attempt+1}/5)", "WARN", worker_id)
                time.sleep(0.5)
        else:
            log(f"邮箱输入失败，跳过: {email}", "ERR", worker_id)
            return email, False, time.time() - start_time
        
        # 4. 点击继续 - 使用多种选择器
        time.sleep(0.5)
        btn = None
        for selector in CSS["continue_btn"]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    break
            except:
                continue
        
        if not btn:
            try:
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH["continue_btn"])))
            except:
                log("未找到继续按钮", "ERR", worker_id)
                return email, False, time.time() - start_time
        
        driver.execute_script("arguments[0].click();", btn)
        log("点击继续", worker_id=worker_id)
        
        # 5. 获取验证码
        time.sleep(1)
        code = get_code(email, worker_id=worker_id)
        if not code:
            return email, False, time.time() - start_time
        
        # 6. 输入验证码
        # 重要：Google 的 OTP 输入框需要正确聚焦并触发事件
        time.sleep(2)  # 等待验证码页面加载
        log(f"输入验证码: {code}", worker_id=worker_id)
        code_entered = False

        for attempt in range(5):  # 最多5次尝试
            try:
                # 查找 pinInput（Google 标准 OTP 输入框）
                pin_input = None
                try:
                    pin_input = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='pinInput']"))
                    )
                except:
                    try:
                        pin_input = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='text']"))
                        )
                    except:
                        pass

                if not pin_input:
                    log(f"未找到验证码输入框，重试 ({attempt+1}/5)...", "WARN", worker_id)
                    time.sleep(1)
                    continue

                # 首先检查 input 是否已有正确的值（避免不必要的重试）
                current_value = pin_input.get_attribute('value') or ''
                if len(current_value) == 6:
                    log(f"验证码已输入: {current_value}", worker_id=worker_id)
                    code_entered = True
                    break

                # 只在第一次或值不完整时才输入
                if attempt == 0 or len(current_value) < 6:
                    # 使用 ActionChains 确保正确聚焦
                    actions = ActionChains(driver)

                    # 清空现有内容（如果有的话）
                    if current_value:
                        # 先点击输入框确保聚焦
                        actions.move_to_element(pin_input).click().perform()
                        time.sleep(0.2)
                        # 全选并删除
                        pin_input.send_keys(Keys.CONTROL + "a")
                        time.sleep(0.1)
                        pin_input.send_keys(Keys.DELETE)
                        time.sleep(0.3)

                    # 方法1：尝试使用 ActionChains 点击并输入
                    try:
                        # 优先点击 span[data-index='0'] 聚焦到第一个位置
                        first_span = driver.find_element(By.CSS_SELECTOR, "span[data-index='0']")
                        actions = ActionChains(driver)
                        actions.move_to_element(first_span).click().perform()
                        time.sleep(0.3)
                    except:
                        # 备用：直接点击 input
                        actions = ActionChains(driver)
                        actions.move_to_element(pin_input).click().perform()
                        time.sleep(0.3)

                    # 逐字符输入验证码（直接向 pin_input 发送，更可靠）
                    for i, char in enumerate(code):
                        # 每个字符都确保发送到正确的元素
                        pin_input.send_keys(char)
                        time.sleep(0.08 + random.uniform(0.02, 0.05))

                        # 每输入2个字符检查一次，确保输入成功
                        if (i + 1) % 2 == 0:
                            check_value = pin_input.get_attribute('value') or ''
                            if len(check_value) < i + 1:
                                # 输入可能丢失，重新聚焦
                                pin_input.click()
                                time.sleep(0.1)

                    # 触发 input 和 change 事件，确保页面响应
                    driver.execute_script("""
                        var el = arguments[0];
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                    """, pin_input)

                # 等待页面处理完成
                time.sleep(1.5)

                # 优先检查 input 的 value（这是最可靠的）
                actual_value = pin_input.get_attribute('value') or ''
                if len(actual_value) == 6:
                    log(f"验证码已输入: {actual_value}", worker_id=worker_id)
                    code_entered = True
                    break

                # 备用：检查 span 显示框
                spans = driver.find_elements(By.CSS_SELECTOR, "span[data-index]")
                if spans and len(spans) >= 6:
                    entered_code = ''.join([sp.text for sp in spans[:6]])
                    if len(entered_code) == 6:
                        log(f"验证码已输入: {entered_code}", worker_id=worker_id)
                        code_entered = True
                        break

                # 如果还是失败，尝试备用方法：直接用 JS 模拟键盘输入
                if attempt >= 2 and len(actual_value) < 6:
                    log(f"尝试 JS 输入方法...", "INFO", worker_id)
                    try:
                        # 清空并重新输入
                        driver.execute_script("""
                            var input = arguments[0];
                            var code = arguments[1];
                            input.focus();
                            input.value = '';
                            for (var i = 0; i < code.length; i++) {
                                input.value += code[i];
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                            }
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                        """, pin_input, code)
                        time.sleep(1.0)
                        actual_value = pin_input.get_attribute('value') or ''
                        if len(actual_value) == 6:
                            log(f"验证码已输入(JS): {actual_value}", worker_id=worker_id)
                            code_entered = True
                            break
                    except Exception as js_err:
                        log(f"JS 输入失败: {js_err}", "WARN", worker_id)

                log(f"验证码显示不完整: input='{actual_value}'，重试 ({attempt+1}/5)...", "WARN", worker_id)
                time.sleep(0.8 + random.uniform(0.2, 0.5))

            except Exception as e:
                log(f"验证码输入尝试 {attempt+1} 失败: {e}", "WARN", worker_id)
                time.sleep(1)

        if not code_entered:
            log("验证码输入失败", "ERR", worker_id)
            return email, False, time.time() - start_time
        
        # 7. 点击验证按钮
        time.sleep(0.5)
        try:
            # 优先找提交按钮
            verify_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", verify_btn)
            log("点击验证", worker_id=worker_id)
        except:
            try:
                vbtn = driver.find_element(By.XPATH, XPATH["verify_btn"])
                driver.execute_script("arguments[0].click();", vbtn)
                log("点击验证", worker_id=worker_id)
            except:
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if '验证' in btn.text or 'Verify' in btn.text:
                        driver.execute_script("arguments[0].click();", btn)
                        log("点击验证", worker_id=worker_id)
                        break
        
        # 等待验证完成（页面跳转）
        log("等待验证完成...", worker_id=worker_id)
        for _ in range(30):  # 最多等30秒
            time.sleep(1)
            current_url = driver.current_url
            # 检查是否离开了验证码页面
            if "verify-oob-code" not in current_url and "accountverification" not in current_url:
                log("验证成功，页面已跳转", worker_id=worker_id)
                break
            # 检查是否有错误提示
            try:
                error_elem = driver.find_element(By.CSS_SELECTOR, ".PPGJnc .B34EJ")
                error_text = error_elem.text
                if "无效" in error_text or "错误" in error_text or "invalid" in error_text.lower():
                    log(f"验证码错误: {error_text}", "ERR", worker_id)
                    return email, False, time.time() - start_time
            except:
                pass
        else:
            log("等待验证完成超时", "WARN", worker_id)
        
        # 8. 输入姓名
        log("等待姓名输入页面...", worker_id=worker_id)
        
        # 等待页面跳转（离开登录确认页面）
        for _ in range(30):  # 最多等30秒
            time.sleep(1)
            page_text = driver.page_source
            # 检查是否还在加载页面
            if "正在登录" in page_text or "Signing in" in page_text:
                continue
            # 检查是否到达姓名输入页面（有 fullName 输入框或包含相关文字）
            if "fullName" in page_text or "全名" in page_text or "Full name" in page_text:
                log("姓名页面已加载", worker_id=worker_id)
                break
        else:
            log("等待姓名页面超时", "WARN", worker_id)
        
        time.sleep(1)  # 额外等待1秒确保页面稳定
        
        # 调试：保存姓名页面 HTML
        try:
            debug_file = f"debug_name_page_w{worker_id}.html"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            log(f"已保存调试 HTML: {debug_file}", worker_id=worker_id)
        except Exception as e:
            log(f"保存调试 HTML 失败: {e}", "WARN", worker_id)
        
        try:
            selectors = [
                "input[formcontrolname='fullName']",
                "input[placeholder='全名']",
                "input[placeholder='Full name']",
                "input#mat-input-0",
            ]
            name = random.choice(NAMES)
            name_entered = False
            
            for attempt in range(5):  # 最多重试5次
                try:
                    # 每次都重新查找元素
                    name_inp = None
                    found_sel = None
                    for _ in range(15):  # 等待元素出现，最多15秒
                        for sel in selectors:
                            try:
                                elem = driver.find_element(By.CSS_SELECTOR, sel)
                                if elem.is_displayed():
                                    name_inp = elem
                                    found_sel = sel
                                    break
                            except:
                                continue
                        if name_inp:
                            break
                        time.sleep(1)
                    
                    # 如果专用选择器都没找到，尝试通用选择器
                    if not name_inp:
                        try:
                            # 查找所有 text 输入框，排除已有值的
                            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                            for inp in inputs:
                                if inp.is_displayed() and not inp.get_attribute('value'):
                                    name_inp = inp
                                    found_sel = "input[type='text']"
                                    break
                        except:
                            pass
                    
                    if not name_inp:
                        if attempt < 4:
                            log(f"未找到姓名输入框，重试 ({attempt+1}/5)...", "WARN", worker_id)
                            time.sleep(2)
                            continue
                        log("未找到姓名输入框", "ERR", worker_id)
                        return email, False, time.time() - start_time
                    
                    if attempt == 0:
                        log(f"找到姓名输入框: {found_sel}", worker_id=worker_id)
                    
                    # 先点击聚焦
                    try:
                        name_inp.click()
                        time.sleep(0.3)
                    except:
                        pass
                    
                    # 使用 JS 直接设置值
                    driver.execute_script("""
                        var el = arguments[0];
                        el.focus();
                        el.value = '';
                        el.value = arguments[1];
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    """, name_inp, name)
                    time.sleep(0.5)
                    
                    # 验证输入
                    actual_name = driver.execute_script("return arguments[0].value;", name_inp)
                    if actual_name == name:
                        log(f"姓名: {name}", worker_id=worker_id)

                        # 点击同意按钮（而非仅用 Enter 提交）
                        try:
                            # 优先查找 agree-button
                            agree_btn = driver.find_element(By.CSS_SELECTOR, "button.agree-button")
                            driver.execute_script("arguments[0].click();", agree_btn)
                            log(f"点击同意按钮", worker_id=worker_id)
                        except:
                            try:
                                # 备用：查找 type='submit' 的按钮
                                submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                                driver.execute_script("arguments[0].click();", submit_btn)
                                log(f"点击提交按钮", worker_id=worker_id)
                            except:
                                # 最后备用：用 Enter 提交
                                name_inp.send_keys(Keys.ENTER)
                                log(f"回车提交", worker_id=worker_id)

                        name_entered = True
                        break
                    else:
                        log(f"姓名输入验证失败: '{actual_name}'，重试 ({attempt+1}/5)...", "WARN", worker_id)
                        time.sleep(1)
                        
                except Exception as e:
                    if "stale element" in str(e).lower():
                        log(f"元素已刷新，重试 ({attempt+1}/5)...", "WARN", worker_id)
                        time.sleep(1)
                        continue
                    else:
                        raise
            
            if not name_entered:
                log("姓名输入失败", "ERR", worker_id)
                return email, False, time.time() - start_time
                
            time.sleep(0.8)
        except Exception as e:
            log(f"姓名输入异常: {e}", "ERR", worker_id)
            return email, False, time.time() - start_time
        
        # 9. 等待进入工作台
        log("等待工作台...", worker_id=worker_id)
        for _ in range(45):  # 增加等待时间到45秒
            time.sleep(1)
            url = driver.current_url
            if 'business.gemini.google' in url and '/cid/' in url:
                log(f"已进入工作台", worker_id=worker_id)
                break
        else:
            log(f"未跳转到带 cid 的页面", "WARN", worker_id)
        
        # 10. 保存配置
        elapsed = time.time() - start_time
        config = save_config(email, driver, timeout=15, worker_id=worker_id)  # 增加配置等待时间到15秒
        if config:
            # 尝试上传到远程服务器
            upload_to_remote(config, worker_id=worker_id)
            log(f"注册成功: {email} (耗时: {elapsed:.1f}s)", worker_id=worker_id)
            return email, True, elapsed
        return email, False, elapsed
        
    except Exception as e:
        log(f"异常: {e}", "ERR", worker_id)
        return None, False, 0
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def worker_task(task_id, worker_id):
    """Worker任务：执行一次注册"""
    global progress_counter, success_counter, fail_counter
    
    email, success, elapsed = register_single(worker_id)
    
    with stats_lock:
        progress_counter += 1
        if success:
            success_counter += 1
        else:
            fail_counter += 1
        current_progress = progress_counter
        current_success = success_counter
        current_fail = fail_counter
    
    print(f"\n[进度 {current_progress}/{TOTAL_ACCOUNTS}] 成功: {current_success} | 失败: {current_fail}")
    return email, success, elapsed

def main():
    global progress_counter, success_counter, fail_counter
    
    print(f"\n{'='*60}")
    print(f"Gemini Business 并行批量注册")
    print(f"总数: {TOTAL_ACCOUNTS} | 并行线程: {PARALLEL_WORKERS}")
    print(f"{'='*60}\n")
    
    start_time = time.time()
    results = []
    times = []
    
    # 使用线程池并行注册
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        futures = []
        for i in range(TOTAL_ACCOUNTS):
            worker_id = i % PARALLEL_WORKERS
            future = executor.submit(worker_task, i, worker_id)
            futures.append(future)
            # 错开启动时间，避免同时创建浏览器
            time.sleep(0.5)
        
        # 等待所有任务完成
        for future in as_completed(futures):
            try:
                email, success, elapsed = future.result()
                if success:
                    times.append(elapsed)
                results.append((email, success, elapsed))
            except Exception as e:
                log(f"任务异常: {e}", "ERR")
    
    # 统计信息
    total_elapsed = time.time() - start_time
    avg = sum(times) / len(times) if times else 0
    min_t = min(times) if times else 0
    max_t = max(times) if times else 0
    
    print(f"\n{'='*60}")
    print(f"完成! 成功: {success_counter}, 失败: {fail_counter}")
    print(f"总耗时: {total_elapsed:.1f}s | 平均单个: {avg:.1f}s")
    print(f"最快: {min_t:.1f}s | 最慢: {max_t:.1f}s")
    print(f"并行效率: {(avg * TOTAL_ACCOUNTS / total_elapsed):.1f}x")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
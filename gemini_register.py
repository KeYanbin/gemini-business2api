import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
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
    print(f"[INFO] 已加载配置: {CONFIG_FILE}")
    if REMOTE_API_URL:
        print(f"[INFO] 远程上传: {REMOTE_API_URL}")
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
progress_counter = 0
success_counter = 0
fail_counter = 0

def log(msg, level="INFO", worker_id=None):
    prefix = f"[W{worker_id}]" if worker_id is not None else ""
    print(f"{prefix}[{level}] {msg}")

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
    log(f"等待验证码...", worker_id=worker_id)
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{MAIL_API}/api/emails", params={"email": email},
                headers={"X-API-Key": MAIL_KEY}, timeout=10)
            if r.status_code == 200:
                emails = r.json().get('data', {}).get('emails', [])
                if emails:
                    html = emails[0].get('html_content') or emails[0].get('content', '')
                    soup = BeautifulSoup(html, 'html.parser')
                    span = soup.find('span', class_='verification-code')
                    if span:
                        code = span.get_text().strip()
                        if len(code) == 6:
                            log(f"验证码: {code}", worker_id=worker_id)
                            return code
        except: pass
        time.sleep(1.5)  # 缩短轮询间隔
    log("验证码超时", "ERR", worker_id)
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

def fast_type(element, text, delay=0.03):
    """快速输入文本，增加稳定性"""
    for c in text:
        element.send_keys(c)
        time.sleep(delay + random.uniform(0, 0.02))  # 添加随机延迟，更像人类输入

def register_single(worker_id):
    """单个worker的注册流程，每个worker独立创建浏览器"""
    global progress_counter, success_counter, fail_counter
    
    driver = None
    try:
        # 创建浏览器（加锁避免文件冲突）
        log("创建浏览器...", worker_id=worker_id)
        with driver_lock:
            options = uc.ChromeOptions()
            driver = uc.Chrome(options=options, use_subprocess=True)
            time.sleep(2)  # 等待驱动完全初始化
        
        start_time = time.time()
        
        # 1. 创建邮箱
        email = create_email(worker_id)
        if not email:
            return None, False, 0
        
        wait = WebDriverWait(driver, 30)
        
        # 2. 访问登录页
        driver.get(LOGIN_URL)
        time.sleep(3)  # 增加等待页面加载时间
        
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
            inp.click()
            time.sleep(0.5)  # 增加等待时间
            inp.clear()
            time.sleep(0.3)
            
            # 使用 JavaScript 清空并设置值作为备选方案
            if attempt >= 2:
                driver.execute_script("arguments[0].value = '';", inp)
                time.sleep(0.2)
            
            fast_type(inp, email, delay=0.06)  # 增加输入延迟
            time.sleep(0.8)  # 增加等待时间让输入完成
            
            actual_value = inp.get_attribute('value')
            if actual_value == email:
                log(f"邮箱: {email}", worker_id=worker_id)
                break
            else:
                log(f"邮箱输入不完整: '{actual_value}' (尝试 {attempt+1}/5)", "WARN", worker_id)
                # 尝试用 JS 直接设置值并触发事件
                if attempt >= 3:
                    driver.execute_script("""
                        arguments[0].value = arguments[1];
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                    """, inp, email)
                    time.sleep(0.5)
                    actual_value = inp.get_attribute('value')
                    if actual_value == email:
                        log(f"邮箱(JS): {email}", worker_id=worker_id)
                        break
                inp.clear()
                time.sleep(0.8)
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
        # 重要：Google 的 OTP 输入框必须用 send_keys 逐字符输入，不能用 JS 设置 value
        time.sleep(2)  # 等待验证码页面加载
        log(f"输入验证码: {code}", worker_id=worker_id)
        code_entered = False

        for attempt in range(3):  # 最多重试3次
            try:
                # 方案1：查找 pinInput（Google 标准 OTP 输入框）
                pin_input = None
                try:
                    pin_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='pinInput']"))
                    )
                except:
                    # 方案2：查找任意可见的文本输入框
                    try:
                        pin_input = WebDriverWait(driver, 5).until(
                            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
                        )
                    except:
                        pass

                if not pin_input:
                    log(f"未找到验证码输入框，重试 ({attempt+1}/3)...", "WARN", worker_id)
                    time.sleep(1)
                    continue

                # 点击第一个显示框或输入框来聚焦
                try:
                    first_span = driver.find_element(By.CSS_SELECTOR, "span[data-index='0']")
                    first_span.click()
                    time.sleep(0.2)
                except:
                    pin_input.click()
                    time.sleep(0.2)

                # 关键：使用 send_keys 逐字符输入，触发页面的键盘事件处理
                # 不能用 JS 设置 value，否则显示框不会更新！
                for char in code:
                    driver.switch_to.active_element.send_keys(char)
                    time.sleep(0.05 + random.uniform(0, 0.03))  # 模拟人类输入速度

                time.sleep(0.5)

                # 验证输入是否成功：检查 6 个显示框的内容
                spans = driver.find_elements(By.CSS_SELECTOR, "span[data-index]")
                if spans and len(spans) >= 6:
                    entered_code = ''.join([sp.text for sp in spans[:6]])
                    if len(entered_code) == 6:
                        log(f"验证码已输入: {entered_code}", worker_id=worker_id)
                        code_entered = True
                        break
                    else:
                        log(f"验证码显示不完整: '{entered_code}'，重试...", "WARN", worker_id)
                else:
                    # 备用验证：检查 input 的 value
                    actual_value = pin_input.get_attribute('value') if pin_input else ''
                    if actual_value and len(actual_value) >= 6:
                        log(f"验证码已输入: {actual_value}", worker_id=worker_id)
                        code_entered = True
                        break
                    log(f"验证码输入不完整: '{actual_value}'，重试...", "WARN", worker_id)

                # 清空重试
                time.sleep(0.3)
                try:
                    pin_input.clear()
                except:
                    # 用退格键清空
                    for _ in range(6):
                        driver.switch_to.active_element.send_keys(Keys.BACKSPACE)
                        time.sleep(0.05)
                time.sleep(0.3)

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
                        # 提交表单
                        name_inp.send_keys(Keys.ENTER)
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
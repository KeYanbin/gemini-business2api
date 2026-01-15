"""
Gemini Business 账号 Session 自动刷新脚本
功能：为现有账号重新获取 cookies，延长有效期
"""
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import time, random, json, os, requests, sqlite3, sys

# 配置
MAIL_API = "https://mail.chatgpt.org.uk"
MAIL_KEY = "gpt-test"
LOGIN_URL = "https://auth.business.gemini.google/login?continueUrl=https:%2F%2Fbusiness.gemini.google%2F&wiffid=CAoSJDIwNTlhYzBjLTVlMmMtNGUxZS1hY2JkLThmOGY2ZDE0ODM1Mg"
DB_FILE = os.path.join(os.path.dirname(__file__), "data", "accounts.db")
REFRESH_THRESHOLD_HOURS = 3  # 剩余时间少于此值时刷新

# XPath
XPATH = {
    "email_input": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[1]/div[1]/div/span[2]/input",
    "continue_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/button",
    "verify_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/div[1]/span/div[1]/button",
}

def log(msg, level="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

def get_db_connection():
    """获取数据库连接"""
    return sqlite3.connect(DB_FILE)

def get_accounts_to_refresh():
    """获取需要刷新的账号列表"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, expires_at FROM accounts 
        WHERE disabled = 0
        ORDER BY expires_at ASC
    """)
    
    accounts = []
    now = datetime.now()
    
    for row in cursor.fetchall():
        account_id = row["id"]
        expires_at = row["expires_at"]
        
        if expires_at:
            try:
                expire_time = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                remaining_hours = (expire_time - now).total_seconds() / 3600
                
                if remaining_hours < REFRESH_THRESHOLD_HOURS:
                    accounts.append({
                        "id": account_id,
                        "expires_at": expires_at,
                        "remaining_hours": remaining_hours
                    })
            except:
                accounts.append({"id": account_id, "expires_at": expires_at, "remaining_hours": -1})
        else:
            # 没有过期时间的也刷新
            accounts.append({"id": account_id, "expires_at": None, "remaining_hours": -1})
    
    conn.close()
    return accounts

def update_account_cookies(account_id, secure_c_ses, host_c_oses, csesidx, config_id, expires_at):
    """更新账号的 cookies"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE accounts 
        SET secure_c_ses = ?, host_c_oses = ?, csesidx = ?, config_id = ?, 
            expires_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (secure_c_ses, host_c_oses, csesidx, config_id, expires_at, account_id))
    
    conn.commit()
    conn.close()
    log(f"账号 {account_id} cookies 已更新，新过期时间: {expires_at}")

def get_code(email, timeout=60):
    """获取验证码"""
    log(f"等待验证码...")
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
                            log(f"验证码: {code}")
                            return code
        except:
            pass
        print(f"  等待验证码... ({int(time.time()-start)}s)", end='\r')
        time.sleep(2)
    log("验证码超时", "ERR")
    return None

def fast_type(element, text, delay=0.02):
    """快速输入文本"""
    for c in text:
        element.send_keys(c)
        time.sleep(delay)

def refresh_account(driver, email):
    """刷新单个账号的 session"""
    start_time = time.time()
    wait = WebDriverWait(driver, 30)

    # 1. 访问登录页
    driver.get(LOGIN_URL)
    time.sleep(2)

    # 2. 输入邮箱
    log(f"输入邮箱: {email}")
    inp = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH["email_input"])))
    inp.click()
    inp.clear()
    fast_type(inp, email)

    # 3. 点击继续
    time.sleep(0.5)
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH["continue_btn"])))
    driver.execute_script("arguments[0].click();", btn)
    log("点击继续")

    # 4. 获取验证码
    time.sleep(2)
    code = get_code(email)
    if not code:
        return None

    # 5. 输入验证码
    time.sleep(1)
    log(f"输入验证码: {code}")
    try:
        pin = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='pinInput']")))
        pin.click()
        time.sleep(0.1)
        fast_type(pin, code, 0.05)
    except:
        try:
            span = driver.find_element(By.CSS_SELECTOR, "span[data-index='0']")
            span.click()
            time.sleep(0.2)
            driver.switch_to.active_element.send_keys(code)
        except Exception as e:
            log(f"验证码输入失败: {e}", "ERR")
            return None

    # 6. 点击验证
    time.sleep(0.5)
    try:
        vbtn = driver.find_element(By.XPATH, XPATH["verify_btn"])
        driver.execute_script("arguments[0].click();", vbtn)
    except:
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            if '验证' in btn.text or 'Verify' in btn.text:
                driver.execute_script("arguments[0].click();", btn)
                break
    log("点击验证")

    # 7. 等待跳转到工作台（已有账号不需要填姓名）
    log("等待工作台...")
    for _ in range(30):
        time.sleep(1)
        url = driver.current_url
        if 'business.gemini.google' in url and '/cid/' in url:
            log(f"已进入工作台")
            break
    else:
        log(f"未跳转到工作台，当前: {driver.current_url}", "WARN")
        return None

    # 8. 提取新的 cookies
    time.sleep(2)
    cookies = driver.get_cookies()
    url = driver.current_url
    parsed = urlparse(url)

    # 解析 config_id
    path_parts = url.split('/')
    config_id = None
    for i, p in enumerate(path_parts):
        if p == 'cid' and i + 1 < len(path_parts):
            config_id = path_parts[i + 1].split('?')[0]
            break

    # 获取 cookies
    cookie_dict = {c['name']: c for c in cookies}
    ses_cookie = cookie_dict.get('__Secure-C_SES', {})
    host_cookie = cookie_dict.get('__Host-C_OSES', {})
    csesidx = parse_qs(parsed.query).get('csesidx', [None])[0]

    if ses_cookie.get('value') and csesidx and config_id:
        expires_at = None
        if ses_cookie.get('expiry'):
            expires_at = datetime.fromtimestamp(ses_cookie['expiry'] - 43200).strftime('%Y-%m-%d %H:%M:%S')
        
        elapsed = time.time() - start_time
        log(f"刷新成功 (耗时: {elapsed:.1f}s)")
        
        return {
            "secure_c_ses": ses_cookie.get('value'),
            "host_c_oses": host_cookie.get('value'),
            "csesidx": csesidx,
            "config_id": config_id,
            "expires_at": expires_at
        }
    
    log("提取 cookies 失败", "ERR")
    return None

def main():
    # 检查数据库
    if not os.path.exists(DB_FILE):
        log(f"数据库不存在: {DB_FILE}", "ERR")
        return

    # 获取需要刷新的账号
    accounts = get_accounts_to_refresh()
    
    if not accounts:
        log("没有需要刷新的账号")
        return
    
    print(f"\n{'='*50}")
    print(f"需要刷新的账号: {len(accounts)} 个")
    print(f"{'='*50}\n")
    
    for acc in accounts:
        remaining = acc['remaining_hours']
        if remaining >= 0:
            print(f"  - {acc['id']}: 剩余 {remaining:.1f} 小时")
        else:
            print(f"  - {acc['id']}: 已过期或无过期时间")
    
    print()
    
    driver = None
    success, fail = 0, 0
    
    for i, acc in enumerate(accounts):
        email = acc['id']
        print(f"\n{'#'*40}")
        print(f"刷新 {i+1}/{len(accounts)}: {email}")
        print(f"{'#'*40}\n")
        
        # 确保 driver 有效
        if driver is None:
            log("创建浏览器...")
            driver = uc.Chrome(options=uc.ChromeOptions(), use_subprocess=True)
            time.sleep(2)
        
        try:
            result = refresh_account(driver, email)
            if result:
                update_account_cookies(
                    email,
                    result['secure_c_ses'],
                    result['host_c_oses'],
                    result['csesidx'],
                    result['config_id'],
                    result['expires_at']
                )
                success += 1
            else:
                fail += 1
        except Exception as e:
            log(f"异常: {e}", "ERR")
            fail += 1
            try:
                driver.quit()
            except:
                pass
            driver = None
        
        # 清理 cookies 准备下一个
        if driver and i < len(accounts) - 1:
            try:
                driver.delete_all_cookies()
            except:
                pass
            time.sleep(random.randint(2, 3))
    
    if driver:
        try:
            driver.quit()
        except:
            pass
    
    print(f"\n{'='*50}")
    print(f"刷新完成! 成功: {success}, 失败: {fail}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()

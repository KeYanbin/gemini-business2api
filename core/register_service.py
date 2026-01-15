"""注册机服务模块 - 支持多线程并发注册"""
import threading
import time
import random
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
from enum import Enum

logger = logging.getLogger(__name__)


class RegisterStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass 
class RegisterConfig:
    """注册机配置"""
    total_accounts: int = 10
    thread_count: int = 2  # 并发线程数
    mail_api: str = "https://mail.chatgpt.org.uk"
    mail_key: str = "gpt-test"
    db_path: str = "data/accounts.db"
    save_to_db: bool = True


@dataclass
class ThreadStatus:
    """单个线程的状态"""
    thread_id: int
    status: str = "idle"  # idle, running, completed, error
    current_email: str = ""
    current_step: str = ""
    success: int = 0
    failed: int = 0


class RegisterService:
    """多线程注册机服务"""
    
    def __init__(self):
        self.config = RegisterConfig()
        self._stop_flag = False
        self._lock = threading.Lock()
        self._browser_init_lock = threading.Lock()  # 浏览器初始化锁，避免chromedriver文件冲突
        self._input_lock = threading.Lock()  # 输入操作锁，避免多线程输入冲突
        self._executor: Optional[ThreadPoolExecutor] = None
        self._max_logs = 1000
        
        # 全局状态
        self._status = RegisterStatus.IDLE
        self._start_time: Optional[float] = None
        self._total = 0
        self._completed = 0
        self._success = 0
        self._failed = 0
        self._logs: List[Dict[str, str]] = []
        self._thread_statuses: Dict[int, ThreadStatus] = {}
        
        # 任务队列
        self._task_queue: Queue = Queue()
        
    def add_log(self, message: str, level: str = "INFO", thread_id: int = None):
        """添加日志（线程安全）"""
        prefix = f"[线程{thread_id}] " if thread_id is not None else ""
        log_entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": f"{prefix}{message}",
            "thread_id": thread_id
        }
        
        with self._lock:
            self._logs.append(log_entry)
            if len(self._logs) > self._max_logs:
                self._logs = self._logs[-self._max_logs:]
        
        # 同时输出到系统日志
        full_msg = f"[REGISTER] {prefix}{message}"
        if level == "ERROR":
            logger.error(full_msg)
        elif level == "WARN":
            logger.warning(full_msg)
        else:
            logger.info(full_msg)
    
    def update_thread_status(self, thread_id: int, **kwargs):
        """更新线程状态（线程安全）"""
        with self._lock:
            if thread_id not in self._thread_statuses:
                self._thread_statuses[thread_id] = ThreadStatus(thread_id=thread_id)
            for key, value in kwargs.items():
                if hasattr(self._thread_statuses[thread_id], key):
                    setattr(self._thread_statuses[thread_id], key, value)
    
    def increment_counter(self, success: bool):
        """增加计数器（线程安全）"""
        with self._lock:
            self._completed += 1
            if success:
                self._success += 1
            else:
                self._failed += 1
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        elapsed = 0
        if self._start_time:
            elapsed = time.time() - self._start_time
        
        with self._lock:
            thread_infos = []
            for tid, ts in self._thread_statuses.items():
                thread_infos.append({
                    "id": ts.thread_id,
                    "status": ts.status,
                    "email": ts.current_email,
                    "step": ts.current_step,
                    "success": ts.success,
                    "failed": ts.failed
                })
            
            return {
                "status": self._status.value,
                "current": self._completed,
                "total": self._total,
                "success": self._success,
                "failed": self._failed,
                "thread_count": self.config.thread_count,
                "active_threads": len([t for t in thread_infos if t["status"] == "running"]),
                "threads": thread_infos,
                "elapsed_seconds": round(elapsed, 1),
                "logs": self._logs[-100:]
            }
    
    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        return {
            "total_accounts": self.config.total_accounts,
            "thread_count": self.config.thread_count,
            "mail_api": self.config.mail_api,
            "mail_key": self.config.mail_key,
            "db_path": self.config.db_path,
            "save_to_db": self.config.save_to_db
        }
    
    def update_config(self, config: Dict[str, Any]):
        """更新配置"""
        if "total_accounts" in config:
            self.config.total_accounts = max(1, min(100, int(config["total_accounts"])))
        if "thread_count" in config:
            self.config.thread_count = max(1, min(10, int(config["thread_count"])))
        if "mail_api" in config:
            self.config.mail_api = config["mail_api"]
        if "mail_key" in config:
            self.config.mail_key = config["mail_key"]
        if "db_path" in config:
            self.config.db_path = config["db_path"]
        if "save_to_db" in config:
            self.config.save_to_db = bool(config["save_to_db"])
    
    def start(self) -> bool:
        """启动注册任务"""
        if self._status == RegisterStatus.RUNNING:
            return False
        
        self._stop_flag = False
        self._status = RegisterStatus.RUNNING
        self._start_time = time.time()
        self._total = self.config.total_accounts
        self._completed = 0
        self._success = 0
        self._failed = 0
        self._logs = []
        self._thread_statuses = {}
        
        # 填充任务队列
        self._task_queue = Queue()
        for i in range(self.config.total_accounts):
            self._task_queue.put(i + 1)
        
        self.add_log(f"注册任务启动，目标: {self.config.total_accounts} 个账户，线程数: {self.config.thread_count}")
        
        # 启动管理线程
        manager_thread = threading.Thread(target=self._run_manager, daemon=True)
        manager_thread.start()
        
        return True
    
    def stop(self) -> bool:
        """停止注册任务"""
        if self._status != RegisterStatus.RUNNING:
            return False
        
        self._stop_flag = True
        self._status = RegisterStatus.STOPPING
        self.add_log("正在停止注册任务...", "WARN")
        return True
    
    def _run_manager(self):
        """管理线程 - 启动和监控工作线程"""
        try:
            thread_count = min(self.config.thread_count, self.config.total_accounts)
            self._executor = ThreadPoolExecutor(max_workers=thread_count)
            
            # 提交工作线程
            futures = []
            for thread_id in range(thread_count):
                future = self._executor.submit(self._worker_thread, thread_id)
                futures.append(future)
                self.update_thread_status(thread_id, status="running")
            
            # 等待所有线程完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.add_log(f"线程异常: {e}", "ERROR")
            
            self._executor.shutdown(wait=True)
            
        except Exception as e:
            self.add_log(f"管理线程异常: {e}", "ERROR")
            self._status = RegisterStatus.ERROR
        finally:
            if self._status == RegisterStatus.RUNNING or self._status == RegisterStatus.STOPPING:
                self._status = RegisterStatus.IDLE
            self.add_log(f"注册完成! 成功: {self._success}, 失败: {self._failed}")
    
    def _worker_thread(self, thread_id: int):
        """工作线程 - 执行注册任务"""
        driver = None
        
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys
            from bs4 import BeautifulSoup
            from urllib.parse import urlparse, parse_qs
            import requests
        except ImportError as e:
            self.add_log(f"缺少依赖: {e}", "ERROR", thread_id)
            self.update_thread_status(thread_id, status="error")
            return
        
        try:
            from core.database import save_account as db_save_account
        except ImportError:
            self.add_log("无法导入数据库模块", "ERROR", thread_id)
            self.update_thread_status(thread_id, status="error")
            return
        
        LOGIN_URL = "https://auth.business.gemini.google/login?continueUrl=https:%2F%2Fbusiness.gemini.google%2F&wiffid=CAoSJDIwNTlhYzBjLTVlMmMtNGUxZS1hY2JkLThmOGY2ZDE0ODM1Mg"
        XPATH = {
            "email_input": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[1]/div[1]/div/span[2]/input",
            "continue_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/button",
            "verify_btn": "/html/body/c-wiz/div/div/div[1]/div/div/div/form/div[2]/div/div[1]/span/div[1]/button",
        }
        NAMES = ["James Smith", "John Johnson", "Robert Williams", "Michael Brown", "William Jones",
                 "David Garcia", "Mary Miller", "Patricia Davis", "Jennifer Rodriguez", "Linda Martinez"]
        
        def create_email():
            try:
                r = requests.get(f"{self.config.mail_api}/api/generate-email",
                    headers={"X-API-Key": self.config.mail_key}, timeout=30)
                if r.status_code == 200 and r.json().get('success'):
                    return r.json()['data']['email']
            except Exception as e:
                self.add_log(f"创建邮箱失败: {e}", "ERROR", thread_id)
            return None
        
        def get_code(email, timeout=60):
            self.update_thread_status(thread_id, current_step="等待验证码")
            start = time.time()
            while time.time() - start < timeout:
                if self._stop_flag:
                    return None
                try:
                    r = requests.get(f"{self.config.mail_api}/api/emails", 
                        params={"email": email},
                        headers={"X-API-Key": self.config.mail_key}, timeout=10)
                    if r.status_code == 200:
                        emails = r.json().get('data', {}).get('emails', [])
                        if emails:
                            html = emails[0].get('html_content') or emails[0].get('content', '')
                            soup = BeautifulSoup(html, 'html.parser')
                            span = soup.find('span', class_='verification-code')
                            if span:
                                code = span.get_text().strip()
                                if len(code) == 6:
                                    return code
                except:
                    pass
                time.sleep(2)
            return None
        
        def fast_type(element, text, delay=0.05):
            """逐字符输入，模拟真实用户"""
            for c in text:
                element.send_keys(c)
                time.sleep(delay + random.uniform(0, 0.03))
        
        def safe_click(drv, element):
            try:
                element.click()
            except:
                try:
                    drv.execute_script("arguments[0].click();", element)
                except:
                    from selenium.webdriver.common.action_chains import ActionChains
                    ActionChains(drv).move_to_element(element).click().perform()
        
        def wait_and_clear(element):
            for _ in range(3):
                try:
                    element.clear()
                    time.sleep(0.1)
                    if not element.get_attribute('value'):
                        return True
                    element.send_keys(Keys.CONTROL + "a")
                    element.send_keys(Keys.DELETE)
                    time.sleep(0.1)
                    if not element.get_attribute('value'):
                        return True
                except:
                    pass
                time.sleep(0.2)
            return False
        
        def save_config(email, drv, timeout=10):
            self.update_thread_status(thread_id, current_step="保存配置")
            start = time.time()
            
            while time.time() - start < timeout:
                if self._stop_flag:
                    return None
                    
                cookies = drv.get_cookies()
                url = drv.current_url
                parsed = urlparse(url)
                
                path_parts = url.split('/')
                config_id = None
                for i, p in enumerate(path_parts):
                    if p == 'cid' and i+1 < len(path_parts):
                        config_id = path_parts[i+1].split('?')[0]
                        break
                
                cookie_dict = {c['name']: c for c in cookies}
                ses_cookie = cookie_dict.get('__Secure-C_SES', {})
                host_cookie = cookie_dict.get('__Host-C_OSES', {})
                csesidx = parse_qs(parsed.query).get('csesidx', [None])[0]
                
                if (ses_cookie.get('value') and host_cookie.get('value') and csesidx and config_id):
                    data = {
                        "id": email,
                        "csesidx": csesidx,
                        "config_id": config_id,
                        "secure_c_ses": ses_cookie.get('value'),
                        "host_c_oses": host_cookie.get('value'),
                        "expires_at": datetime.fromtimestamp(ses_cookie.get('expiry', 0) - 43200).strftime('%Y-%m-%d %H:%M:%S') if ses_cookie.get('expiry') else None
                    }
                    
                    if self.config.save_to_db:
                        if db_save_account(data):
                            self.add_log(f"已保存: {email}", "INFO", thread_id)
                        else:
                            self.add_log(f"保存失败: {email}", "ERROR", thread_id)
                    return data
                time.sleep(1)
            
            return None
        
        def register_one(drv, task_num):
            """执行单个注册"""
            email = create_email()
            if not email:
                return False
            
            self.update_thread_status(thread_id, current_email=email)
            self.add_log(f"开始注册 #{task_num}: {email}", "INFO", thread_id)
            
            wait = WebDriverWait(drv, 30)
            
            try:
                # 1. 访问登录页
                self.update_thread_status(thread_id, current_step="访问登录页")
                drv.get(LOGIN_URL)
                time.sleep(2)
                
                # 2. 检查页面状态并输入邮箱
                self.update_thread_status(thread_id, current_step="输入邮箱")
                email_entered = False
                for attempt in range(10):
                    current_url = drv.current_url
                    self.add_log(f"当前页面: {current_url[:60]}...", "DEBUG", thread_id)
                    
                    # 检查是否已经登录成功（跳转到工作台）
                    if 'business.gemini.google' in current_url and '/cid/' in current_url:
                        self.add_log(f"已登录，跳过输入", "INFO", thread_id)
                        email_entered = True
                        break
                    
                    # 检查是否在验证码页面
                    if 'pinInput' in drv.page_source or 'verification' in current_url.lower():
                        self.add_log(f"已在验证码页面", "DEBUG", thread_id)
                        break
                    
                    # 尝试找到并输入邮箱
                    try:
                        inp = drv.find_element(By.XPATH, XPATH["email_input"])
                        if inp.is_displayed() and inp.is_enabled():
                            time.sleep(0.3)
                            safe_click(drv, inp)
                            time.sleep(0.2)
                            wait_and_clear(inp)
                            time.sleep(0.1)
                            fast_type(inp, email, delay=0.05)
                            time.sleep(0.3)
                            
                            if inp.get_attribute('value') == email:
                                email_entered = True
                                self.add_log(f"邮箱已输入: {email}", "DEBUG", thread_id)
                                break
                            else:
                                self.add_log(f"邮箱输入不完整，重试", "WARN", thread_id)
                    except Exception as e:
                        self.add_log(f"尝试 {attempt+1}: 等待邮箱输入框... ({e})", "DEBUG", thread_id)
                    
                    time.sleep(1)
                
                if not email_entered and 'pinInput' not in drv.page_source:
                    self.add_log(f"邮箱输入失败，当前URL: {drv.current_url}", "ERROR", thread_id)
                    return False
                
                # 3. 点击继续
                self.update_thread_status(thread_id, current_step="点击继续")
                time.sleep(0.8)
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH["continue_btn"])))
                safe_click(drv, btn)
                
                # 4. 获取验证码
                time.sleep(3)
                code = get_code(email)
                if not code:
                    self.add_log(f"验证码超时: {email}", "ERROR", thread_id)
                    return False
                
                # 5. 输入验证码
                self.update_thread_status(thread_id, current_step="输入验证码")
                time.sleep(1.5)
                
                for attempt in range(5):
                    try:
                        selectors = ["input[name='pinInput']", "input[type='tel']", "input[autocomplete='one-time-code']"]
                        pin = None
                        for sel in selectors:
                            try:
                                pin = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                                if pin and pin.is_displayed():
                                    break
                            except:
                                continue
                        
                        if pin:
                            safe_click(drv, pin)
                            time.sleep(0.3)
                            fast_type(pin, code, delay=0.1)
                            break
                    except:
                        if attempt == 4:
                            # 尝试 span 方式
                            try:
                                span = drv.find_element(By.CSS_SELECTOR, "span[data-index='0']")
                                safe_click(drv, span)
                                time.sleep(0.2)
                                drv.switch_to.active_element.send_keys(code)
                            except:
                                self.add_log(f"验证码输入失败", "ERROR", thread_id)
                                return False
                        time.sleep(1)
                
                # 6. 点击验证
                self.update_thread_status(thread_id, current_step="点击验证")
                time.sleep(1)
                try:
                    vbtn = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH["verify_btn"])))
                    safe_click(drv, vbtn)
                except:
                    for btn in drv.find_elements(By.TAG_NAME, "button"):
                        if '验证' in btn.text or 'Verify' in btn.text:
                            safe_click(drv, btn)
                            break
                
                # 7. 输入姓名
                self.update_thread_status(thread_id, current_step="输入姓名")
                time.sleep(2)
                
                name_selectors = [
                    "input[formcontrolname='fullName']",
                    "input[placeholder='全名']",
                    "input[placeholder='Full name']",
                    "input#mat-input-0",
                ]
                name_inp = None
                
                for _ in range(30):
                    if self._stop_flag:
                        return False
                    for sel in name_selectors:
                        try:
                            name_inp = drv.find_element(By.CSS_SELECTOR, sel)
                            if name_inp.is_displayed():
                                break
                        except:
                            continue
                    if name_inp and name_inp.is_displayed():
                        break
                    time.sleep(1)
                
                if name_inp and name_inp.is_displayed():
                    name = random.choice(NAMES)
                    safe_click(drv, name_inp)
                    time.sleep(0.2)
                    name_inp.clear()
                    fast_type(name_inp, name)
                    time.sleep(0.3)
                    name_inp.send_keys(Keys.ENTER)
                    time.sleep(1)
                else:
                    self.add_log(f"未找到姓名输入框", "ERROR", thread_id)
                    return False
                
                # 8. 等待工作台
                self.update_thread_status(thread_id, current_step="等待工作台")
                for wait_i in range(30):
                    if self._stop_flag:
                        return False
                    time.sleep(1)
                    current = drv.current_url
                    if 'business.gemini.google' in current and '/cid/' in current:
                        break
                    # 如果卡在 /admin/create 页面，尝试点击可能的提交按钮
                    if '/admin/create' in current and wait_i >= 5:
                        try:
                            for btn in drv.find_elements(By.TAG_NAME, "button"):
                                txt = btn.text.lower()
                                if any(k in txt for k in ['create', 'start', 'submit', '创建', '开始', '提交']):
                                    if btn.is_enabled() and btn.is_displayed():
                                        self.add_log(f"尝试点击按钮: {btn.text}", "DEBUG", thread_id)
                                        safe_click(drv, btn)
                                        time.sleep(2)
                                        break
                        except:
                            pass
                
                # 9. 保存配置
                current_url = drv.current_url
                self.add_log(f"当前URL: {current_url}", "DEBUG", thread_id)
                
                cookies = drv.get_cookies()
                cookie_names = [c['name'] for c in cookies]
                has_ses = '__Secure-C_SES' in cookie_names
                has_host = '__Host-C_OSES' in cookie_names
                self.add_log(f"Cookies: SES={has_ses}, HOST={has_host}", "DEBUG", thread_id)
                
                config = save_config(email, drv)
                if config:
                    self.add_log(f"注册成功: {email}", "INFO", thread_id)
                    return True
                else:
                    self.add_log(f"配置保存失败: {email} (URL: {current_url[:80]})", "ERROR", thread_id)
                    return False
                    
            except Exception as e:
                self.add_log(f"注册异常: {e}", "ERROR", thread_id)
                return False
        
        # 工作线程主循环
        try:
            self.add_log(f"等待启动浏览器", "INFO", thread_id)
            self.update_thread_status(thread_id, current_step="等待启动浏览器")
            
            # 使用锁串行化浏览器初始化，避免 chromedriver 文件冲突
            with self._browser_init_lock:
                self.add_log(f"正在启动浏览器", "INFO", thread_id)
                self.update_thread_status(thread_id, current_step="启动浏览器")
                try:
                    options = uc.ChromeOptions()
                    driver = uc.Chrome(options=options, use_subprocess=True)
                    time.sleep(3)  # 等待浏览器完全启动
                except Exception as e:
                    self.add_log(f"浏览器启动失败: {e}", "ERROR", thread_id)
                    self.update_thread_status(thread_id, status="error", current_step=f"启动失败: {e}")
                    return
            
            self.add_log(f"浏览器已启动", "INFO", thread_id)
            
            while not self._stop_flag:
                try:
                    task_num = self._task_queue.get_nowait()
                except Empty:
                    break
                
                success = register_one(driver, task_num)
                self.increment_counter(success)
                
                with self._lock:
                    ts = self._thread_statuses.get(thread_id)
                    if ts:
                        if success:
                            ts.success += 1
                        else:
                            ts.failed += 1
                
                # 清理cookies准备下一个
                if not self._stop_flag:
                    try:
                        driver.delete_all_cookies()
                    except:
                        pass
                    time.sleep(random.randint(1, 2))
            
            self.update_thread_status(thread_id, status="completed", current_step="已完成")
            
        except Exception as e:
            self.add_log(f"工作线程异常: {e}", "ERROR", thread_id)
            self.update_thread_status(thread_id, status="error", current_step=f"错误: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            self.add_log(f"浏览器已关闭", "INFO", thread_id)


# 全局单例
register_service = RegisterService()

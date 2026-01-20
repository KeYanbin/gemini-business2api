"""
Gemini自动化登录模块（用于新账号注册）
"""
import os
import random
import string
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from DrissionPage import ChromiumPage, ChromiumOptions


# 常量
AUTH_HOME_URL = "https://auth.business.gemini.google/"
DEFAULT_XSRF_TOKEN = "KdLRzKwwBTD5wo8nUollAbY6cW0"

# Linux 下常见的 Chromium 路径
CHROMIUM_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def _find_chromium_path() -> Optional[str]:
    """查找可用的 Chromium/Chrome 浏览器路径"""
    for path in CHROMIUM_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class GeminiAutomation:
    """Gemini自动化登录"""

    def __init__(
        self,
        user_agent: str = "",
        proxy: str = "",
        headless: bool = True,
        timeout: int = 60,
        log_callback=None,
    ) -> None:
        self.user_agent = user_agent or self._get_ua()
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.log_callback = log_callback

    def login_and_extract(self, email: str, mail_client) -> dict:
        """执行登录并提取配置"""
        page = None
        user_data_dir = None
        try:
            page = self._create_page()
            user_data_dir = getattr(page, 'user_data_dir', None)
            return self._run_flow(page, email, mail_client)
        except Exception as exc:
            self._log("error", f"automation error: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
            self._cleanup_user_data(user_data_dir)

    def _create_page(self) -> ChromiumPage:
        """创建浏览器页面"""
        options = ChromiumOptions()

        # 自动检测 Chromium 浏览器路径（Linux/Docker 环境）
        chromium_path = _find_chromium_path()
        if chromium_path:
            options.set_browser_path(chromium_path)
            self._log("info", f"using browser: {chromium_path}")

        options.set_argument("--incognito")
        options.set_argument("--no-sandbox")
        options.set_argument("--disable-setuid-sandbox")
        options.set_argument("--disable-blink-features=AutomationControlled")
        options.set_argument("--window-size=1280,800")
        options.set_user_agent(self.user_agent)

        # 语言设置（确保使用中文界面）
        options.set_argument("--lang=zh-CN")
        options.set_pref("intl.accept_languages", "zh-CN,zh")

        if self.proxy:
            options.set_argument(f"--proxy-server={self.proxy}")

        if self.headless:
            # 使用新版无头模式，更接近真实浏览器
            options.set_argument("--headless=new")
            options.set_argument("--disable-gpu")
            options.set_argument("--disable-dev-shm-usage")
            options.set_argument("--no-first-run")
            options.set_argument("--disable-extensions")
            # 增强反检测参数
            options.set_argument("--disable-infobars")
            options.set_argument("--enable-features=NetworkService,NetworkServiceInProcess")
            # 额外的反检测参数
            options.set_argument("--disable-background-networking")
            options.set_argument("--disable-background-timer-throttling")
            options.set_argument("--disable-backgrounding-occluded-windows")
            options.set_argument("--disable-breakpad")
            options.set_argument("--disable-component-update")
            options.set_argument("--disable-default-apps")
            options.set_argument("--disable-domain-reliability")
            options.set_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees,IsolateOrigins,site-per-process")
            options.set_argument("--disable-hang-monitor")
            options.set_argument("--disable-ipc-flooding-protection")
            options.set_argument("--disable-popup-blocking")
            options.set_argument("--disable-prompt-on-repost")
            options.set_argument("--disable-renderer-backgrounding")
            options.set_argument("--disable-sync")
            options.set_argument("--force-color-profile=srgb")
            options.set_argument("--metrics-recording-only")
            options.set_argument("--no-first-run")
            options.set_argument("--password-store=basic")
            options.set_argument("--use-mock-keychain")
            options.set_argument("--export-tagged-pdf")
            # 模拟真实屏幕尺寸
            options.set_argument("--window-position=0,0")

        options.auto_port()
        page = ChromiumPage(options)
        page.set.timeouts(self.timeout)

        # 反检测：注入全面的 stealth 脚本
        self._inject_stealth_scripts(page)

        return page

    def _inject_stealth_scripts(self, page) -> None:
        """注入全面的反检测脚本（基于 puppeteer-extra-stealth）"""
        stealth_js = """
        // ============ 1. 隐藏 webdriver 属性 ============
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });

        // 删除 webdriver 相关痕迹
        delete navigator.__proto__.webdriver;

        // ============ 2. 模拟真实的 plugins 数组 ============
        const mockPlugins = {
            0: {
                0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                description: "Portable Document Format",
                filename: "internal-pdf-viewer",
                length: 1,
                name: "Chrome PDF Plugin"
            },
            1: {
                0: {type: "application/pdf", suffixes: "pdf", description: ""},
                description: "",
                filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                length: 1,
                name: "Chrome PDF Viewer"
            },
            2: {
                0: {type: "application/x-nacl", suffixes: "", description: "Native Client Executable"},
                1: {type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable"},
                description: "",
                filename: "internal-nacl-plugin",
                length: 2,
                name: "Native Client"
            },
            length: 3,
            item: function(i) { return this[i] || null; },
            namedItem: function(name) {
                for (let i = 0; i < this.length; i++) {
                    if (this[i].name === name) return this[i];
                }
                return null;
            },
            refresh: function() {}
        };
        Object.setPrototypeOf(mockPlugins, PluginArray.prototype);
        Object.defineProperty(navigator, 'plugins', {
            get: () => mockPlugins,
            configurable: true
        });

        // ============ 3. 模拟真实的 mimeTypes ============
        const mockMimeTypes = {
            0: {type: "application/pdf", suffixes: "pdf", description: "", enabledPlugin: mockPlugins[1]},
            1: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format", enabledPlugin: mockPlugins[0]},
            2: {type: "application/x-nacl", suffixes: "", description: "Native Client Executable", enabledPlugin: mockPlugins[2]},
            3: {type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable", enabledPlugin: mockPlugins[2]},
            length: 4,
            item: function(i) { return this[i] || null; },
            namedItem: function(name) {
                for (let i = 0; i < this.length; i++) {
                    if (this[i].type === name) return this[i];
                }
                return null;
            }
        };
        Object.setPrototypeOf(mockMimeTypes, MimeTypeArray.prototype);
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => mockMimeTypes,
            configurable: true
        });

        // ============ 4. 完整的 chrome 对象 ============
        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'},
                RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'}
            },
            runtime: {
                OnInstalledReason: {CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update'},
                OnRestartRequiredReason: {APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic'},
                PlatformArch: {ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'},
                PlatformNaclArch: {ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'},
                PlatformOs: {ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win'},
                RequestUpdateCheckStatus: {NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available'},
                connect: function() {},
                sendMessage: function() {}
            },
            csi: function() { return {}; },
            loadTimes: function() {
                return {
                    commitLoadTime: Date.now() / 1000 - Math.random() * 2,
                    connectionInfo: 'h2',
                    finishDocumentLoadTime: Date.now() / 1000 - Math.random(),
                    finishLoadTime: Date.now() / 1000 - Math.random() * 0.5,
                    firstPaintAfterLoadTime: 0,
                    firstPaintTime: Date.now() / 1000 - Math.random() * 1.5,
                    navigationType: 'Other',
                    npnNegotiatedProtocol: 'unknown',
                    requestTime: Date.now() / 1000 - Math.random() * 3,
                    startLoadTime: Date.now() / 1000 - Math.random() * 2.5,
                    wasAlternateProtocolAvailable: false,
                    wasFetchedViaSpdy: true,
                    wasNpnNegotiated: true
                };
            }
        };

        // ============ 5. 语言和平台属性 ============
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            configurable: true
        });
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32',
            configurable: true
        });
        Object.defineProperty(navigator, 'vendor', {
            get: () => 'Google Inc.',
            configurable: true
        });
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: () => 0,
            configurable: true
        });
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8,
            configurable: true
        });
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
            configurable: true
        });

        // ============ 6. 权限 API 模拟 ============
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => {
            if (parameters.name === 'notifications') {
                return Promise.resolve({state: 'prompt', onchange: null});
            }
            if (parameters.name === 'push') {
                return Promise.resolve({state: 'prompt', onchange: null});
            }
            if (parameters.name === 'midi') {
                return Promise.resolve({state: 'prompt', onchange: null});
            }
            return originalQuery.call(navigator.permissions, parameters);
        };

        // ============ 7. WebGL 指纹伪装 ============
        const getParameterProxyHandler = {
            apply: function(target, thisArg, args) {
                const param = args[0];
                const gl = thisArg;
                // UNMASKED_VENDOR_WEBGL
                if (param === 37445) {
                    return 'Google Inc. (NVIDIA)';
                }
                // UNMASKED_RENDERER_WEBGL
                if (param === 37446) {
                    return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)';
                }
                return target.apply(thisArg, args);
            }
        };

        const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = new Proxy(originalGetParameter, getParameterProxyHandler);

        if (typeof WebGL2RenderingContext !== 'undefined') {
            const originalGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = new Proxy(originalGetParameter2, getParameterProxyHandler);
        }

        // ============ 8. Canvas 指纹随机化 ============
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (type === 'image/png' || type === undefined) {
                const context = this.getContext('2d');
                if (context) {
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {
                        // 对每个像素添加微小的随机噪声
                        imageData.data[i] = imageData.data[i] ^ (Math.random() > 0.99 ? 1 : 0);
                    }
                    context.putImageData(imageData, 0, 0);
                }
            }
            return originalToDataURL.apply(this, arguments);
        };

        const originalToBlob = HTMLCanvasElement.prototype.toBlob;
        HTMLCanvasElement.prototype.toBlob = function(callback, type, quality) {
            if (type === 'image/png' || type === undefined) {
                const context = this.getContext('2d');
                if (context) {
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {
                        imageData.data[i] = imageData.data[i] ^ (Math.random() > 0.99 ? 1 : 0);
                    }
                    context.putImageData(imageData, 0, 0);
                }
            }
            return originalToBlob.apply(this, arguments);
        };

        // ============ 9. AudioContext 指纹随机化 ============
        if (typeof AudioContext !== 'undefined') {
            const originalCreateOscillator = AudioContext.prototype.createOscillator;
            AudioContext.prototype.createOscillator = function() {
                const oscillator = originalCreateOscillator.apply(this, arguments);
                oscillator.frequency.value = oscillator.frequency.value + (Math.random() - 0.5) * 0.01;
                return oscillator;
            };
        }

        // ============ 10. 隐藏 Headless 特征 ============
        // 覆盖 User-Agent 中可能的 HeadlessChrome 标记（备用）
        // 注意：必须先保存原始值，避免在 getter 中访问自身导致无限递归
        const originalUserAgent = navigator.userAgent;
        Object.defineProperty(navigator, 'userAgent', {
            get: () => originalUserAgent.replace('HeadlessChrome', 'Chrome'),
            configurable: true
        });

        // 隐藏 window.outerWidth/outerHeight 为 0 的问题
        if (window.outerWidth === 0) {
            Object.defineProperty(window, 'outerWidth', {
                get: () => window.innerWidth,
                configurable: true
            });
        }
        if (window.outerHeight === 0) {
            Object.defineProperty(window, 'outerHeight', {
                get: () => window.innerHeight + 85,
                configurable: true
            });
        }

        // ============ 11. 屏幕属性 ============
        Object.defineProperty(screen, 'colorDepth', {
            get: () => 24,
            configurable: true
        });
        Object.defineProperty(screen, 'pixelDepth', {
            get: () => 24,
            configurable: true
        });

        // ============ 12. 连接信息 ============
        if (navigator.connection === undefined) {
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                }),
                configurable: true
            });
        }

        // ============ 13. Brave 浏览器检测绕过 ============
        Object.defineProperty(navigator, 'brave', {
            get: () => undefined,
            configurable: true
        });

        // ============ 14. 电池 API ============
        if (navigator.getBattery) {
            navigator.getBattery = () => Promise.resolve({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 1,
                addEventListener: () => {},
                removeEventListener: () => {}
            });
        }

        // ============ 15. 隐藏 CDP (Chrome DevTools Protocol) ============
        // 删除可能暴露自动化的调试属性
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

        // 清理 iframe 中的检测
        const originalAttachShadow = Element.prototype.attachShadow;
        Element.prototype.attachShadow = function() {
            if (arguments[0] && arguments[0].mode === 'open') {
                arguments[0] = { mode: 'closed' };
            }
            return originalAttachShadow.apply(this, arguments);
        };

        console.log('[Stealth] Anti-detection scripts loaded successfully');
        """

        try:
            page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=stealth_js)
            self._log("info", "stealth scripts injected successfully")
        except Exception as e:
            self._log("warning", f"failed to inject stealth scripts: {e}")

    def _run_flow(self, page, email: str, mail_client) -> dict:
        """执行登录流程"""

        # 记录开始时间，用于邮件时间过滤
        from datetime import datetime
        send_time = datetime.now()

        # Step 1: 导航到首页并设置 Cookie
        self._log("info", f"navigating to login page for {email}")

        page.get(AUTH_HOME_URL, timeout=self.timeout)
        time.sleep(2)

        # 模拟真人鼠标移动
        self._simulate_mouse_movement(page)

        # 设置两个关键 Cookie
        try:
            page.set.cookies({
                "name": "__Host-AP_SignInXsrf",
                "value": DEFAULT_XSRF_TOKEN,
                "url": AUTH_HOME_URL,
                "path": "/",
                "secure": True,
            })
            # 添加 reCAPTCHA Cookie
            page.set.cookies({
                "name": "_GRECAPTCHA",
                "value": "09ABCL...",
                "url": "https://google.com",
                "path": "/",
                "secure": True,
            })
        except Exception as e:
            self._log("warning", f"failed to set cookies: {e}")

        login_hint = quote(email, safe="")
        login_url = f"https://auth.business.gemini.google/login/email?continueUrl=https%3A%2F%2Fbusiness.gemini.google%2F&loginHint={login_hint}&xsrfToken={DEFAULT_XSRF_TOKEN}"
        page.get(login_url, timeout=self.timeout)

        # 模拟真人等待和鼠标移动
        time.sleep(3)
        self._simulate_mouse_movement(page)
        time.sleep(2)

        # Step 2: 检查当前页面状态
        current_url = page.url
        has_business_params = "business.gemini.google" in current_url and "csesidx=" in current_url and "/cid/" in current_url

        if has_business_params:
            return self._extract_config(page, email)

        # Step 3: 点击发送验证码按钮
        self._log("info", "clicking send verification code button")
        if not self._click_send_code_button(page):
            self._log("error", "send code button not found")
            self._save_screenshot(page, "send_code_button_missing")
            return {"success": False, "error": "send code button not found"}

        # Step 4: 等待验证码输入框出现
        code_input = self._wait_for_code_input(page)
        if not code_input:
            self._log("error", "code input not found")
            self._save_screenshot(page, "code_input_missing")
            return {"success": False, "error": "code input not found"}

        # Step 5: 轮询邮件获取验证码（传入发送时间）
        self._log("info", "polling for verification code")
        code = mail_client.poll_for_code(timeout=40, interval=4, since_time=send_time)

        if not code:
            self._log("warning", "verification code timeout, trying to resend")
            # 更新发送时间（在点击按钮之前记录）
            send_time = datetime.now()
            # 尝试点击重新发送按钮
            if self._click_resend_code_button(page):
                self._log("info", "resend button clicked, waiting for new code")
                # 再次轮询验证码
                code = mail_client.poll_for_code(timeout=40, interval=4, since_time=send_time)
                if not code:
                    self._log("error", "verification code timeout after resend")
                    self._save_screenshot(page, "code_timeout_after_resend")
                    return {"success": False, "error": "verification code timeout after resend"}
            else:
                self._log("error", "verification code timeout and resend button not found")
                self._save_screenshot(page, "code_timeout")
                return {"success": False, "error": "verification code timeout"}

        self._log("info", f"code received: {code}")

        # Step 6: 输入验证码并提交
        code_input = page.ele("css:input[jsname='ovqh0b']", timeout=3) or \
                     page.ele("css:input[type='tel']", timeout=2)

        if not code_input:
            self._log("error", "code input expired")
            return {"success": False, "error": "code input expired"}

        self._log("info", "inputting verification code")
        code_input.input(code, clear=True)
        time.sleep(0.5)

        verify_btn = page.ele("css:button[jsname='XooR8e']", timeout=3)
        if verify_btn:
            self._log("info", "clicking verify button (method 1)")
            verify_btn.click()
        else:
            verify_btn = self._find_verify_button(page)
            if verify_btn:
                self._log("info", "clicking verify button (method 2)")
                verify_btn.click()
            else:
                self._log("info", "pressing enter to submit")
                code_input.input("\n")

        # Step 7: 等待页面自动重定向（提交验证码后 Google 会自动跳转）
        self._log("info", "waiting for auto-redirect after verification")
        time.sleep(12)  # 增加等待时间，让页面有足够时间完成重定向（如果网络慢可以继续增加）

        # 记录当前 URL 状态
        current_url = page.url
        self._log("info", f"current URL after verification: {current_url}")

        # 检查是否还停留在验证码页面（说明提交失败）
        if "verify-oob-code" in current_url:
            self._log("error", "verification code submission failed, still on verification page")
            self._save_screenshot(page, "verification_submit_failed")
            return {"success": False, "error": "verification code submission failed"}

        # Step 8: 处理协议页面（如果有）
        self._handle_agreement_page(page)

        # Step 9: 检查是否已经在正确的页面
        current_url = page.url
        has_business_params = "business.gemini.google" in current_url and "csesidx=" in current_url and "/cid/" in current_url

        if has_business_params:
            # 已经在正确的页面，不需要再次导航
            self._log("info", "already on business page with parameters")
            return self._extract_config(page, email)

        # Step 10: 如果不在正确的页面，尝试导航
        if "business.gemini.google" not in current_url:
            self._log("info", "navigating to business page")
            page.get("https://business.gemini.google/", timeout=self.timeout)
            time.sleep(5)  # 增加等待时间
            current_url = page.url
            self._log("info", f"URL after navigation: {current_url}")

        # Step 11: 检查是否需要设置用户名
        if "cid" not in page.url:
            if self._handle_username_setup(page):
                time.sleep(5)  # 增加等待时间

        # Step 12: 等待 URL 参数生成（csesidx 和 cid）
        self._log("info", "waiting for URL parameters")
        if not self._wait_for_business_params(page):
            self._log("warning", "URL parameters not generated, trying refresh")
            page.refresh()
            time.sleep(5)  # 增加等待时间
            if not self._wait_for_business_params(page):
                self._log("error", "URL parameters generation failed")
                current_url = page.url
                self._log("error", f"final URL: {current_url}")
                self._save_screenshot(page, "params_missing")
                return {"success": False, "error": "URL parameters not found"}

        # Step 13: 提取配置
        self._log("info", "login success")
        return self._extract_config(page, email)

    def _click_send_code_button(self, page) -> bool:
        """点击发送验证码按钮（如果需要）"""
        time.sleep(2)

        # 首先检查是否已经在验证码输入页面（Google 可能已自动发送验证码）
        if self._is_on_code_input_page(page):
            self._log("info", "Already on verification code input page, code auto-sent")
            return True

        # 方法1: 直接通过ID查找
        direct_btn = page.ele("#sign-in-with-email", timeout=5)
        if direct_btn:
            try:
                direct_btn.click()
                return True
            except Exception:
                pass

        # 方法2: 通过关键词查找
        keywords = ["通过电子邮件发送验证码", "通过电子邮件发送", "email", "Email", "Send code", "Send verification", "Verification code"]
        try:
            buttons = page.eles("tag:button")
            for btn in buttons:
                text = (btn.text or "").strip()
                if text and any(kw in text for kw in keywords):
                    try:
                        btn.click()
                        return True
                    except Exception:
                        pass
        except Exception:
            pass

        # 再次检查是否已经在验证码输入页面（可能在查找过程中页面已跳转）
        if self._is_on_code_input_page(page):
            self._log("info", "Now on verification code input page")
            return True

        return False

    def _is_on_code_input_page(self, page) -> bool:
        """检查是否在验证码输入页面"""
        # 使用多种选择器检测验证码输入框
        code_input_selectors = [
            "css:input[jsname='ovqh0b']",
            "css:input[name='pinInput']",
            "css:input[type='tel']",
            "css:input[autocomplete='one-time-code']",
            "css:input[inputmode='numeric']",
            "css:input[maxlength='6']",
        ]

        for selector in code_input_selectors:
            try:
                el = page.ele(selector, timeout=1)
                if el:
                    self._log("info", f"Code input detected with selector: {selector}")
                    return True
            except Exception:
                continue

        # 检查页面文本是否包含验证码相关关键词
        try:
            page_text = page.html or ""
            code_page_keywords = ["输入验证码", "Enter the code", "Verification code", "验证码已发送", "code sent"]
            if any(kw in page_text for kw in code_page_keywords):
                self._log("info", "Code input page detected by keywords")
                return True
        except Exception:
            pass

        return False

    def _wait_for_code_input(self, page, timeout: int = 30):
        """等待验证码输入框出现"""
        selectors = [
            "css:input[jsname='ovqh0b']",
            "css:input[type='tel']",
            "css:input[name='pinInput']",
            "css:input[autocomplete='one-time-code']",
            "css:input[inputmode='numeric']",
            "css:input[maxlength='6']",
        ]
        for _ in range(timeout // 2):
            for selector in selectors:
                try:
                    el = page.ele(selector, timeout=1)
                    if el:
                        self._log("info", f"Code input found: {selector}")
                        return el
                except Exception:
                    continue
            time.sleep(2)
        return None

    def _find_verify_button(self, page):
        """查找验证按钮（排除重新发送按钮）"""
        try:
            buttons = page.eles("tag:button")
            for btn in buttons:
                text = (btn.text or "").strip().lower()
                if text and "重新" not in text and "发送" not in text and "resend" not in text and "send" not in text:
                    return btn
        except Exception:
            pass
        return None

    def _click_resend_code_button(self, page) -> bool:
        """点击重新发送验证码按钮"""
        time.sleep(2)

        # 查找包含重新发送关键词的按钮（与 _find_verify_button 相反）
        try:
            buttons = page.eles("tag:button")
            for btn in buttons:
                text = (btn.text or "").strip().lower()
                if text and ("重新" in text or "resend" in text):
                    try:
                        self._log("info", f"found resend button: {text}")
                        btn.click()
                        time.sleep(2)
                        return True
                    except Exception:
                        pass
        except Exception:
            pass

        return False

    def _handle_agreement_page(self, page) -> None:
        """处理协议页面"""
        if "/admin/create" in page.url:
            agree_btn = page.ele("css:button.agree-button", timeout=5)
            if agree_btn:
                agree_btn.click()
                time.sleep(2)

    def _wait_for_cid(self, page, timeout: int = 10) -> bool:
        """等待URL包含cid"""
        for _ in range(timeout):
            if "cid" in page.url:
                return True
            time.sleep(1)
        return False

    def _wait_for_business_params(self, page, timeout: int = 30) -> bool:
        """等待业务页面参数生成（csesidx 和 cid）"""
        for _ in range(timeout):
            url = page.url
            if "csesidx=" in url and "/cid/" in url:
                self._log("info", f"business params ready: {url}")
                return True
            time.sleep(1)
        return False

    def _handle_username_setup(self, page) -> bool:
        """处理用户名设置页面"""
        current_url = page.url

        if "auth.business.gemini.google/login" in current_url:
            return False

        selectors = [
            "css:input[type='text']",
            "css:input[name='displayName']",
            "css:input[aria-label*='用户名' i]",
            "css:input[aria-label*='display name' i]",
        ]

        username_input = None
        for selector in selectors:
            try:
                username_input = page.ele(selector, timeout=2)
                if username_input:
                    break
            except Exception:
                continue

        if not username_input:
            return False

        suffix = "".join(random.choices(string.ascii_letters + string.digits, k=3))
        username = f"Test{suffix}"

        try:
            username_input.click()
            time.sleep(0.2)
            username_input.clear()
            username_input.input(username)
            time.sleep(0.3)

            buttons = page.eles("tag:button")
            submit_btn = None
            for btn in buttons:
                text = (btn.text or "").strip().lower()
                if any(kw in text for kw in ["确认", "提交", "继续", "submit", "continue", "confirm", "save", "保存", "下一步", "next"]):
                    submit_btn = btn
                    break

            if submit_btn:
                submit_btn.click()
            else:
                username_input.input("\n")

            time.sleep(5)
            return True
        except Exception:
            return False

    def _extract_config(self, page, email: str) -> dict:
        """提取配置"""
        try:
            if "cid/" not in page.url:
                page.get("https://business.gemini.google/", timeout=self.timeout)
                time.sleep(3)

            url = page.url
            if "cid/" not in url:
                return {"success": False, "error": "cid not found"}

            config_id = url.split("cid/")[1].split("?")[0].split("/")[0]
            csesidx = url.split("csesidx=")[1].split("&")[0] if "csesidx=" in url else ""

            cookies = page.cookies()
            ses = next((c["value"] for c in cookies if c["name"] == "__Secure-C_SES"), None)
            host = next((c["value"] for c in cookies if c["name"] == "__Host-C_OSES"), None)

            ses_obj = next((c for c in cookies if c["name"] == "__Secure-C_SES"), None)
            # 使用北京时区，确保时间计算正确（Cookie expiry 是 UTC 时间戳）
            beijing_tz = timezone(timedelta(hours=8))
            if ses_obj and "expiry" in ses_obj:
                # 将 UTC 时间戳转为北京时间，再减去12小时作为刷新窗口
                cookie_expire_beijing = datetime.fromtimestamp(ses_obj["expiry"], tz=beijing_tz)
                expires_at = (cookie_expire_beijing - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                expires_at = (datetime.now(beijing_tz) + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")

            config = {
                "id": email,
                "csesidx": csesidx,
                "config_id": config_id,
                "secure_c_ses": ses,
                "host_c_oses": host,
                "expires_at": expires_at,
            }
            return {"success": True, "config": config}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _save_screenshot(self, page, name: str) -> None:
        """保存截图"""
        try:
            import os
            screenshot_dir = os.path.join("data", "automation")
            os.makedirs(screenshot_dir, exist_ok=True)
            path = os.path.join(screenshot_dir, f"{name}_{int(time.time())}.png")
            page.get_screenshot(path=path)
        except Exception:
            pass

    def _log(self, level: str, message: str) -> None:
        """记录日志"""
        if self.log_callback:
            try:
                self.log_callback(level, message)
            except Exception:
                pass

    def _cleanup_user_data(self, user_data_dir: Optional[str]) -> None:
        """清理浏览器用户数据目录"""
        if not user_data_dir:
            return
        try:
            import shutil
            if os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception:
            pass

    @staticmethod
    def _get_ua() -> str:
        """生成随机User-Agent（使用更新的浏览器版本）"""
        # 使用 2024-2025 年常见的 Chrome 版本
        v = random.choice(["121.0.6167.85", "122.0.6261.94", "123.0.6312.58", "124.0.6367.60", "125.0.6422.76"])
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"

    def _human_delay(self, min_ms: int = 50, max_ms: int = 150) -> None:
        """模拟真人的随机延迟"""
        delay = random.uniform(min_ms / 1000, max_ms / 1000)
        time.sleep(delay)

    def _human_type(self, element, text: str) -> None:
        """模拟真人打字（每个字符之间有随机延迟）"""
        for char in text:
            element.input(char)
            self._human_delay(30, 120)

    def _simulate_mouse_movement(self, page) -> None:
        """模拟随机鼠标移动（增加真实性）"""
        try:
            # 在页面上随机移动几次鼠标
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                page.run_cdp("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
                self._human_delay(100, 300)
        except Exception:
            pass

"""
ChatGPT.org.uk 邮件客户端
与 DuckMailClient 接口兼容，用于 gemini_register 方案
"""
import re
import time
from typing import Optional

import requests

from core.mail_utils import extract_verification_code


class ChatGptMailClient:
    """ChatGPT.org.uk 邮件客户端"""

    def __init__(
        self,
        base_url: str = "https://mail.chatgpt.org.uk",
        proxy: str = "",
        verify_ssl: bool = True,
        api_key: str = "gpt-test",
        log_callback=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.api_key = api_key.strip()
        self.log_callback = log_callback

        self.email: Optional[str] = None
        self.password: Optional[str] = None  # 此方案不需要密码，但保持接口兼容

    def set_credentials(self, email: str, password: str = "") -> None:
        """设置邮箱凭据（保持接口兼容）"""
        self.email = email
        self.password = password

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """发送请求"""
        headers = kwargs.pop("headers", None) or {}
        if self.api_key and "X-API-Key" not in headers:
            headers["X-API-Key"] = self.api_key
        kwargs["headers"] = headers
        self._log("info", f"[HTTP] {method} {url}")

        try:
            res = requests.request(
                method,
                url,
                proxies=self.proxies,
                verify=self.verify_ssl,
                timeout=kwargs.pop("timeout", 30),
                **kwargs,
            )
            self._log("info", f"[HTTP] Response: {res.status_code}")
            return res
        except Exception as e:
            self._log("error", f"[HTTP] Request failed: {e}")
            raise

    def register_account(self, domain: Optional[str] = None) -> bool:
        """注册新邮箱账号（生成临时邮箱）"""
        try:
            res = self._request(
                "GET",
                f"{self.base_url}/api/generate-email",
            )
            if res.status_code == 200:
                data = res.json() if res.content else {}
                if data.get("success"):
                    self.email = data.get("data", {}).get("email")
                    self.password = ""  # 此方案不需要密码
                    if self.email:
                        self._log("info", f"ChatGptMail register success: {self.email}")
                        return True
        except Exception as e:
            self._log("error", f"ChatGptMail register failed: {e}")
            return False

        self._log("error", "ChatGptMail register failed")
        return False

    def login(self) -> bool:
        """登录（此方案不需要登录，直接返回 True）"""
        return True

    def fetch_verification_code(self, since_time=None) -> Optional[str]:
        """获取验证码"""
        if not self.email:
            self._log("error", "No email address set")
            return None

        try:
            self._log("info", f"Fetching emails for: {self.email}")
            res = self._request(
                "GET",
                f"{self.base_url}/api/emails",
                params={"email": self.email},
            )

            if res.status_code != 200:
                return None

            data = res.json() if res.content else {}

            # 调试日志：记录 API 返回的原始结构
            self._log("info", f"API response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

            # API 响应格式: { "success": true, "data": { "emails": [...] } }
            # 或者: { "data": { "emails": [...] } }
            data_field = data.get("data", {})
            if isinstance(data_field, dict):
                emails = data_field.get("emails", [])
            else:
                # 兼容直接返回列表的情况
                emails = data_field if isinstance(data_field, list) else []

            if not emails:
                self._log("info", f"No emails found, raw response: {str(data)[:200]}")
                return None

            self._log("info", f"Found {len(emails)} email(s), parsing...")

            # 遍历邮件查找验证码
            for email_item in emails:
                if not isinstance(email_item, dict):
                    continue

                # 获取邮件内容 - 兼容多种字段名
                html_content = email_item.get("html_content") or email_item.get("html") or ""
                text_content = email_item.get("content") or email_item.get("body") or email_item.get("text") or ""
                subject = email_item.get("subject") or ""

                content = f"{subject} {text_content} {html_content}"

                # 使用 mail_utils 提取验证码
                code = extract_verification_code(content)
                if code:
                    self._log("info", f"Verification code found: {code}")
                    return code

                # 备用方案：直接用正则匹配 6 位数字
                code_match = re.search(r'\b(\d{6})\b', content)
                if code_match:
                    code = code_match.group(1)
                    self._log("info", f"Verification code found (regex): {code}")
                    return code

            return None

        except Exception as e:
            self._log("error", f"Fetch code failed: {e}")
            return None

    def poll_for_code(
        self,
        timeout: int = 120,
        interval: int = 4,
        since_time=None,
    ) -> Optional[str]:
        """轮询获取验证码"""
        max_retries = timeout // interval

        for i in range(1, max_retries + 1):
            self._log("info", f"Polling for verification code ({i}/{max_retries})...")
            code = self.fetch_verification_code(since_time=since_time)
            if code:
                return code

            if i < max_retries:
                time.sleep(interval)

        self._log("error", "Verification code timeout")
        return None

    def _log(self, level: str, message: str) -> None:
        if self.log_callback:
            try:
                self.log_callback(level, message)
            except Exception:
                pass

    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        return extract_verification_code(text)

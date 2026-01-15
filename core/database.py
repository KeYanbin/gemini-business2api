"""数据库模块 - SQLite 账户存储"""
import sqlite3
import json
import logging
import os
from typing import List, Dict, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 数据库路径 - 自动检测环境
if os.path.exists("/data"):
    DB_FILE = "/data/accounts.db"
    JSON_FILE = "/data/accounts.json"
else:
    DB_FILE = "data/accounts.db"
    JSON_FILE = "data/accounts.json"


def get_db_path() -> str:
    """获取数据库文件路径"""
    return DB_FILE


@contextmanager
def get_connection():
    """获取数据库连接（上下文管理器）"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """初始化数据库表结构"""
    os.makedirs(os.path.dirname(DB_FILE) if os.path.dirname(DB_FILE) else "data", exist_ok=True)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                secure_c_ses TEXT NOT NULL,
                host_c_oses TEXT,
                csesidx TEXT NOT NULL,
                config_id TEXT NOT NULL,
                expires_at TEXT,
                disabled INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info(f"[DB] 数据库初始化完成: {DB_FILE}")


def migrate_from_json():
    """从 JSON 文件迁移数据到数据库"""
    if not os.path.exists(JSON_FILE):
        logger.info("[DB] 未找到 JSON 文件，跳过迁移")
        return 0
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts")
        if cursor.fetchone()[0] > 0:
            logger.info("[DB] 数据库已有数据，跳过迁移")
            return 0
    
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            accounts_data = json.load(f)
        
        if not accounts_data:
            logger.info("[DB] JSON 文件为空，跳过迁移")
            return 0
        
        count = 0
        with get_connection() as conn:
            cursor = conn.cursor()
            for i, acc in enumerate(accounts_data, 1):
                account_id = acc.get("id", f"account_{i}")
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO accounts 
                        (id, secure_c_ses, host_c_oses, csesidx, config_id, expires_at, disabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        account_id,
                        acc.get("secure_c_ses"),
                        acc.get("host_c_oses"),
                        acc.get("csesidx"),
                        acc.get("config_id"),
                        acc.get("expires_at"),
                        1 if acc.get("disabled", False) else 0
                    ))
                    count += 1
                except Exception as e:
                    logger.error(f"[DB] 迁移账户 {account_id} 失败: {e}")
            conn.commit()
        
        # 备份原 JSON 文件
        backup_file = JSON_FILE + ".backup"
        os.rename(JSON_FILE, backup_file)
        logger.info(f"[DB] 成功迁移 {count} 个账户，原文件已备份为 {backup_file}")
        return count
    except Exception as e:
        logger.error(f"[DB] 迁移失败: {e}")
        return 0


def save_account(account: Dict) -> bool:
    """保存或更新单个账户"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO accounts 
                (id, secure_c_ses, host_c_oses, csesidx, config_id, expires_at, disabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                account.get("id"),
                account.get("secure_c_ses"),
                account.get("host_c_oses"),
                account.get("csesidx"),
                account.get("config_id"),
                account.get("expires_at"),
                1 if account.get("disabled", False) else 0
            ))
            conn.commit()
            logger.info(f"[DB] 账户 {account.get('id')} 已保存")
            return True
    except Exception as e:
        logger.error(f"[DB] 保存账户失败: {e}")
        return False


def save_accounts(accounts_data: List[Dict]):
    """保存所有账户（先清空再插入）"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM accounts")
            
            for i, acc in enumerate(accounts_data, 1):
                account_id = acc.get("id", f"account_{i}")
                cursor.execute('''
                    INSERT INTO accounts 
                    (id, secure_c_ses, host_c_oses, csesidx, config_id, expires_at, disabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    account_id,
                    acc.get("secure_c_ses"),
                    acc.get("host_c_oses"),
                    acc.get("csesidx"),
                    acc.get("config_id"),
                    acc.get("expires_at"),
                    1 if acc.get("disabled", False) else 0
                ))
            conn.commit()
            logger.info(f"[DB] 已保存 {len(accounts_data)} 个账户")
    except Exception as e:
        logger.error(f"[DB] 批量保存失败: {e}")
        raise


def load_accounts() -> List[Dict]:
    """从数据库加载所有账户"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts ORDER BY created_at")
            rows = cursor.fetchall()
            
            accounts = []
            for row in rows:
                accounts.append({
                    "id": row["id"],
                    "secure_c_ses": row["secure_c_ses"],
                    "host_c_oses": row["host_c_oses"],
                    "csesidx": row["csesidx"],
                    "config_id": row["config_id"],
                    "expires_at": row["expires_at"],
                    "disabled": bool(row["disabled"])
                })
            
            if accounts:
                logger.info(f"[DB] 从数据库加载 {len(accounts)} 个账户")
            return accounts
    except Exception as e:
        logger.error(f"[DB] 加载账户失败: {e}")
        return []


def delete_account_by_id(account_id: str) -> bool:
    """删除单个账户"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"[DB] 账户 {account_id} 已删除")
                return True
            else:
                logger.warning(f"[DB] 账户 {account_id} 不存在")
                return False
    except Exception as e:
        logger.error(f"[DB] 删除账户失败: {e}")
        return False


def update_account_status(account_id: str, disabled: bool) -> bool:
    """更新账户禁用状态"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE accounts SET disabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if disabled else 0, account_id)
            )
            conn.commit()
            if cursor.rowcount > 0:
                status = "禁用" if disabled else "启用"
                logger.info(f"[DB] 账户 {account_id} 已{status}")
                return True
            else:
                logger.warning(f"[DB] 账户 {account_id} 不存在")
                return False
    except Exception as e:
        logger.error(f"[DB] 更新状态失败: {e}")
        return False


def get_account_count() -> int:
    """获取账户总数"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM accounts")
            return cursor.fetchone()[0]
    except:
        return 0


def upsert_accounts(accounts_data: List[Dict]) -> Dict[str, int]:
    """批量插入或更新账户（不删除现有账户）
    
    Returns:
        {"added": int, "updated": int} 统计信息
    """
    added = 0
    updated = 0
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            for i, acc in enumerate(accounts_data, 1):
                account_id = acc.get("id", f"account_{i}")
                
                # 检查账户是否已存在
                cursor.execute("SELECT id FROM accounts WHERE id = ?", (account_id,))
                exists = cursor.fetchone() is not None
                
                cursor.execute('''
                    INSERT OR REPLACE INTO accounts 
                    (id, secure_c_ses, host_c_oses, csesidx, config_id, expires_at, disabled, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    account_id,
                    acc.get("secure_c_ses"),
                    acc.get("host_c_oses"),
                    acc.get("csesidx"),
                    acc.get("config_id"),
                    acc.get("expires_at"),
                    1 if acc.get("disabled", False) else 0
                ))
                
                if exists:
                    updated += 1
                else:
                    added += 1
            
            conn.commit()
            logger.info(f"[DB] 批量上传完成: 新增 {added}, 更新 {updated}")
            return {"added": added, "updated": updated}
    except Exception as e:
        logger.error(f"[DB] 批量上传失败: {e}")
        raise

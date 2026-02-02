#!/usr/bin/env python3
import aiohttp
from aiohttp import web
import json
import time
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CloudAccountManager:
    def __init__(self):
        self.accounts = self.load_accounts()
        self.blocked_accounts = {}  # account_key -> unblock_timestamp
        self.current_account_index = 0

    def load_accounts(self) -> List[Dict]:
        """Загрузка аккаунтов Ollama Cloud из файла"""
        try:
            with open('/app/config/cloud_accounts.json', 'r') as f:
                data = json.load(f)
                return data.get('accounts', [])
        except Exception as e:
            logger.error(f"Error loading accounts: {e}")
            return []

    def get_next_available_account(self) -> Optional[Dict]:
        """Получить следующий доступный аккаунт с ротацией"""
        if not self.accounts:
            return None

        # Сначала проверяем есть ли незаблокированные аккаунты
        available_accounts = []
        for account in self.accounts:
            account_key = account['api_key']
            if account_key in self.blocked_accounts:
                # Проверяем не истекла ли блокировка (неделя)
                if time.time() < self.blocked_accounts[account_key]:
                    continue  # Аккаунт еще заблокирован
                else:
                    # Блокировка истекла, удаляем из blocked
                    del self.blocked_accounts[account_key]
            available_accounts.append(account)

        if not available_accounts:
            logger.error("All Ollama Cloud accounts are blocked")
            return None

        # Round-robin выбор аккаунта
        if self.current_account_index >= len(available_accounts):
            self.current_account_index = 0

        account = available_accounts[self.current_account_index]
        self.current_account_index = (self.current_account_index + 1) % len(available_accounts)

        return account

    def block_account(self, account_key: str, duration_days: int = 7):
        """Блокировать аккаунт на указанное количество дней"""
        block_until = time.time() + (duration_days * 24 * 3600)
        self.blocked_accounts[account_key] = block_until
        logger.warning(f"Account blocked until {datetime.fromtimestamp(block_until)}")

    def get_account_status(self) -> Dict:
        """Получить статус всех аккаунтов"""
        status = {}
        for account in self.accounts:
            key = account['api_key']
            is_blocked = key in self.blocked_accounts
            status[account['name']] = {
                'blocked': is_blocked,
                'blocked_until': datetime.fromtimestamp(self.blocked_accounts[key]).isoformat() if is_blocked else None,
                'current_requests': 0
            }
        return status

class OllamaCloudGateway:
    def __init__(self):
        self.account_manager = CloudAccountManager()
        self.base_url = "https://api.ollama.com"
        self.session = None

    async def get_session(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def handle_request(self, request):
        """Обработка входящего запроса"""
        path = request.match_info.get('path', '')
        method = request.method

        # Получаем тело запроса
        try:
            body = await request.json() if method in ['POST', 'PUT'] else None
        except:
            body = await request.text() if method in ['POST', 'PUT'] else None

        # Получаем аккаунт для запроса
        account = self.account_manager.get_next_available_account()
        if not account:
            return web.json_response(
                {"error": "All Ollama Cloud accounts are currently blocked (429 errors). Try again later."},
                status=429
            )

        logger.info(f"Using account: {account['name']}")

        try:
            result = await self.make_cloud_request(
                method, f"{self.base_url}/{path}", body, account['api_key']
            )
            return result

        except aiohttp.ClientError as e:
            if hasattr(e, 'status') and e.status == 429:
                # Блокируем аккаунт на неделю при ошибке 429
                self.account_manager.block_account(account['api_key'])
                logger.error(f"Account {account['name']} blocked due to 429 error")

                # Пробуем следующий аккаунт
                next_account = self.account_manager.get_next_available_account()
                if next_account:
                    logger.info(f"Retrying with account: {next_account['name']}")
                    try:
                        result = await self.make_cloud_request(
                            method, f"{self.base_url}/{path}", body, next_account['api_key']
                        )
                        return result
                    except aiohttp.ClientError as retry_e:
                        return web.json_response(
                            {"error": f"Retry failed: {str(retry_e)}"},
                            status=retry_e.status if hasattr(retry_e, 'status') else 500
                        )

                return web.json_response(
                    {"error": "All accounts exhausted after 429 error"},
                    status=429
                )
            else:
                return web.json_response(
                    {"error": f"Ollama Cloud error: {str(e)}"},
                    status=e.status if hasattr(e, 'status') else 500
                )

    async def make_cloud_request(self, method, url, body, api_key):
        """Выполнить запрос к Ollama Cloud"""
        session = await self.get_session()

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        async with session.request(
                method, url,
                json=body if isinstance(body, dict) else None,
                data=json.dumps(body) if not isinstance(body, dict) else None,
                headers=headers
        ) as response:

            if response.status == 429:
                raise aiohttp.ClientError("Rate limit exceeded", status=429)

            response_data = await response.json()

            return web.json_response(
                response_data,
                status=response.status
            )

# Создаем приложение
gateway = OllamaCloudGateway()
app = web.Application()

# Маршруты
app.router.add_route('*', '/api/{path:.*}', gateway.handle_request)
app.router.add_route('*', '/{path:.*}', gateway.handle_request)

# Admin endpoints
@app.get('/admin/status')
async def get_status(request):
    return web.json_response(gateway.account_manager.get_account_status())

@app.post('/admin/unblock/{account_name}')
async def unblock_account(request):
    account_name = request.match_info.get('account_name')
    for account in gateway.account_manager.accounts:
        if account['name'] == account_name:
            if account['api_key'] in gateway.account_manager.blocked_accounts:
                del gateway.account_manager.blocked_accounts[account['api_key']]
                return web.json_response({"message": f"Account {account_name} unblocked"})
    return web.json_response({"error": "Account not found"}, status=404)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=11435)
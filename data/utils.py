# utils.py - ИСПРАВЛЕННЫЙ
import asyncio
import functools
import logging
import time
from typing import Any, Callable, TypeVar, Coroutine, Optional, Dict, List
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
T = TypeVar('T')


def run_in_executor(func: Callable[..., T]) -> Callable[..., Coroutine[Any, Any, T]]:
    """
    Декоратор для запуска синхронной функции в отдельном потоке.
    Используется для блокирующих операций (файлы, процессы, тяжёлые вычисления).
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    return wrapper


class AsyncSemaphore:
    """
    Асинхронный семафор с логированием для управления параллельными запросами.
    """
    
    def __init__(self, limit: int = 10, name: str = "semaphore", timeout: Optional[float] = None):
        self._semaphore = asyncio.Semaphore(limit)
        self._name = name
        self._active = 0
        self._total_waits = 0
        self._timeout = timeout
    
    async def acquire(self):
        start = time.time()
        self._total_waits += 1
        try:
            if self._timeout:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=self._timeout)
            else:
                await self._semaphore.acquire()
            self._active += 1
            wait_time = time.time() - start
            if wait_time > 1.0:
                logger.debug(f"[{self._name}] Ожидание: {wait_time:.2f}с, активных: {self._active}")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[{self._name}] Таймаут получения семафора")
            return False
    
    def release(self):
        self._active -= 1
        self._semaphore.release()
    
    async def __aenter__(self):
        """Асинхронный вход в контекстный менеджер."""
        acquired = await self.acquire()
        if not acquired:
            raise RuntimeError(f"Не удалось получить семафор {self._name}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный выход из контекстного менеджера."""
        self.release()
    
    def get_stats(self) -> Dict:
        return {
            "name": self._name,
            "active": self._active,
            "total_waits": self._total_waits,
            "limit": self._semaphore._value
        }


# Глобальные семафоры
rag_semaphore = AsyncSemaphore(5, "rag", timeout=30.0)
api_semaphore = AsyncSemaphore(10, "api", timeout=60.0)
fs_semaphore = AsyncSemaphore(3, "filesystem", timeout=30.0)
db_semaphore = AsyncSemaphore(5, "database", timeout=10.0)
voice_semaphore = AsyncSemaphore(2, "voice", timeout=30.0)


class AsyncRateLimiter:
    """Простой rate limiter для API запросов."""
    
    def __init__(self, calls_per_second: float = 1.0):
        self.calls_per_second = calls_per_second
        self._last_call = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        async with self._lock:
            now = time.time()
            wait_time = (1.0 / self.calls_per_second) - (now - self._last_call)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_call = time.time()


# Глобальный rate limiter для API
api_rate_limiter = AsyncRateLimiter(calls_per_second=0.5)  # 1 запрос в 2 секунды


class AsyncTaskPool:
    """Пул для управления фоновыми задачами."""
    
    def __init__(self, max_tasks: int = 100):
        self._tasks: List[asyncio.Task] = []
        self._max_tasks = max_tasks
        self._lock = asyncio.Lock()
    
    async def add(self, coro):
        """Добавляет задачу в пул."""
        async with self._lock:
            # Очищаем завершённые задачи
            self._tasks = [t for t in self._tasks if not t.done()]
            
            if len(self._tasks) >= self._max_tasks:
                # Ждём завершения самой старой задачи
                oldest = self._tasks[0]
                await oldest
                self._tasks.pop(0)
            
            task = asyncio.create_task(coro)
            self._tasks.append(task)
            return task
    
    async def wait_all(self):
        """Ожидает завершения всех задач."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
    
    def cancel_all(self):
        """Отменяет все задачи."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


# Глобальный пул задач
task_pool = AsyncTaskPool()


def safe_cancel(task: asyncio.Task):
    """Безопасная отмена задачи."""
    if task and not task.done():
        task.cancel()
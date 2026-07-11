"""
Abstract Exchange Interface
Both LiveExchange (real XT.com trading) and PaperExchange (simulated trading)
implement this same interface, so the rest of the bot doesn't care which mode is active.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, List


class ExchangeInterface(ABC):
    """Common interface for live and paper trading engines"""

    @abstractmethod
    async def connect(self) -> bool:
        ...

    @abstractmethod
    async def disconnect(self):
        ...

    @abstractmethod
    async def get_balance(self) -> Dict:
        """Returns: {'USDT': free, 'total': total, 'used': used}"""
        ...

    @abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List:
        ...

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Dict:
        ...

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        ...

    @abstractmethod
    async def place_order(
        self, symbol: str, side: str, amount: float,
        order_type: str = "market", price: Optional[float] = None,
        stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
        leverage: int = 10,
    ) -> Optional[Dict]:
        ...

    @abstractmethod
    async def get_open_positions(self) -> List[Dict]:
        ...

    @abstractmethod
    async def close_position(self, symbol: str, side: str, amount: float) -> Optional[Dict]:
        ...

    @abstractmethod
    async def get_symbols(self, quote: str = "USDT") -> List[str]:
        ...

    @abstractmethod
    async def get_symbols_by_volume(self, quote: str = "USDT", top_n: int = 8) -> List[str]:
        ...

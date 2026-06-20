"""English, ergonomic MCP server for the SiYuan note kernel."""

from .client import SiyuanClient, SiyuanError
from .service import SiyuanService

__all__ = ["SiyuanClient", "SiyuanError", "SiyuanService"]
__version__ = "0.1.0"

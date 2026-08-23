import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    BITGET_API_KEY: str = os.getenv("BITGET_API_KEY", "")
    BITGET_SECRET: str = os.getenv("BITGET_SECRET", "")
    BITGET_PASSPHRASE: str = os.getenv("BITGET_PASSPHRASE", "")
    
    USE_TESTNET: bool = os.getenv("USE_TESTNET", "false").lower() in ("true", "1", "yes")
    WEBHOOK_PASSPHRASE: str = os.getenv("WEBHOOK_PASSPHRASE", "my_super_secret_passphrase_123")
    
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    @classmethod
    def validate_keys(cls) -> bool:
        """Check if API keys are configured."""
        return bool(cls.BITGET_API_KEY and cls.BITGET_SECRET and cls.BITGET_PASSPHRASE)

config = Config()

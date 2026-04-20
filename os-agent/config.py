import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://ruoli.dev")

    SSH_HOST = os.getenv("SSH_HOST", "localhost")
    SSH_PORT = int(os.getenv("SSH_PORT", 22))
    SSH_USER = os.getenv("SSH_USER", "root")
    SSH_PASSWORD = os.getenv("SSH_PASSWORD")
    SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")


    AGENT_MODE = os.getenv("AGENT_MODE", "local")  # local or remote

    REQUIRE_CONFIRM = os.getenv("REQUIRE_CONFIRM_FOR_HIGH_RISK", "true").lower() == "true"

    # Claude 模型配置
    MODEL_NAME = "claude-opus-4-6"
    MAX_TOKENS = 2048
    TEMPERATURE = 0


config = Config()

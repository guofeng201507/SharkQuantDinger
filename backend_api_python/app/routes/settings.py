"""
Settings API — read and write .env configuration.

Admin-only endpoints for system configuration management.
"""
import os
import re
from flask import jsonify, request
from app.openapi.blueprint import HumanBlueprint as Blueprint
from app._version import APP_VERSION
from app.markets.registry import market_options
from app.utils.logger import get_logger
from app.utils.config_loader import clear_config_cache
from app.utils.auth import login_required, admin_required
from app.services.settings.branding import build_brand_config
from app.services.settings.env_file import read_env_file, write_env_file
from app.utils.redaction import redact_secrets
from app.services.settings.runtime import reload_runtime_env, refresh_runtime_services

logger = get_logger(__name__)

settings_blp = Blueprint('settings', __name__)

# These values are process-group security roots. They may be persisted through
# the settings UI, but applying them to only one Gunicorn worker would make
# authentication or credential decryption inconsistent until every worker has
# restarted.
STRATEGY_RUNTIME_SETTINGS = {
    'STRATEGY_MAX_ACTIVE',
    'STRATEGY_EVALUATOR_THREADS',
    'SHARED_PUBLIC_MARKET_FEED_ENABLED',
    'SHARED_PUBLIC_MARKET_FALLBACK_TTL_SEC',
    'BAR_CLOSE_EVENT_SCHEDULER_ENABLED',
    'BAR_CLOSE_EVENT_GRACE_SEC',
    'BAR_EVENT_FALLBACK_WAKE_SEC',
    'KAFKA_EVENT_PUBLISH_ENABLED',
    'STRATEGY_SHARD_COUNT',
    'STRATEGY_EVALUATION_BATCH_SIZE',
    'STRATEGY_EVALUATOR_MODE',
    'STRATEGY_DISTRIBUTED_BAR_ENABLED',
    'STRATEGY_EVALUATOR_LEASE_SEC',
    'STRATEGY_EVALUATOR_MAX_ATTEMPTS',
    'STRATEGY_EVALUATOR_BATCH_WORKERS',
    'STRATEGY_EVALUATION_TIMEOUT_SEC',
    'KAFKA_MAX_POLL_INTERVAL_MS',
    'BAR_IDLE_SCHEDULER_ENABLED',
    'BAR_IDLE_WAKE_INTERVAL_SEC',
}

RESTART_REQUIRED_SETTINGS = {
    'SECRET_KEY',
    'CREDENTIAL_ENCRYPTION_KEY',
} | STRATEGY_RUNTIME_SETTINGS

# ---------------------------------------------------------------
# ---------------------------------------------------------------

# Keys that should land in the "Advanced" tab of the Settings page.  Anything
# not listed here defaults to the "Basic" tab.  Keep this list small and
# intentional — only put truly rarely changed knobs here so the basic tab stays
# useful for day-to-day operators.
ADVANCED_KEYS = {
    # Bootstrap compatibility
    'ADMIN_USER', 'ADMIN_PASSWORD',
    # AI tuning
    'OPENROUTER_TEMPERATURE',
    'LLM_MAX_TOKENS',
    'AI_ANALYSIS_CONSENSUS_TIMEFRAMES', 'SEARCH_MAX_RESULTS',
    'FAST_ANALYSIS_INCLUDE_GLOBAL_NEWS',
    'SEARCH_GOOGLE_API_KEY', 'SEARCH_GOOGLE_CX', 'SEARCH_BING_API_KEY', 'SERPAPI_KEYS',
    'SEARCH_SEARXNG_ENGINES', 'SEARCH_SEARXNG_CATEGORIES', 'SEARCH_SEARXNG_LANGUAGE', 'SEARCH_SEARXNG_TIMEOUT',
    'GDELT_BASE_URL', 'GDELT_TIMEOUT', 'GDELT_MAX_RESULTS',
    'ALPHA_VANTAGE_API_KEY', 'ALPHA_VANTAGE_BASE_URL', 'ALPHA_VANTAGE_TIMEOUT', 'ALPHA_VANTAGE_NEWS_LIMIT',
    'AI_CODE_GEN_MODEL', 'LLM_PROXY_URL', 'LLM_USE_SYSTEM_PROXY',
    'JEV_BASE_URL', 'JEV_MODEL', 'JEV_TIMEOUT_SECONDS', 'JEV_MIN_CONFIDENCE', 'AI_DECISION_TIMEOUT_SECONDS',
    'EVENT_RADAR_JEV_MIN_CONFIDENCE', 'EVENT_RADAR_NEWS_LOOKBACK_DAYS', 'EVENT_RADAR_MAX_EVENTS',
    'SEC_EDGAR_USER_AGENT',
    'OPENAI_BASE_URL', 'DEEPSEEK_BASE_URL', 'GROK_BASE_URL', 'ATLASCLOUD_BASE_URL', 'MINIMAX_BASE_URL',
    # Trading internals
    'ORDER_MODE', 'MAKER_WAIT_SEC',
    'SPOT_CLOSE_SAFETY_RATIO', 'SPOT_OPEN_QUOTE_BUFFER',
    'FINNHUB_API_KEY', 'FINNHUB_FREE_ONLY',
    'TRADING_ECONOMICS_CLIENT', 'TRADING_ECONOMICS_KEY',
    'COINGLASS_API_KEY', 'CRYPTOQUANT_API_KEY', 'TIINGO_API_KEY',
    'TWELVE_DATA_API_KEY', 'ADANOS_API_KEY', 'TWITTERAPI_IO_KEY',
    # Agent gateway (operator-level)
    'AGENT_JOBS_MAX_WORKERS',
    'ENABLE_PENDING_ORDER_WORKER', 'DISABLE_RESTORE_RUNNING_STRATEGIES',
    # Distributed strategy runtime tuning
    'SHARED_PUBLIC_MARKET_FALLBACK_TTL_SEC',
    'BAR_CLOSE_EVENT_GRACE_SEC', 'BAR_EVENT_FALLBACK_WAKE_SEC',
    'STRATEGY_SHARD_COUNT', 'STRATEGY_EVALUATION_BATCH_SIZE',
    'STRATEGY_EVALUATOR_LEASE_SEC', 'STRATEGY_EVALUATOR_MAX_ATTEMPTS',
    'STRATEGY_EVALUATOR_BATCH_WORKERS', 'STRATEGY_EVALUATION_TIMEOUT_SEC',
    'KAFKA_MAX_POLL_INTERVAL_MS', 'BAR_IDLE_WAKE_INTERVAL_SEC',
    # OAuth advanced
    'OAUTH_ALLOWED_REDIRECTS', 'OAUTH_STATE_TTL_MINUTES',
    'GOOGLE_REDIRECT_URI', 'GITHUB_REDIRECT_URI',
    # Security rate-limit / verification code tuning
    'SECURITY_IP_MAX_ATTEMPTS', 'SECURITY_IP_WINDOW_MINUTES', 'SECURITY_IP_BLOCK_MINUTES',
    'SECURITY_ACCOUNT_MAX_ATTEMPTS', 'SECURITY_ACCOUNT_WINDOW_MINUTES', 'SECURITY_ACCOUNT_BLOCK_MINUTES',
    'VERIFICATION_CODE_EXPIRE_MINUTES', 'VERIFICATION_CODE_RATE_LIMIT',
    'VERIFICATION_CODE_IP_HOURLY_LIMIT', 'VERIFICATION_CODE_MAX_ATTEMPTS',
    'VERIFICATION_CODE_LOCK_MINUTES',
    'MFA_CHALLENGE_EXPIRE_MINUTES', 'MFA_MAX_ATTEMPTS',
    # AI reflection / calibration
    'REFLECTION_WORKER_INTERVAL_SEC', 'REFLECTION_MIN_AGE_DAYS', 'REFLECTION_VALIDATE_LIMIT',
    'AI_CALIBRATION_MARKETS', 'AI_CALIBRATION_LOOKBACK_DAYS', 'AI_CALIBRATION_MIN_SAMPLES',
    # Stablecoin pay internals
    'USDT_TRC20_CONTRACT', 'USDT_BEP20_CONTRACT', 'USDT_ERC20_CONTRACT', 'USDT_SOL_MINT',
    'USDC_ERC20_CONTRACT', 'USDC_SOL_MINT',
    'TRONGRID_BASE_URL', 'ETHERSCAN_V2_BASE_URL', 'BSC_RPC_URLS', 'ETH_RPC_URLS',
    'SOLANA_RPC_URL', 'BEP20_PREFER_EXPLORER', 'ERC20_PREFER_EXPLORER',
    'USDT_PAY_CONFIRM_SECONDS', 'USDT_PAY_EXPIRE_MINUTES',
    'USDT_AMOUNT_SUFFIX_DECIMALS', 'USDT_WORKER_POLL_INTERVAL',
    # Adanos sentiment
    'ADANOS_SENTIMENT_SOURCE', 'ADANOS_API_BASE_URL', 'TWITTERAPI_IO_BASE_URL',
    # Provider internals / rarely changed endpoints
    'TRADING_ECONOMICS_BASE_URL', 'TRADING_ECONOMICS_TIMEOUT',
    'FRED_BASE_URL', 'FRED_TIMEOUT', 'BLS_BASE_URL', 'BLS_TIMEOUT', 'BEA_BASE_URL', 'BEA_TIMEOUT',
    # Brand internals
    'BRAND_FAVICON_URL',
    'BRAND_LEGAL_USER_AGREEMENT_TEXT', 'BRAND_LEGAL_PRIVACY_POLICY_TEXT',
}

CONFIG_SCHEMA = {

    # Frontend reads these via /api/settings/brand-config (no auth) so logos,
    # social links, version label and legal modals can be rebranded without
    # touching the Vue source.
    'brand': {
        'title': 'Brand & Identity',
        'icon': 'crown',
        'order': 0,
        'items': [
            {
                'key': 'BRAND_APP_NAME',
                'label': 'settings.field.BRAND_APP_NAME',
                'type': 'text',
                'default': 'SharkQuant',
                'description': 'settings.desc.BRAND_APP_NAME'
            },
            {
                'key': 'BRAND_COPYRIGHT',
                'label': 'settings.field.BRAND_COPYRIGHT',
                'type': 'text',
                'default': '© 2025-2026 SharkQuant. All rights reserved.',
                'description': 'settings.desc.BRAND_COPYRIGHT'
            },
            {
                'key': 'BRAND_LOGO_LIGHT_URL',
                'label': 'settings.field.BRAND_LOGO_LIGHT_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LOGO_LIGHT_URL'
            },
            {
                'key': 'BRAND_LOGO_DARK_URL',
                'label': 'settings.field.BRAND_LOGO_DARK_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LOGO_DARK_URL'
            },
            {
                'key': 'BRAND_LOGO_COLLAPSED_URL',
                'label': 'settings.field.BRAND_LOGO_COLLAPSED_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LOGO_COLLAPSED_URL'
            },
            {
                'key': 'BRAND_FAVICON_URL',
                'label': 'settings.field.BRAND_FAVICON_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_FAVICON_URL'
            },
        ]
    },

    'contact': {
        'title': 'Contact & Support',
        'icon': 'customer-service',
        'order': 0,
        'items': [
            {
                'key': 'BRAND_CONTACT_EMAIL',
                'label': 'settings.field.BRAND_CONTACT_EMAIL',
                'type': 'text',
                'default': 'support@sharkv2.com',
                'description': 'settings.desc.BRAND_CONTACT_EMAIL'
            },
            {
                'key': 'BRAND_CONTACT_SUPPORT_URL',
                'label': 'settings.field.BRAND_CONTACT_SUPPORT_URL',
                'type': 'text',
                'default': 'https://t.me/sharkquant_support',
                'description': 'settings.desc.BRAND_CONTACT_SUPPORT_URL'
            },
            {
                'key': 'BRAND_CONTACT_LIVE_CHAT_URL',
                'label': 'settings.field.BRAND_CONTACT_LIVE_CHAT_URL',
                'type': 'text',
                'default': 'https://t.me/sharkquant_support',
                'description': 'settings.desc.BRAND_CONTACT_LIVE_CHAT_URL'
            },
            {
                'key': 'BRAND_CONTACT_FEATURE_REQUEST_URL',
                'label': 'settings.field.BRAND_CONTACT_FEATURE_REQUEST_URL',
                'type': 'text',
                'default': '',
                'description': 'settings.desc.BRAND_CONTACT_FEATURE_REQUEST_URL'
            },
        ]
    },

    'social': {
        'title': 'Social Accounts',
        'icon': 'team',
        'order': 0,
        'items': [
            {
                'key': 'BRAND_SOCIAL_GITHUB',
                'label': 'settings.field.BRAND_SOCIAL_GITHUB',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_SOCIAL_GITHUB'
            },
            {
                'key': 'BRAND_SOCIAL_X',
                'label': 'settings.field.BRAND_SOCIAL_X',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_SOCIAL_X'
            },
            {
                'key': 'BRAND_SOCIAL_DISCORD',
                'label': 'settings.field.BRAND_SOCIAL_DISCORD',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_SOCIAL_DISCORD'
            },
            {
                'key': 'BRAND_SOCIAL_TELEGRAM',
                'label': 'settings.field.BRAND_SOCIAL_TELEGRAM',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_SOCIAL_TELEGRAM'
            },
            {
                'key': 'BRAND_SOCIAL_YOUTUBE',
                'label': 'settings.field.BRAND_SOCIAL_YOUTUBE',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_SOCIAL_YOUTUBE'
            },
        ]
    },

    'legal': {
        'title': 'Legal & Mobile App',
        'icon': 'safety-certificate',
        'order': 0,
        'items': [
            {
                'key': 'BRAND_LEGAL_USER_AGREEMENT_URL',
                'label': 'settings.field.BRAND_LEGAL_USER_AGREEMENT_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LEGAL_USER_AGREEMENT_URL'
            },
            {
                'key': 'BRAND_LEGAL_USER_AGREEMENT_TEXT',
                'label': 'settings.field.BRAND_LEGAL_USER_AGREEMENT_TEXT',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LEGAL_USER_AGREEMENT_TEXT'
            },
            {
                'key': 'BRAND_LEGAL_PRIVACY_POLICY_URL',
                'label': 'settings.field.BRAND_LEGAL_PRIVACY_POLICY_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LEGAL_PRIVACY_POLICY_URL'
            },
            {
                'key': 'BRAND_LEGAL_PRIVACY_POLICY_TEXT',
                'label': 'settings.field.BRAND_LEGAL_PRIVACY_POLICY_TEXT',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BRAND_LEGAL_PRIVACY_POLICY_TEXT'
            },
            {
                'key': 'MOBILE_APP_LATEST_VERSION',
                'label': 'settings.field.MOBILE_APP_LATEST_VERSION',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.MOBILE_APP_LATEST_VERSION'
            },
            {
                'key': 'MOBILE_APP_DOWNLOAD_URL',
                'label': 'settings.field.MOBILE_APP_DOWNLOAD_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.MOBILE_APP_DOWNLOAD_URL'
            },
        ]
    },

    'auth': {
        'title': 'Security & Authentication',
        'icon': 'lock',
        'order': 1,
        'items': [
            {
                'key': 'SECRET_KEY',
                'label': 'settings.field.SECRET_KEY',
                'type': 'password',
                'default': '',
                'description': 'settings.desc.SECRET_KEY'
            },
            {
                'key': 'ADMIN_USER',
                'label': 'settings.field.ADMIN_USER',
                'type': 'text',
                'default': 'quantdinger',
                'description': 'settings.desc.ADMIN_USER'
            },
            {
                'key': 'ADMIN_PASSWORD',
                'label': 'settings.field.ADMIN_PASSWORD',
                'type': 'password',
                'default': '123456',
                'description': 'settings.desc.ADMIN_PASSWORD'
            },
            {
                'key': 'ADMIN_EMAIL',
                'label': 'settings.field.ADMIN_EMAIL',
                'type': 'text',
                'default': 'admin@example.com',
                'description': 'settings.desc.ADMIN_EMAIL'
            },
        ]
    },

    'ai': {
        'title': 'AI / LLM',
        'icon': 'robot',
        'order': 2,
        'items': [
            {
                'key': 'JEV_API_KEY',
                'label': 'settings.field.JEV_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://console.typesafe.ai/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.JEV_API_KEY'
            },
            {
                'key': 'JEV_BASE_URL',
                'label': 'settings.field.JEV_BASE_URL',
                'type': 'text',
                'default': 'https://api.typesafe.ai/v1',
                'description': 'settings.desc.JEV_BASE_URL'
            },
            {
                'key': 'JEV_MODEL',
                'label': 'settings.field.JEV_MODEL',
                'type': 'text',
                'default': 'jev-latest',
                'description': 'settings.desc.JEV_MODEL'
            },
            {
                'key': 'JEV_TIMEOUT_SECONDS',
                'label': 'settings.field.JEV_TIMEOUT_SECONDS',
                'type': 'number',
                'default': 8,
                'description': 'settings.desc.JEV_TIMEOUT_SECONDS'
            },
            {
                'key': 'AI_DECISION_TIMEOUT_SECONDS',
                'label': 'settings.field.AI_DECISION_TIMEOUT_SECONDS',
                'type': 'number',
                'default': 10,
                'description': 'settings.desc.AI_DECISION_TIMEOUT_SECONDS'
            },
            {
                'key': 'JEV_MIN_CONFIDENCE',
                'label': 'settings.field.JEV_MIN_CONFIDENCE',
                'type': 'number',
                'default': 0.55,
                'description': 'settings.desc.JEV_MIN_CONFIDENCE'
            },
            {
                'key': 'EVENT_RADAR_ENABLED',
                'label': 'settings.field.EVENT_RADAR_ENABLED',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.EVENT_RADAR_ENABLED'
            },
            {
                'key': 'EVENT_RADAR_JEV_MIN_CONFIDENCE',
                'label': 'settings.field.EVENT_RADAR_JEV_MIN_CONFIDENCE',
                'type': 'number',
                'default': 0.30,
                'description': 'settings.desc.EVENT_RADAR_JEV_MIN_CONFIDENCE'
            },
            {
                'key': 'EVENT_RADAR_NEWS_LOOKBACK_DAYS',
                'label': 'settings.field.EVENT_RADAR_NEWS_LOOKBACK_DAYS',
                'type': 'number',
                'default': 2,
                'description': 'settings.desc.EVENT_RADAR_NEWS_LOOKBACK_DAYS'
            },
            {
                'key': 'EVENT_RADAR_MAX_EVENTS',
                'label': 'settings.field.EVENT_RADAR_MAX_EVENTS',
                'type': 'number',
                'default': 8,
                'description': 'settings.desc.EVENT_RADAR_MAX_EVENTS'
            },
            {
                'key': 'EVENT_RADAR_CRYPTO_RSS_ENABLED',
                'label': 'settings.field.EVENT_RADAR_CRYPTO_RSS_ENABLED',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.EVENT_RADAR_CRYPTO_RSS_ENABLED'
            },
            {
                'key': 'EVENT_RADAR_YAHOO_FINANCE_RSS_ENABLED',
                'label': 'settings.field.EVENT_RADAR_YAHOO_FINANCE_RSS_ENABLED',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.EVENT_RADAR_YAHOO_FINANCE_RSS_ENABLED'
            },
            {
                'key': 'EVENT_RADAR_SEC_EDGAR_ENABLED',
                'label': 'settings.field.EVENT_RADAR_SEC_EDGAR_ENABLED',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.EVENT_RADAR_SEC_EDGAR_ENABLED'
            },
            {
                'key': 'SEC_EDGAR_USER_AGENT',
                'label': 'settings.field.SEC_EDGAR_USER_AGENT',
                'type': 'text',
                'default': '',
                'required': False,
                'description': 'settings.desc.SEC_EDGAR_USER_AGENT'
            },
            {
                'key': 'LLM_PROVIDER',
                'label': 'settings.field.LLM_PROVIDER',
                'type': 'select',
                'default': 'openrouter',
                'options': [
                    {'value': 'openrouter', 'label': 'settings.option.LLM_PROVIDER.openrouter'},
                    {'value': 'openai', 'label': 'settings.option.LLM_PROVIDER.openai'},
                    {'value': 'google', 'label': 'settings.option.LLM_PROVIDER.google'},
                    {'value': 'deepseek', 'label': 'settings.option.LLM_PROVIDER.deepseek'},
                    {'value': 'grok', 'label': 'settings.option.LLM_PROVIDER.grok'},
                    {'value': 'atlascloud', 'label': 'settings.option.LLM_PROVIDER.atlascloud'},
                    {'value': 'custom', 'label': 'settings.option.LLM_PROVIDER.custom'},
                    {'value': 'minimax', 'label': 'settings.option.LLM_PROVIDER.minimax'},
                    {'value': 'litellm', 'label': 'settings.option.LLM_PROVIDER.litellm'},
                ],
                'description': 'settings.desc.LLM_PROVIDER'
            },
            {
                'key': 'AI_CODE_GEN_MODEL',
                'label': 'settings.field.AI_CODE_GEN_MODEL',
                'type': 'text',
                'default': '',
                'required': False,
                'description': 'settings.desc.AI_CODE_GEN_MODEL'
            },
            # OpenRouter
            {
                'key': 'OPENROUTER_API_KEY',
                'label': 'settings.field.OPENROUTER_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://openrouter.ai/keys',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.OPENROUTER_API_KEY',
                'group': 'openrouter'
            },
            {
                'key': 'OPENROUTER_MODEL',
                'label': 'settings.field.OPENROUTER_MODEL',
                'type': 'text',
                'default': 'openai/gpt-5.4',
                'link': 'https://openrouter.ai/models',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.OPENROUTER_MODEL',
                'group': 'openrouter'
            },
            {
                'key': 'OPENROUTER_FALLBACK_MODEL',
                'label': 'settings.field.OPENROUTER_FALLBACK_MODEL',
                'type': 'text',
                'default': '',
                'required': False,
                'link': 'https://openrouter.ai/models',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.OPENROUTER_FALLBACK_MODEL',
                'group': 'openrouter'
            },
            # OpenAI Direct
            {
                'key': 'OPENAI_API_KEY',
                'label': 'settings.field.OPENAI_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://platform.openai.com/api-keys',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.OPENAI_API_KEY',
                'group': 'openai'
            },
            {
                'key': 'OPENAI_MODEL',
                'label': 'settings.field.OPENAI_MODEL',
                'type': 'text',
                'default': 'gpt-5.4',
                'link': 'https://platform.openai.com/docs/models',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.OPENAI_MODEL',
                'group': 'openai'
            },
            {
                'key': 'OPENAI_BASE_URL',
                'label': 'settings.field.OPENAI_BASE_URL',
                'type': 'text',
                'default': 'https://api.openai.com/v1',
                'description': 'settings.desc.OPENAI_BASE_URL',
                'group': 'openai'
            },
            # Google Gemini
            {
                'key': 'GOOGLE_API_KEY',
                'label': 'settings.field.GOOGLE_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://aistudio.google.com/apikey',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.GOOGLE_API_KEY',
                'group': 'google'
            },
            {
                'key': 'GOOGLE_MODEL',
                'label': 'settings.field.GOOGLE_MODEL',
                'type': 'text',
                'default': 'gemini-1.5-flash',
                'link': 'https://ai.google.dev/gemini-api/docs/models',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.GOOGLE_MODEL',
                'group': 'google'
            },
            # DeepSeek
            {
                'key': 'DEEPSEEK_API_KEY',
                'label': 'settings.field.DEEPSEEK_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://platform.deepseek.com/api_keys',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.DEEPSEEK_API_KEY',
                'group': 'deepseek'
            },
            {
                'key': 'DEEPSEEK_MODEL',
                'label': 'settings.field.DEEPSEEK_MODEL',
                'type': 'text',
                'default': 'deepseek-chat',
                'link': 'https://api-docs.deepseek.com/quick_start/pricing',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.DEEPSEEK_MODEL',
                'group': 'deepseek'
            },
            {
                'key': 'DEEPSEEK_BASE_URL',
                'label': 'settings.field.DEEPSEEK_BASE_URL',
                'type': 'text',
                'default': 'https://api.deepseek.com/v1',
                'description': 'settings.desc.DEEPSEEK_BASE_URL',
                'group': 'deepseek'
            },
            # xAI Grok
            {
                'key': 'GROK_API_KEY',
                'label': 'settings.field.GROK_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://console.x.ai/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.GROK_API_KEY',
                'group': 'grok'
            },
            {
                'key': 'GROK_MODEL',
                'label': 'settings.field.GROK_MODEL',
                'type': 'text',
                'default': 'grok-beta',
                'link': 'https://docs.x.ai/docs/models',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.GROK_MODEL',
                'group': 'grok'
            },
            {
                'key': 'GROK_BASE_URL',
                'label': 'settings.field.GROK_BASE_URL',
                'type': 'text',
                'default': 'https://api.x.ai/v1',
                'description': 'settings.desc.GROK_BASE_URL',
                'group': 'grok'
            },
            # AtlasCloud
            {
                'key': 'ATLASCLOUD_API_KEY',
                'label': 'settings.field.ATLASCLOUD_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://www.atlascloud.ai/docs/api-keys',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.ATLASCLOUD_API_KEY',
                'group': 'atlascloud'
            },
            {
                'key': 'ATLASCLOUD_MODEL',
                'label': 'settings.field.ATLASCLOUD_MODEL',
                'type': 'text',
                'default': 'openai/gpt-5.4',
                'link': 'https://www.atlascloud.ai/docs/models/llm',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.ATLASCLOUD_MODEL',
                'group': 'atlascloud'
            },
            {
                'key': 'ATLASCLOUD_BASE_URL',
                'label': 'settings.field.ATLASCLOUD_BASE_URL',
                'type': 'text',
                'default': 'https://api.atlascloud.ai/v1',
                'description': 'settings.desc.ATLASCLOUD_BASE_URL',
                'group': 'atlascloud'
            },
            # Custom API (OpenAI-compatible)
            {
                'key': 'CUSTOM_API_URL',
                'label': 'settings.field.CUSTOM_API_URL',
                'type': 'text',
                'default': '',
                'description': 'settings.desc.CUSTOM_API_URL',
                'group': 'custom'
            },
            {
                'key': 'CUSTOM_API_KEY',
                'label': 'settings.field.CUSTOM_API_KEY',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.CUSTOM_API_KEY',
                'group': 'custom'
            },
            {
                'key': 'CUSTOM_MODEL',
                'label': 'settings.field.CUSTOM_MODEL',
                'type': 'text',
                'default': '',
                'description': 'settings.desc.CUSTOM_MODEL',
                'group': 'custom'
            },
            # MiniMax
            {
                'key': 'MINIMAX_API_KEY',
                'label': 'settings.field.MINIMAX_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://platform.minimax.io',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.MINIMAX_API_KEY',
                'group': 'minimax'
            },
            {
                'key': 'MINIMAX_MODEL',
                'label': 'settings.field.MINIMAX_MODEL',
                'type': 'text',
                'default': 'MiniMax-M2.7',
                'link': 'https://platform.minimax.io/docs',
                'link_text': 'settings.link.viewModels',
                'description': 'settings.desc.MINIMAX_MODEL',
                'group': 'minimax'
            },
            {
                'key': 'MINIMAX_BASE_URL',
                'label': 'settings.field.MINIMAX_BASE_URL',
                'type': 'text',
                'default': 'https://api.minimax.io/v1',
                'description': 'settings.desc.MINIMAX_BASE_URL',
                'group': 'minimax'
            },
            # LiteLLM
            {
                'key': 'LITELLM_API_KEY',
                'label': 'settings.field.LITELLM_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://docs.litellm.ai/docs/providers',
                'link_text': 'settings.link.viewProviders',
                'description': 'settings.desc.LITELLM_API_KEY',
                'group': 'litellm'
            },
            {
                'key': 'LITELLM_MODEL',
                'label': 'settings.field.LITELLM_MODEL',
                'type': 'text',
                'default': 'openai/gpt-5.4',
                'link': 'https://docs.litellm.ai/docs/providers',
                'link_text': 'settings.link.viewProviders',
                'description': 'settings.desc.LITELLM_MODEL',
                'group': 'litellm'
            },
            {
                'key': 'LITELLM_BASE_URL',
                'label': 'settings.field.LITELLM_BASE_URL',
                'type': 'text',
                'default': '',
                'description': 'settings.desc.LITELLM_BASE_URL',
                'group': 'litellm'
            },
            # Common settings
            {
                'key': 'OPENROUTER_TEMPERATURE',
                'label': 'settings.field.OPENROUTER_TEMPERATURE',
                'type': 'number',
                'default': '0.7',
                'description': 'settings.desc.OPENROUTER_TEMPERATURE'
            },
            {
                'key': 'LLM_MAX_TOKENS',
                'label': 'settings.field.LLM_MAX_TOKENS',
                'type': 'number',
                'default': 16384,
                'description': 'settings.desc.LLM_MAX_TOKENS'
            },
            {
                'key': 'AI_ANALYSIS_CONSENSUS_TIMEFRAMES',
                'label': 'settings.field.AI_ANALYSIS_CONSENSUS_TIMEFRAMES',
                'type': 'text',
                'default': '1D,4H',
                'required': False,
                'description': 'settings.desc.AI_ANALYSIS_CONSENSUS_TIMEFRAMES'
            },
            {
                'key': 'LLM_PROXY_URL',
                'label': 'settings.field.LLM_PROXY_URL',
                'type': 'text',
                'default': '',
                'required': False,
                'description': 'settings.desc.LLM_PROXY_URL'
            },
            {
                'key': 'LLM_USE_SYSTEM_PROXY',
                'label': 'settings.field.LLM_USE_SYSTEM_PROXY',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.LLM_USE_SYSTEM_PROXY'
            },
        ]
    },

    'trading': {
        'title': 'Live Trading',
        'icon': 'stock',
        'order': 3,
        'items': [
            {
                'key': 'ORDER_MODE',
                'label': 'settings.field.ORDER_MODE',
                'type': 'select',
                'options': [
                    {'value': 'market', 'label': 'settings.option.ORDER_MODE.market'},
                    {'value': 'maker', 'label': 'settings.option.ORDER_MODE.maker'},
                ],
                'default': 'market',
                'description': 'settings.desc.ORDER_MODE'
            },
            {
                'key': 'MAKER_WAIT_SEC',
                'label': 'settings.field.MAKER_WAIT_SEC',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.MAKER_WAIT_SEC'
            },
            {
                'key': 'SPOT_CLOSE_SAFETY_RATIO',
                'label': 'settings.field.SPOT_CLOSE_SAFETY_RATIO',
                'type': 'number',
                'default': '1.0',
                'description': 'settings.desc.SPOT_CLOSE_SAFETY_RATIO'
            },
            {
                'key': 'SPOT_OPEN_QUOTE_BUFFER',
                'label': 'settings.field.SPOT_OPEN_QUOTE_BUFFER',
                'type': 'number',
                'default': '0.995',
                'description': 'settings.desc.SPOT_OPEN_QUOTE_BUFFER'
            },
            {
                'key': 'ALLOW_LOCAL_DESKTOP_BROKERS',
                'label': 'settings.field.ALLOW_LOCAL_DESKTOP_BROKERS',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.ALLOW_LOCAL_DESKTOP_BROKERS'
            },
            {
                'key': 'ENABLE_PENDING_ORDER_WORKER',
                'label': 'settings.field.ENABLE_PENDING_ORDER_WORKER',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.ENABLE_PENDING_ORDER_WORKER'
            },
            {
                'key': 'DISABLE_RESTORE_RUNNING_STRATEGIES',
                'label': 'settings.field.DISABLE_RESTORE_RUNNING_STRATEGIES',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.DISABLE_RESTORE_RUNNING_STRATEGIES'
            },
        ]
    },

    'strategy_runtime': {
        'title': 'settings.group.strategy_runtime',
        'icon': 'cluster',
        'order': 3.25,
        'items': [
            {
                'key': 'STRATEGY_MAX_ACTIVE',
                'label': 'settings.field.STRATEGY_MAX_ACTIVE',
                'type': 'number',
                'default': '100000',
                'description': 'settings.desc.STRATEGY_MAX_ACTIVE',
            },
            {
                'key': 'STRATEGY_EVALUATOR_THREADS',
                'label': 'settings.field.STRATEGY_EVALUATOR_THREADS',
                'type': 'number',
                'default': '16',
                'description': 'settings.desc.STRATEGY_EVALUATOR_THREADS',
            },
            {
                'key': 'STRATEGY_EVALUATION_BATCH_SIZE',
                'label': 'settings.field.STRATEGY_EVALUATION_BATCH_SIZE',
                'type': 'number',
                'default': '250',
                'description': 'settings.desc.STRATEGY_EVALUATION_BATCH_SIZE',
            },
            {
                'key': 'STRATEGY_EVALUATOR_BATCH_WORKERS',
                'label': 'settings.field.STRATEGY_EVALUATOR_BATCH_WORKERS',
                'type': 'number',
                'default': '16',
                'description': 'settings.desc.STRATEGY_EVALUATOR_BATCH_WORKERS',
            },
            {
                'key': 'STRATEGY_EVALUATION_TIMEOUT_SEC',
                'label': 'settings.field.STRATEGY_EVALUATION_TIMEOUT_SEC',
                'type': 'number',
                'default': '90',
                'description': 'settings.desc.STRATEGY_EVALUATION_TIMEOUT_SEC',
            },
            {
                'key': 'BAR_CLOSE_EVENT_GRACE_SEC',
                'label': 'settings.field.BAR_CLOSE_EVENT_GRACE_SEC',
                'type': 'number',
                'default': '0.5',
                'description': 'settings.desc.BAR_CLOSE_EVENT_GRACE_SEC',
            },
        ]
    },

    'market_modules': {
        'title': 'Market Modules',
        'icon': 'appstore',
        'order': 3.5,
        'items': [
            {
                'key': 'ENABLED_MARKETS',
                'label': 'settings.field.ENABLED_MARKETS',
                'type': 'market_multiselect',
                'default': '',
                'options': market_options(),
                'description': 'settings.desc.ENABLED_MARKETS'
            },
        ]
    },

    'data_source': {
        'title': 'Data Sources',
        'icon': 'database',
        'order': 4,
        'items': [
            {
                'key': 'PROFESSIONAL_REPORT_DATA_TIER',
                'label': 'settings.field.PROFESSIONAL_REPORT_DATA_TIER',
                'type': 'select',
                'default': 'community',
                'options': [
                    {'value': 'community', 'label': 'settings.option.PROFESSIONAL_REPORT_DATA_TIER.community'},
                    {'value': 'professional', 'label': 'settings.option.PROFESSIONAL_REPORT_DATA_TIER.professional'},
                ],
                'description': 'settings.desc.PROFESSIONAL_REPORT_DATA_TIER',
            },
            {
                'key': 'PROFESSIONAL_REPORT_RISK_BUDGET_PCT',
                'label': 'settings.field.PROFESSIONAL_REPORT_RISK_BUDGET_PCT',
                'type': 'number',
                'default': '1.0',
                'description': 'settings.desc.PROFESSIONAL_REPORT_RISK_BUDGET_PCT',
            },
            {
                'key': 'FAST_ANALYSIS_INCLUDE_GLOBAL_NEWS',
                'label': 'settings.field.FAST_ANALYSIS_INCLUDE_GLOBAL_NEWS',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.FAST_ANALYSIS_INCLUDE_GLOBAL_NEWS',
            },
            {
                'key': 'CRYPTO_PUBLIC_DEFAULT_EXCHANGE',
                'label': 'settings.field.CRYPTO_PUBLIC_DEFAULT_EXCHANGE',
                'type': 'text',
                'default': 'binance',
                'description': 'settings.desc.CRYPTO_PUBLIC_DEFAULT_EXCHANGE',
            },
            {
                'key': 'FINNHUB_API_KEY',
                'label': 'settings.field.FINNHUB_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://finnhub.io/register',
                'link_text': 'settings.link.freeRegister',
                'description': 'settings.desc.FINNHUB_API_KEY',
            },
            {
                'key': 'FINNHUB_FREE_ONLY',
                'label': 'settings.field.FINNHUB_FREE_ONLY',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.FINNHUB_FREE_ONLY',
            },
            {
                'key': 'TRADING_ECONOMICS_CLIENT',
                'label': 'settings.field.TRADING_ECONOMICS_CLIENT',
                'type': 'text',
                'default': '',
                'required': False,
                'link': 'https://docs.tradingeconomics.com/',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.TRADING_ECONOMICS_CLIENT',
            },
            {
                'key': 'TRADING_ECONOMICS_KEY',
                'label': 'settings.field.TRADING_ECONOMICS_KEY',
                'type': 'password',
                'default': '',
                'required': False,
                'link': 'https://docs.tradingeconomics.com/',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.TRADING_ECONOMICS_KEY',
            },
            {
                'key': 'TRADING_ECONOMICS_BASE_URL',
                'label': 'settings.field.TRADING_ECONOMICS_BASE_URL',
                'type': 'text',
                'default': 'https://api.tradingeconomics.com',
                'description': 'settings.desc.TRADING_ECONOMICS_BASE_URL',
            },
            {
                'key': 'TRADING_ECONOMICS_TIMEOUT',
                'label': 'settings.field.TRADING_ECONOMICS_TIMEOUT',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.TRADING_ECONOMICS_TIMEOUT',
            },
            {
                'key': 'FRED_API_KEY',
                'label': 'settings.field.FRED_API_KEY',
                'type': 'password',
                'default': '',
                'required': False,
                'link': 'https://fred.stlouisfed.org/docs/api/api_key.html',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.FRED_API_KEY',
            },
            {
                'key': 'FRED_BASE_URL',
                'label': 'settings.field.FRED_BASE_URL',
                'type': 'text',
                'default': 'https://api.stlouisfed.org/fred',
                'link': 'https://fred.stlouisfed.org/docs/api/fred/',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.FRED_BASE_URL',
            },
            {
                'key': 'FRED_TIMEOUT',
                'label': 'settings.field.FRED_TIMEOUT',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.FRED_TIMEOUT',
            },
            {
                'key': 'BLS_API_KEY',
                'label': 'settings.field.BLS_API_KEY',
                'type': 'password',
                'default': '',
                'required': False,
                'link': 'https://www.bls.gov/developers/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.BLS_API_KEY',
            },
            {
                'key': 'BLS_BASE_URL',
                'label': 'settings.field.BLS_BASE_URL',
                'type': 'text',
                'default': 'https://api.bls.gov/publicAPI/v2',
                'link': 'https://www.bls.gov/developers/',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.BLS_BASE_URL',
            },
            {
                'key': 'BLS_TIMEOUT',
                'label': 'settings.field.BLS_TIMEOUT',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.BLS_TIMEOUT',
            },
            {
                'key': 'BEA_API_KEY',
                'label': 'settings.field.BEA_API_KEY',
                'type': 'password',
                'default': '',
                'required': False,
                'link': 'https://apps.bea.gov/API/signup/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.BEA_API_KEY',
            },
            {
                'key': 'BEA_BASE_URL',
                'label': 'settings.field.BEA_BASE_URL',
                'type': 'text',
                'default': 'https://apps.bea.gov/api/data',
                'link': 'https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.BEA_BASE_URL',
            },
            {
                'key': 'BEA_TIMEOUT',
                'label': 'settings.field.BEA_TIMEOUT',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.BEA_TIMEOUT',
            },
            {
                'key': 'COINGLASS_API_KEY',
                'label': 'settings.field.COINGLASS_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://docs.coinglass.com/reference/getting-started-with-your-api',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.COINGLASS_API_KEY',
            },
            {
                'key': 'CRYPTOQUANT_API_KEY',
                'label': 'settings.field.CRYPTOQUANT_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://cryptoquant.com/docs',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.CRYPTOQUANT_API_KEY',
            },
            {
                'key': 'TIINGO_API_KEY',
                'label': 'settings.field.TIINGO_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://www.tiingo.com/account/api/token',
                'link_text': 'settings.link.getToken',
                'description': 'settings.desc.TIINGO_API_KEY',
            },
            {
                'key': 'TWELVE_DATA_API_KEY',
                'label': 'settings.field.TWELVE_DATA_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://twelvedata.com/apikey',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.TWELVE_DATA_API_KEY',
            },
            {
                'key': 'ADANOS_API_KEY',
                'label': 'settings.field.ADANOS_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://adanos.org',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.ADANOS_API_KEY',
            },
            {
                'key': 'ADANOS_SENTIMENT_SOURCE',
                'label': 'settings.field.ADANOS_SENTIMENT_SOURCE',
                'type': 'text',
                'default': 'reddit',
                'description': 'settings.desc.ADANOS_SENTIMENT_SOURCE',
            },
            {
                'key': 'ADANOS_API_BASE_URL',
                'label': 'settings.field.ADANOS_API_BASE_URL',
                'type': 'text',
                'default': 'https://api.adanos.org',
                'description': 'settings.desc.ADANOS_API_BASE_URL',
            },
            {
                'key': 'TWITTERAPI_IO_KEY',
                'label': 'settings.field.TWITTERAPI_IO_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://twitterapi.io',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.TWITTERAPI_IO_KEY',
            },
            {
                'key': 'TWITTERAPI_IO_BASE_URL',
                'label': 'settings.field.TWITTERAPI_IO_BASE_URL',
                'type': 'text',
                'default': 'https://api.twitterapi.io',
                'description': 'settings.desc.TWITTERAPI_IO_BASE_URL',
            },
        ]
    },

    'search': {
        'title': 'Search & News Sources',
        'icon': 'search',
        'order': 4.5,
        'items': [
            {
                'key': 'SEARCH_PROVIDER',
                'label': 'settings.field.SEARCH_PROVIDER',
                'type': 'select',
                'options': [
                    {'value': 'tavily', 'label': 'settings.option.SEARCH_PROVIDER.tavily'},
                    {'value': 'searxng', 'label': 'settings.option.SEARCH_PROVIDER.searxng'},
                    {'value': 'gdelt', 'label': 'settings.option.SEARCH_PROVIDER.gdelt'},
                    {'value': 'serpapi', 'label': 'settings.option.SEARCH_PROVIDER.serpapi'},
                    {'value': 'google', 'label': 'settings.option.SEARCH_PROVIDER.google'},
                    {'value': 'bing', 'label': 'settings.option.SEARCH_PROVIDER.bing'},
                    {'value': 'duckduckgo', 'label': 'settings.option.SEARCH_PROVIDER.duckduckgo'},
                    {'value': 'none', 'label': 'settings.option.SEARCH_PROVIDER.none'},
                ],
                'default': 'tavily',
                'description': 'settings.desc.SEARCH_PROVIDER'
            },
            {
                'key': 'SEARCH_MAX_RESULTS',
                'label': 'settings.field.SEARCH_MAX_RESULTS',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.SEARCH_MAX_RESULTS'
            },
            {
                'key': 'TAVILY_API_KEYS',
                'label': 'settings.field.TAVILY_API_KEYS',
                'type': 'password',
                'required': False,
                'link': 'https://tavily.com/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.TAVILY_API_KEYS'
            },
            {
                'key': 'SEARCH_SEARXNG_BASE_URL',
                'label': 'settings.field.SEARCH_SEARXNG_BASE_URL',
                'type': 'text',
                'required': False,
                'default': '',
                'link': 'https://docs.searxng.org/',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.SEARCH_SEARXNG_BASE_URL'
            },
            {
                'key': 'GDELT_BASE_URL',
                'label': 'settings.field.GDELT_BASE_URL',
                'type': 'text',
                'default': 'https://api.gdeltproject.org/api/v2/doc/doc',
                'link': 'https://api.gdeltproject.org/api/v2/doc/doc',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.GDELT_BASE_URL'
            },
            {
                'key': 'SERPAPI_KEYS',
                'label': 'settings.field.SERPAPI_KEYS',
                'type': 'password',
                'required': False,
                'link': 'https://serpapi.com/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.SERPAPI_KEYS'
            },
            {
                'key': 'SEARCH_GOOGLE_API_KEY',
                'label': 'settings.field.SEARCH_GOOGLE_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://console.cloud.google.com/apis/credentials',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.SEARCH_GOOGLE_API_KEY'
            },
            {
                'key': 'SEARCH_GOOGLE_CX',
                'label': 'settings.field.SEARCH_GOOGLE_CX',
                'type': 'text',
                'required': False,
                'link': 'https://programmablesearchengine.google.com/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.SEARCH_GOOGLE_CX'
            },
            {
                'key': 'SEARCH_BING_API_KEY',
                'label': 'settings.field.SEARCH_BING_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://portal.azure.com/',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.SEARCH_BING_API_KEY'
            },
            {
                'key': 'SEARCH_SEARXNG_ENGINES',
                'label': 'settings.field.SEARCH_SEARXNG_ENGINES',
                'type': 'text',
                'required': False,
                'default': '',
                'description': 'settings.desc.SEARCH_SEARXNG_ENGINES'
            },
            {
                'key': 'SEARCH_SEARXNG_CATEGORIES',
                'label': 'settings.field.SEARCH_SEARXNG_CATEGORIES',
                'type': 'text',
                'required': False,
                'default': 'general',
                'description': 'settings.desc.SEARCH_SEARXNG_CATEGORIES'
            },
            {
                'key': 'SEARCH_SEARXNG_LANGUAGE',
                'label': 'settings.field.SEARCH_SEARXNG_LANGUAGE',
                'type': 'text',
                'required': False,
                'default': 'auto',
                'description': 'settings.desc.SEARCH_SEARXNG_LANGUAGE'
            },
            {
                'key': 'SEARCH_SEARXNG_TIMEOUT',
                'label': 'settings.field.SEARCH_SEARXNG_TIMEOUT',
                'type': 'number',
                'default': '12',
                'description': 'settings.desc.SEARCH_SEARXNG_TIMEOUT'
            },
            {
                'key': 'GDELT_TIMEOUT',
                'label': 'settings.field.GDELT_TIMEOUT',
                'type': 'number',
                'default': '12',
                'description': 'settings.desc.GDELT_TIMEOUT'
            },
            {
                'key': 'GDELT_MAX_RESULTS',
                'label': 'settings.field.GDELT_MAX_RESULTS',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.GDELT_MAX_RESULTS'
            },
            {
                'key': 'ALPHA_VANTAGE_API_KEY',
                'label': 'settings.field.ALPHA_VANTAGE_API_KEY',
                'type': 'password',
                'required': False,
                'link': 'https://www.alphavantage.co/support/#api-key',
                'link_text': 'settings.link.getApiKey',
                'description': 'settings.desc.ALPHA_VANTAGE_API_KEY'
            },
            {
                'key': 'ALPHA_VANTAGE_BASE_URL',
                'label': 'settings.field.ALPHA_VANTAGE_BASE_URL',
                'type': 'text',
                'default': 'https://www.alphavantage.co/query',
                'link': 'https://www.alphavantage.co/documentation/',
                'link_text': 'settings.link.viewDocs',
                'description': 'settings.desc.ALPHA_VANTAGE_BASE_URL'
            },
            {
                'key': 'ALPHA_VANTAGE_TIMEOUT',
                'label': 'settings.field.ALPHA_VANTAGE_TIMEOUT',
                'type': 'number',
                'default': '12',
                'description': 'settings.desc.ALPHA_VANTAGE_TIMEOUT'
            },
            {
                'key': 'ALPHA_VANTAGE_NEWS_LIMIT',
                'label': 'settings.field.ALPHA_VANTAGE_NEWS_LIMIT',
                'type': 'number',
                'default': '20',
                'description': 'settings.desc.ALPHA_VANTAGE_NEWS_LIMIT'
            },
        ]
    },

    'email': {
        'title': 'Email (SMTP)',
        'icon': 'mail',
        'order': 5,
        'items': [
            {
                'key': 'SMTP_HOST',
                'label': 'settings.field.SMTP_HOST',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.SMTP_HOST'
            },
            {
                'key': 'SMTP_PORT',
                'label': 'settings.field.SMTP_PORT',
                'type': 'number',
                'default': '587',
                'description': 'settings.desc.SMTP_PORT'
            },
            {
                'key': 'SMTP_USER',
                'label': 'settings.field.SMTP_USER',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.SMTP_USER'
            },
            {
                'key': 'SMTP_PASSWORD',
                'label': 'settings.field.SMTP_PASSWORD',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.SMTP_PASSWORD'
            },
            {
                'key': 'SMTP_FROM',
                'label': 'settings.field.SMTP_FROM',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.SMTP_FROM'
            },
            {
                'key': 'SMTP_USE_TLS',
                'label': 'settings.field.SMTP_USE_TLS',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.SMTP_USE_TLS'
            },
            {
                'key': 'SMTP_USE_SSL',
                'label': 'settings.field.SMTP_USE_SSL',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.SMTP_USE_SSL'
            },
        ]
    },

    'sms': {
        'title': 'SMS (Twilio)',
        'icon': 'phone',
        'order': 6,
        'items': [
            {
                'key': 'TWILIO_ACCOUNT_SID',
                'label': 'settings.field.TWILIO_ACCOUNT_SID',
                'type': 'password',
                'required': False,
                'link': 'https://console.twilio.com/',
                'link_text': 'settings.link.getApi',
                'description': 'settings.desc.TWILIO_ACCOUNT_SID'
            },
            {
                'key': 'TWILIO_AUTH_TOKEN',
                'label': 'settings.field.TWILIO_AUTH_TOKEN',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.TWILIO_AUTH_TOKEN'
            },
            {
                'key': 'TWILIO_FROM_NUMBER',
                'label': 'settings.field.TWILIO_FROM_NUMBER',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.TWILIO_FROM_NUMBER'
            },
        ]
    },

    # ==================== 7. AI Agent ====================
    'agent': {
        'title': 'AI Agent',
        'icon': 'experiment',
        'order': 7,
        'items': [
            # Agent Gateway (/api/agent/v1) deployment knobs
            {
                'key': 'AGENT_LIVE_TRADING_ENABLED',
                'label': 'settings.field.AGENT_LIVE_TRADING_ENABLED',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.AGENT_LIVE_TRADING_ENABLED'
            },
            {
                'key': 'QUANTDINGER_DEPLOYMENT_MODE',
                'label': 'settings.field.QUANTDINGER_DEPLOYMENT_MODE',
                'type': 'select',
                'options': [
                    {'value': '', 'label': 'settings.option.QUANTDINGER_DEPLOYMENT_MODE.selfHosted'},
                    {'value': 'saas', 'label': 'settings.option.QUANTDINGER_DEPLOYMENT_MODE.saas'},
                    {'value': 'hosted', 'label': 'settings.option.QUANTDINGER_DEPLOYMENT_MODE.hosted'},
                ],
                'default': '',
                'description': 'settings.desc.QUANTDINGER_DEPLOYMENT_MODE'
            },
            {
                'key': 'AGENT_JOBS_MAX_WORKERS',
                'label': 'settings.field.AGENT_JOBS_MAX_WORKERS',
                'type': 'number',
                'default': '4',
                'description': 'settings.desc.AGENT_JOBS_MAX_WORKERS'
            },
            {
                'key': 'ENABLE_REFLECTION_WORKER',
                'label': 'settings.field.ENABLE_REFLECTION_WORKER',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.ENABLE_REFLECTION_WORKER'
            },
            {
                'key': 'REFLECTION_WORKER_INTERVAL_SEC',
                'label': 'settings.field.REFLECTION_WORKER_INTERVAL_SEC',
                'type': 'number',
                'default': '86400',
                'description': 'settings.desc.REFLECTION_WORKER_INTERVAL_SEC'
            },
            {
                'key': 'REFLECTION_MIN_AGE_DAYS',
                'label': 'settings.field.REFLECTION_MIN_AGE_DAYS',
                'type': 'number',
                'default': '7',
                'description': 'settings.desc.REFLECTION_MIN_AGE_DAYS'
            },
            {
                'key': 'REFLECTION_VALIDATE_LIMIT',
                'label': 'settings.field.REFLECTION_VALIDATE_LIMIT',
                'type': 'number',
                'default': '200',
                'description': 'settings.desc.REFLECTION_VALIDATE_LIMIT'
            },
            {
                'key': 'ENABLE_CONFIDENCE_CALIBRATION',
                'label': 'settings.field.ENABLE_CONFIDENCE_CALIBRATION',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.ENABLE_CONFIDENCE_CALIBRATION'
            },
            {
                'key': 'ENABLE_AI_ENSEMBLE',
                'label': 'settings.field.ENABLE_AI_ENSEMBLE',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.ENABLE_AI_ENSEMBLE'
            },
            {
                'key': 'AI_ENSEMBLE_MODELS',
                'label': 'settings.field.AI_ENSEMBLE_MODELS',
                'type': 'text',
                'default': 'openai/gpt-5.4,openai/gpt-4o-mini',
                'description': 'settings.desc.AI_ENSEMBLE_MODELS'
            },
            {
                'key': 'AI_CALIBRATION_MARKETS',
                'label': 'settings.field.AI_CALIBRATION_MARKETS',
                'type': 'text',
                'default': 'Crypto',
                'description': 'settings.desc.AI_CALIBRATION_MARKETS'
            },
            {
                'key': 'AI_CALIBRATION_LOOKBACK_DAYS',
                'label': 'settings.field.AI_CALIBRATION_LOOKBACK_DAYS',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.AI_CALIBRATION_LOOKBACK_DAYS'
            },
            {
                'key': 'AI_CALIBRATION_MIN_SAMPLES',
                'label': 'settings.field.AI_CALIBRATION_MIN_SAMPLES',
                'type': 'number',
                'default': '80',
                'description': 'settings.desc.AI_CALIBRATION_MIN_SAMPLES'
            },
        ]
    },

    'network': {
        'title': 'Network & Proxy',
        'icon': 'global',
        'order': 8,
        'items': [
            {
                'key': 'PROXY_URL',
                'label': 'settings.field.PROXY_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.PROXY_URL'
            },
        ]
    },

    'security': {
        'title': 'Registration & OAuth',
        'icon': 'safety',
        'order': 10,
        'items': [
            {
                'key': 'ENABLE_REGISTRATION',
                'label': 'settings.field.ENABLE_REGISTRATION',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.ENABLE_REGISTRATION'
            },
            {
                'key': 'MFA_ENABLED',
                'label': 'settings.field.MFA_ENABLED',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.MFA_ENABLED'
            },
            {
                'key': 'MFA_RISK_LOGIN_ONLY',
                'label': 'settings.field.MFA_RISK_LOGIN_ONLY',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.MFA_RISK_LOGIN_ONLY'
            },
            {
                'key': 'FRONTEND_URL',
                'label': 'settings.field.FRONTEND_URL',
                'type': 'text',
                'default': 'http://localhost:8080',
                'description': 'settings.desc.FRONTEND_URL'
            },
            {
                'key': 'OAUTH_ALLOWED_REDIRECTS',
                'label': 'settings.field.OAUTH_ALLOWED_REDIRECTS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.OAUTH_ALLOWED_REDIRECTS'
            },
            {
                'key': 'OAUTH_STATE_TTL_MINUTES',
                'label': 'settings.field.OAUTH_STATE_TTL_MINUTES',
                'type': 'number',
                'default': '20',
                'description': 'settings.desc.OAUTH_STATE_TTL_MINUTES'
            },
            {
                'key': 'TURNSTILE_SITE_KEY',
                'label': 'settings.field.TURNSTILE_SITE_KEY',
                'type': 'text',
                'required': False,
                'link': 'https://dash.cloudflare.com/?to=/:account/turnstile',
                'link_text': 'settings.link.getTurnstileKey',
                'description': 'settings.desc.TURNSTILE_SITE_KEY'
            },
            {
                'key': 'TURNSTILE_SECRET_KEY',
                'label': 'settings.field.TURNSTILE_SECRET_KEY',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.TURNSTILE_SECRET_KEY'
            },
            {
                'key': 'GOOGLE_CLIENT_ID',
                'label': 'settings.field.GOOGLE_CLIENT_ID',
                'type': 'text',
                'required': False,
                'link': 'https://console.cloud.google.com/apis/credentials',
                'link_text': 'settings.link.getGoogleCredentials',
                'description': 'settings.desc.GOOGLE_CLIENT_ID'
            },
            {
                'key': 'GOOGLE_CLIENT_SECRET',
                'label': 'settings.field.GOOGLE_CLIENT_SECRET',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.GOOGLE_CLIENT_SECRET'
            },
            {
                'key': 'GOOGLE_REDIRECT_URI',
                'label': 'settings.field.GOOGLE_REDIRECT_URI',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.GOOGLE_REDIRECT_URI'
            },
            {
                'key': 'GITHUB_CLIENT_ID',
                'label': 'settings.field.GITHUB_CLIENT_ID',
                'type': 'text',
                'required': False,
                'link': 'https://github.com/settings/developers',
                'link_text': 'settings.link.getGithubCredentials',
                'description': 'settings.desc.GITHUB_CLIENT_ID'
            },
            {
                'key': 'GITHUB_CLIENT_SECRET',
                'label': 'settings.field.GITHUB_CLIENT_SECRET',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.GITHUB_CLIENT_SECRET'
            },
            {
                'key': 'GITHUB_REDIRECT_URI',
                'label': 'settings.field.GITHUB_REDIRECT_URI',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.GITHUB_REDIRECT_URI'
            },

            # ===== Login / verification-code rate limiting (advanced) =====
            {
                'key': 'SECURITY_IP_MAX_ATTEMPTS',
                'label': 'settings.field.SECURITY_IP_MAX_ATTEMPTS',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.SECURITY_IP_MAX_ATTEMPTS'
            },
            {
                'key': 'SECURITY_IP_WINDOW_MINUTES',
                'label': 'settings.field.SECURITY_IP_WINDOW_MINUTES',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.SECURITY_IP_WINDOW_MINUTES'
            },
            {
                'key': 'SECURITY_IP_BLOCK_MINUTES',
                'label': 'settings.field.SECURITY_IP_BLOCK_MINUTES',
                'type': 'number',
                'default': '15',
                'description': 'settings.desc.SECURITY_IP_BLOCK_MINUTES'
            },
            {
                'key': 'SECURITY_ACCOUNT_MAX_ATTEMPTS',
                'label': 'settings.field.SECURITY_ACCOUNT_MAX_ATTEMPTS',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.SECURITY_ACCOUNT_MAX_ATTEMPTS'
            },
            {
                'key': 'SECURITY_ACCOUNT_WINDOW_MINUTES',
                'label': 'settings.field.SECURITY_ACCOUNT_WINDOW_MINUTES',
                'type': 'number',
                'default': '60',
                'description': 'settings.desc.SECURITY_ACCOUNT_WINDOW_MINUTES'
            },
            {
                'key': 'SECURITY_ACCOUNT_BLOCK_MINUTES',
                'label': 'settings.field.SECURITY_ACCOUNT_BLOCK_MINUTES',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.SECURITY_ACCOUNT_BLOCK_MINUTES'
            },
            {
                'key': 'VERIFICATION_CODE_EXPIRE_MINUTES',
                'label': 'settings.field.VERIFICATION_CODE_EXPIRE_MINUTES',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.VERIFICATION_CODE_EXPIRE_MINUTES'
            },
            {
                'key': 'VERIFICATION_CODE_RATE_LIMIT',
                'label': 'settings.field.VERIFICATION_CODE_RATE_LIMIT',
                'type': 'number',
                'default': '60',
                'description': 'settings.desc.VERIFICATION_CODE_RATE_LIMIT'
            },
            {
                'key': 'VERIFICATION_CODE_IP_HOURLY_LIMIT',
                'label': 'settings.field.VERIFICATION_CODE_IP_HOURLY_LIMIT',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.VERIFICATION_CODE_IP_HOURLY_LIMIT'
            },
            {
                'key': 'VERIFICATION_CODE_MAX_ATTEMPTS',
                'label': 'settings.field.VERIFICATION_CODE_MAX_ATTEMPTS',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.VERIFICATION_CODE_MAX_ATTEMPTS'
            },
            {
                'key': 'VERIFICATION_CODE_LOCK_MINUTES',
                'label': 'settings.field.VERIFICATION_CODE_LOCK_MINUTES',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.VERIFICATION_CODE_LOCK_MINUTES'
            },
            {
                'key': 'MFA_CHALLENGE_EXPIRE_MINUTES',
                'label': 'settings.field.MFA_CHALLENGE_EXPIRE_MINUTES',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.MFA_CHALLENGE_EXPIRE_MINUTES'
            },
            {
                'key': 'MFA_MAX_ATTEMPTS',
                'label': 'settings.field.MFA_MAX_ATTEMPTS',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.MFA_MAX_ATTEMPTS'
            },
        ]
    },

    'billing': {
        'title': 'Billing & Credits',
        'icon': 'dollar',
        'order': 11,
        'items': [
            {
                'key': 'BILLING_ENABLED',
                'label': 'settings.field.BILLING_ENABLED',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.BILLING_ENABLED',
            },

            # ===== USDT Pay (v3.0.6+: one fixed address per chain + amount-suffix matching) =====
            # Model: each chain has a single receiving address. Orders are
            # disambiguated by a unique amount suffix in the low decimals
            # (e.g. 19.991234 USDT, where .001234 is the order tag), so funds
            # land directly in the operator wallet without per-order HD
            # derivation or batched consolidation.
            {
                'key': 'USDT_PAY_ENABLED',
                'label': 'settings.field.USDT_PAY_ENABLED',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.USDT_PAY_ENABLED',
            },
            {
                'key': 'USDT_PAY_ENABLED_CHAINS',
                'label': 'settings.field.USDT_PAY_ENABLED_CHAINS',
                'type': 'text',
                'default': 'TRC20,BEP20,ERC20,SOL',
                'description': 'settings.desc.USDT_PAY_ENABLED_CHAINS',
            },
            {
                'key': 'USDT_TRC20_ADDRESS',
                'label': 'settings.field.USDT_TRC20_ADDRESS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.USDT_TRC20_ADDRESS',
            },
            {
                'key': 'USDT_BEP20_ADDRESS',
                'label': 'settings.field.USDT_BEP20_ADDRESS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.USDT_BEP20_ADDRESS',
            },
            {
                'key': 'USDT_ERC20_ADDRESS',
                'label': 'settings.field.USDT_ERC20_ADDRESS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.USDT_ERC20_ADDRESS',
            },
            {
                'key': 'USDT_SOL_ADDRESS',
                'label': 'settings.field.USDT_SOL_ADDRESS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.USDT_SOL_ADDRESS',
            },
            {
                'key': 'USDT_TRC20_CONTRACT',
                'label': 'settings.field.USDT_TRC20_CONTRACT',
                'type': 'text',
                'default': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
                'required': False,
                'description': 'settings.desc.USDT_TRC20_CONTRACT',
            },
            {
                'key': 'USDT_BEP20_CONTRACT',
                'label': 'settings.field.USDT_BEP20_CONTRACT',
                'type': 'text',
                'default': '0x55d398326f99059fF775485246999027B3197955',
                'required': False,
                'description': 'settings.desc.USDT_BEP20_CONTRACT',
            },
            {
                'key': 'USDT_ERC20_CONTRACT',
                'label': 'settings.field.USDT_ERC20_CONTRACT',
                'type': 'text',
                'default': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
                'required': False,
                'description': 'settings.desc.USDT_ERC20_CONTRACT',
            },
            {
                'key': 'USDT_SOL_MINT',
                'label': 'settings.field.USDT_SOL_MINT',
                'type': 'text',
                'default': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
                'required': False,
                'description': 'settings.desc.USDT_SOL_MINT',
            },
            {
                'key': 'USDC_PAY_ENABLED',
                'label': 'settings.field.USDC_PAY_ENABLED',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.USDC_PAY_ENABLED',
            },
            {
                'key': 'USDC_PAY_ENABLED_CHAINS',
                'label': 'settings.field.USDC_PAY_ENABLED_CHAINS',
                'type': 'text',
                'default': 'ERC20,SOL',
                'description': 'settings.desc.USDC_PAY_ENABLED_CHAINS',
            },
            {
                'key': 'USDC_ERC20_ADDRESS',
                'label': 'settings.field.USDC_ERC20_ADDRESS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.USDC_ERC20_ADDRESS',
            },
            {
                'key': 'USDC_SOL_ADDRESS',
                'label': 'settings.field.USDC_SOL_ADDRESS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.USDC_SOL_ADDRESS',
            },
            {
                'key': 'USDC_ERC20_CONTRACT',
                'label': 'settings.field.USDC_ERC20_CONTRACT',
                'type': 'text',
                'default': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
                'required': False,
                'description': 'settings.desc.USDC_ERC20_CONTRACT',
            },
            {
                'key': 'USDC_SOL_MINT',
                'label': 'settings.field.USDC_SOL_MINT',
                'type': 'text',
                'default': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                'required': False,
                'description': 'settings.desc.USDC_SOL_MINT',
            },
            {
                'key': 'STRIPE_PAY_ENABLED',
                'label': 'settings.field.STRIPE_PAY_ENABLED',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.STRIPE_PAY_ENABLED',
            },
            {
                'key': 'STRIPE_SECRET_KEY',
                'label': 'settings.field.STRIPE_SECRET_KEY',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.STRIPE_SECRET_KEY',
            },
            {
                'key': 'STRIPE_WEBHOOK_SECRET',
                'label': 'settings.field.STRIPE_WEBHOOK_SECRET',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.STRIPE_WEBHOOK_SECRET',
            },
            {
                'key': 'STRIPE_PRODUCT_TAX_CODE',
                'label': 'settings.field.STRIPE_PRODUCT_TAX_CODE',
                'type': 'text',
                'default': 'txcd_10103000',
                'required': False,
                'description': 'settings.desc.STRIPE_PRODUCT_TAX_CODE',
            },
            {
                'key': 'STRIPE_SUCCESS_URL',
                'label': 'settings.field.STRIPE_SUCCESS_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.STRIPE_SUCCESS_URL',
            },
            {
                'key': 'STRIPE_CANCEL_URL',
                'label': 'settings.field.STRIPE_CANCEL_URL',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.STRIPE_CANCEL_URL',
            },
            {
                'key': 'TRONGRID_API_KEY',
                'label': 'settings.field.TRONGRID_API_KEY',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.TRONGRID_API_KEY',
            },
            {
                'key': 'TRONGRID_BASE_URL',
                'label': 'settings.field.TRONGRID_BASE_URL',
                'type': 'text',
                'default': 'https://api.trongrid.io',
                'description': 'settings.desc.TRONGRID_BASE_URL'
            },
            {
                'key': 'ETHERSCAN_API_KEY',
                'label': 'settings.field.ETHERSCAN_API_KEY',
                'type': 'password',
                'required': False,
                'description': 'settings.desc.ETHERSCAN_API_KEY',
            },
            {
                'key': 'ETHERSCAN_V2_BASE_URL',
                'label': 'settings.field.ETHERSCAN_V2_BASE_URL',
                'type': 'text',
                'default': 'https://api.etherscan.io/v2/api',
                'description': 'settings.desc.ETHERSCAN_V2_BASE_URL'
            },
            {
                'key': 'BSC_RPC_URLS',
                'label': 'settings.field.BSC_RPC_URLS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.BSC_RPC_URLS',
            },
            {
                'key': 'ETH_RPC_URLS',
                'label': 'settings.field.ETH_RPC_URLS',
                'type': 'text',
                'required': False,
                'description': 'settings.desc.ETH_RPC_URLS'
            },
            {
                'key': 'SOLANA_RPC_URL',
                'label': 'settings.field.SOLANA_RPC_URL',
                'type': 'text',
                'default': 'https://api.mainnet-beta.solana.com',
                'description': 'settings.desc.SOLANA_RPC_URL'
            },
            {
                'key': 'BEP20_PREFER_EXPLORER',
                'label': 'settings.field.BEP20_PREFER_EXPLORER',
                'type': 'boolean',
                'default': 'False',
                'description': 'settings.desc.BEP20_PREFER_EXPLORER'
            },
            {
                'key': 'ERC20_PREFER_EXPLORER',
                'label': 'settings.field.ERC20_PREFER_EXPLORER',
                'type': 'boolean',
                'default': 'True',
                'description': 'settings.desc.ERC20_PREFER_EXPLORER'
            },
            {
                'key': 'USDT_AMOUNT_SUFFIX_DECIMALS',
                'label': 'settings.field.USDT_AMOUNT_SUFFIX_DECIMALS',
                'type': 'number',
                'default': 6,
                'description': 'settings.desc.USDT_AMOUNT_SUFFIX_DECIMALS'
            },
            {
                'key': 'USDT_PAY_CONFIRM_SECONDS',
                'label': 'settings.field.USDT_PAY_CONFIRM_SECONDS',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.USDT_PAY_CONFIRM_SECONDS',
            },
            {
                'key': 'USDT_PAY_EXPIRE_MINUTES',
                'label': 'settings.field.USDT_PAY_EXPIRE_MINUTES',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.USDT_PAY_EXPIRE_MINUTES',
            },
            {
                'key': 'USDT_WORKER_POLL_INTERVAL',
                'label': 'settings.field.USDT_WORKER_POLL_INTERVAL',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.USDT_WORKER_POLL_INTERVAL',
            },
            {
                'key': 'BILLING_COST_BACKTEST',
                'label': 'settings.field.BILLING_COST_BACKTEST',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.BILLING_COST_BACKTEST',
            },
            {
                'key': 'BILLING_COST_AI_REVIEW',
                'label': 'settings.field.BILLING_COST_AI_REVIEW',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.BILLING_COST_AI_REVIEW',
            },
            {
                'key': 'BILLING_COST_AI_ANALYSIS',
                'label': 'settings.field.BILLING_COST_AI_ANALYSIS',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.BILLING_COST_AI_ANALYSIS',
            },
            {
                'key': 'BILLING_COST_AI_CODE_GEN',
                'label': 'settings.field.BILLING_COST_AI_CODE_GEN',
                'type': 'number',
                'default': '30',
                'description': 'settings.desc.BILLING_COST_AI_CODE_GEN',
            },
            {
                'key': 'BILLING_COST_AI_COPILOT_CHAT',
                'label': 'settings.field.BILLING_COST_AI_COPILOT_CHAT',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.BILLING_COST_AI_COPILOT_CHAT',
            },
            {
                'key': 'BILLING_COST_AI_COPILOT_IMAGE',
                'label': 'settings.field.BILLING_COST_AI_COPILOT_IMAGE',
                'type': 'number',
                'default': '15',
                'description': 'settings.desc.BILLING_COST_AI_COPILOT_IMAGE',
            },
            {
                'key': 'BILLING_COST_AI_DECISION_FILTER',
                'label': 'settings.field.BILLING_COST_AI_DECISION_FILTER',
                'type': 'number',
                'default': '1',
                'description': 'settings.desc.BILLING_COST_AI_DECISION_FILTER'
            },
            {
                'key': 'BILLING_COST_EVENT_RADAR',
                'label': 'settings.field.BILLING_COST_EVENT_RADAR',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.BILLING_COST_EVENT_RADAR'
            },
            {
                'key': 'MARKETPLACE_PLATFORM_FEE_RATE',
                'label': 'settings.field.MARKETPLACE_PLATFORM_FEE_RATE',
                'type': 'text',
                'default': '0',
                'description': 'settings.desc.MARKETPLACE_PLATFORM_FEE_RATE',
            },
            {
                'key': 'CREDITS_REGISTER_BONUS',
                'label': 'settings.field.CREDITS_REGISTER_BONUS',
                'type': 'number',
                'default': '100',
                'description': 'settings.desc.CREDITS_REGISTER_BONUS',
            },
            {
                'key': 'CREDITS_REFERRAL_BONUS',
                'label': 'settings.field.CREDITS_REFERRAL_BONUS',
                'type': 'number',
                'default': '50',
                'description': 'settings.desc.CREDITS_REFERRAL_BONUS',
            },
            {
                'key': 'FREE_USER_STRATEGY_LIMIT',
                'label': 'settings.field.FREE_USER_STRATEGY_LIMIT',
                'type': 'number',
                'default': '5',
                'description': 'settings.desc.FREE_USER_STRATEGY_LIMIT'
            },
            {
                'key': 'REFERRAL_PROGRAM_ENABLED',
                'label': 'settings.field.REFERRAL_PROGRAM_ENABLED',
                'type': 'boolean',
                'default': False,
                'description': 'settings.desc.REFERRAL_PROGRAM_ENABLED'
            },
            {
                'key': 'REFERRAL_REWARD_RATES',
                'label': 'settings.field.REFERRAL_REWARD_RATES',
                'type': 'text',
                'default': '10,5,3',
                'description': 'settings.desc.REFERRAL_REWARD_RATES'
            },
            {
                'key': 'REFERRAL_REWARD_HOLD_DAYS',
                'label': 'settings.field.REFERRAL_REWARD_HOLD_DAYS',
                'type': 'number',
                'default': '7',
                'description': 'settings.desc.REFERRAL_REWARD_HOLD_DAYS'
            },
            {
                'key': 'REFERRAL_MIN_WITHDRAWAL_USD',
                'label': 'settings.field.REFERRAL_MIN_WITHDRAWAL_USD',
                'type': 'number',
                'default': '10',
                'description': 'settings.desc.REFERRAL_MIN_WITHDRAWAL_USD'
            },
        ]
    },

}


def _schema_with_advanced_flags():
    """Return a deep-ish copy of CONFIG_SCHEMA with ``is_advanced`` annotated on
    every item according to ``ADVANCED_KEYS``. Lets the frontend split settings
    into a Basic / Advanced tab without each item needing a manual flag."""
    annotated = {}
    for group_key, group in CONFIG_SCHEMA.items():
        items = []
        for item in group.get('items', []):
            new_item = dict(item)
            new_item['is_advanced'] = item['key'] in ADVANCED_KEYS
            items.append(new_item)
        annotated[group_key] = {**group, 'items': items}
    return annotated


def _effective_schema(env_values=None):
    """Return only operator-safe settings curated for the admin UI.

    Deployment, database, container, and observability variables remain in the
    dotenv file because changing them from a running application cannot be
    applied safely or atomically.
    """
    return _schema_with_advanced_flags()


@settings_blp.route('/schema', methods=['GET'])
@login_required
@admin_required
def get_settings_schema():
    """Return settings schema definition (admin only)."""
    return jsonify({
        'code': 1,
        'msg': 'success',
        'data': _effective_schema()
    })


@settings_blp.route('/public-config', methods=['GET'])
@login_required
def get_public_config():
    """Return non-sensitive config values needed by frontend widgets."""
    from app.config.data_sources import CryptoPublicConfig
    return jsonify({
        'code': 1,
        'data': {
            'crypto_public_default_exchange': (CryptoPublicConfig.DEFAULT_EXCHANGE or 'binance').lower(),
        }
    })


@settings_blp.route('/brand-config', methods=['GET'])
def get_brand_config():
    """Public, no-auth endpoint exposing branding / legal / contact info.

    Drives the frontend's logo, footer, social links, legal modals and version
    label entirely from backend ENV vars so operators can rebrand a deployment
    by editing ``.env`` (or the Settings page) — no frontend rebuild required.

    Empty ENV values fall back to the bundled defaults so a fresh
    install still ships with working links instead of blanks.
    """
    return jsonify({
        'code': 1,
        'msg': 'success',
        'data': build_brand_config(APP_VERSION)
    })


@settings_blp.route('/values', methods=['GET'])
@login_required
@admin_required
def get_settings_values():
    """Return current settings values without exposing stored secrets."""
    env_values = read_env_file()
    
    schema = _effective_schema(env_values)
    result = {}
    for group_key, group in schema.items():
        result[group_key] = {}
        for item in group['items']:
            key = item['key']
            if item['type'] == 'password':
                value = env_values.get(key, '')
                result[group_key][key] = ''
                result[group_key][f'{key}_configured'] = bool(value)
            else:
                result[group_key][key] = env_values.get(key, item.get('default', ''))
    
    return jsonify({
        'code': 1,
        'msg': 'success',
        'data': result
    })


@settings_blp.route('/market-catalog', methods=['GET'])
@login_required
@admin_required
def get_market_catalog():
    """Return market catalog coverage and the latest synchronization state."""
    try:
        from app.services.market_catalog_sync import get_market_catalog_overview
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': get_market_catalog_overview(),
        })
    except Exception as exc:
        logger.error("Failed to load market catalog overview: %s", exc, exc_info=True)
        return jsonify({'code': 0, 'msg': str(exc)}), 500


@settings_blp.route('/market-catalog/sync', methods=['POST'])
@login_required
@admin_required
def sync_market_catalog():
    """Start a non-blocking full sync for the supported crypto venues."""
    try:
        from app.services.market_catalog_sync import start_market_catalog_sync
        result = start_market_catalog_sync('manual')
        if not result.get('started'):
            return jsonify({
                'code': 0,
                'msg': result.get('reason', 'already_running'),
                'data': result,
            }), 409
        return jsonify({'code': 1, 'msg': 'started', 'data': result}), 202
    except Exception as exc:
        logger.error("Failed to start market catalog sync: %s", exc, exc_info=True)
        return jsonify({'code': 0, 'msg': str(exc)}), 500


@settings_blp.route('/save', methods=['POST'])
@login_required
@admin_required
def save_settings():
    """Save settings to .env (admin only)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'code': 0, 'msg': 'Invalid request payload'})
        
        current_env = read_env_file()
        effective_schema = _effective_schema(current_env)
        
        updates = {}
        for group_key, group_values in data.items():
            if group_key not in effective_schema:
                continue
            
            for item in effective_schema[group_key]['items']:
                key = item['key']
                if key in group_values:
                    new_value = group_values[key]
                    
                    if new_value is None or new_value == '':
                        if not item.get('required', True):
                            updates[key] = ''
                    else:
                        updates[key] = str(new_value)

        if 'REFERRAL_REWARD_RATES' in updates:
            try:
                rate_tokens = [token for token in re.split(r'[,，;；\s]+', updates['REFERRAL_REWARD_RATES']) if token]
                rates = [float(token.rstrip('%')) for token in rate_tokens]
                if not rates or len(rates) > 3 or any(rate < 0 or rate > 100 for rate in rates) or sum(rates) > 100:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({'code': 0, 'msg': 'settings.invalidReferralRewardRates'}), 400
        for positive_key in ('FREE_USER_STRATEGY_LIMIT', 'REFERRAL_MIN_WITHDRAWAL_USD'):
            if positive_key in updates:
                try:
                    if float(updates[positive_key]) <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return jsonify({'code': 0, 'msg': 'settings.invalidPositiveValue'}), 400
        if 'REFERRAL_REWARD_HOLD_DAYS' in updates:
            try:
                hold_days = int(float(updates['REFERRAL_REWARD_HOLD_DAYS']))
                if hold_days < 0 or hold_days > 365:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({'code': 0, 'msg': 'settings.invalidRewardHoldDays'}), 400

        admin_email_sync = None
        if 'ADMIN_EMAIL' in updates:
            requested_admin_email = str(updates.get('ADMIN_EMAIL') or '').strip().lower()
            if requested_admin_email and requested_admin_email != 'admin@example.com':
                if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', requested_admin_email):
                    return jsonify({'code': 0, 'msg': 'Invalid admin email'}), 400

                from app.services.user_service import get_user_service
                user_service = get_user_service()
                admin_username = str(
                    updates.get('ADMIN_USER')
                    or current_env.get('ADMIN_USER')
                    or os.getenv('ADMIN_USER')
                    or ''
                ).strip()
                if not admin_username:
                    try:
                        from app.config.settings import Config
                        admin_username = str(Config.ADMIN_USER or 'quantdinger')
                    except Exception:
                        admin_username = 'quantdinger'

                admin_user = user_service.get_user_by_username(admin_username)
                if not admin_user:
                    first_id = user_service.get_first_user_id()
                    admin_user = user_service.get_user_by_id(first_id) if first_id is not None else None

                existing = user_service.get_user_by_email(requested_admin_email)
                if existing and admin_user and int(existing.get('id')) != int(admin_user.get('id')):
                    return jsonify({
                        'code': 0,
                        'msg': 'Admin email is already used by another account'
                    }), 409

        updates = {
            key: value
            for key, value in updates.items()
            if str(current_env.get(key, '')) != str(value)
        }

        if not updates:
            return jsonify({
                'code': 1,
                'msg': 'settings.alreadyUpToDate',
                'data': {
                    'updated_keys': [],
                    'restart_required_keys': [],
                    'hot_reloaded_keys': [],
                    'requires_restart': False,
                    'hot_reloaded': False,
                    'services_refreshed': False,
                }
            })
        
        current_env.update(updates)
        
        if write_env_file(current_env):
            restart_keys = sorted(RESTART_REQUIRED_SETTINGS.intersection(updates))
            hot_reload_keys = sorted(set(updates) - set(restart_keys))

            # Runtime reload preserves process-group security roots. Skip the
            # reload entirely when every changed value requires a restart.
            if hot_reload_keys:
                clear_config_cache()
                reload_runtime_env()
                refresh_runtime_services()

            if 'ADMIN_EMAIL' in updates:
                try:
                    from app.services.user_service import get_user_service
                    admin_email_sync = get_user_service().sync_admin_email_from_config(
                        updates.get('ADMIN_EMAIL'),
                        overwrite_existing=True,
                    )
                except Exception as sync_error:
                    logger.warning(f"Failed to sync admin email after settings save: {sync_error}")
                    admin_email_sync = {
                        'synced': False,
                        'reason': 'error',
                        'message': str(sync_error),
                    }

            response_data = {
                'updated_keys': list(updates.keys()),
                'restart_required_keys': restart_keys,
                'hot_reloaded_keys': hot_reload_keys,
                'requires_restart': bool(restart_keys),
                'hot_reloaded': bool(hot_reload_keys),
                'services_refreshed': bool(hot_reload_keys)
            }
            if admin_email_sync is not None:
                response_data['admin_email_sync'] = admin_email_sync
            
            return jsonify({
                'code': 1,
                'msg': 'Settings saved successfully',
                'data': response_data
            })
        else:
            return jsonify({'code': 0, 'msg': 'Failed to save settings'})
    
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return jsonify({'code': 0, 'msg': f'Save failed: {str(e)}'})


@settings_blp.route('/openrouter-balance', methods=['GET'])
@login_required
@admin_required
def get_openrouter_balance():
    """Query OpenRouter account balance (admin only)."""
    try:
        import requests
        from app.config.api_keys import APIKeys
        
        api_key = APIKeys.OPENROUTER_API_KEY
        if not api_key:
            return jsonify({
                'code': 0, 
                'msg': 'OpenRouter API Key 未配置',
                'data': None
            })
        
        # https://openrouter.ai/docs#limits
        resp = requests.get(
            'https://openrouter.ai/api/v1/auth/key',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            key_data = data.get('data', {})
            usage = key_data.get('usage', 0)  # 已使用金额
            limit = key_data.get('limit')  # 限额（可能为null表示无限制）
            limit_remaining = key_data.get('limit_remaining')  # 剩余额度
            is_free_tier = key_data.get('is_free_tier', False)
            rate_limit = key_data.get('rate_limit', {})
            
            return jsonify({
                'code': 1,
                'msg': 'success',
                'data': {
                    'usage': round(usage, 4),  # 已使用（美元）
                    'limit': limit,  # 总限额
                    'limit_remaining': round(limit_remaining, 4) if limit_remaining is not None else None,  # 剩余额度
                    'is_free_tier': is_free_tier,
                    'rate_limit': rate_limit,
                    'label': key_data.get('label', '')
                }
            })
        elif resp.status_code == 401:
            return jsonify({
                'code': 0,
                'msg': 'API Key 无效或已过期',
                'data': None
            })
        else:
            return jsonify({
                'code': 0,
                'msg': f'查询失败: HTTP {resp.status_code}',
                'data': None
            })
            
    except requests.exceptions.Timeout:
        return jsonify({
            'code': 0,
            'msg': '请求超时，请检查网络连接',
            'data': None
        })
    except Exception as e:
        logger.error(f"Get OpenRouter balance failed: {e}")
        return jsonify({
            'code': 0,
            'msg': f'查询失败: {str(e)}',
            'data': None
        })


@settings_blp.route('/test-connection', methods=['POST'])
@login_required
@admin_required
def test_connection():
    """Test third-party API connectivity (admin only)."""
    try:
        data = request.get_json()
        service = data.get('service')
        
        if service == 'openrouter':
            from app.services.llm import LLMService
            llm = LLMService()
            ok, detail = llm.test_connection()
            return jsonify({'code': 1 if ok else 0, 'msg': detail})
        
        elif service == 'finnhub':
            import requests
            api_key = data.get('api_key') or os.getenv('FINNHUB_API_KEY')
            if not api_key:
                return jsonify({'code': 0, 'msg': 'API key is not configured'})
            resp = requests.get(
                f'https://finnhub.io/api/v1/quote?symbol=AAPL&token={api_key}',
                timeout=10
            )
            if resp.status_code == 200:
                return jsonify({'code': 1, 'msg': 'Finnhub connection successful'})
            else:
                return jsonify({'code': 0, 'msg': f'Finnhub connection failed: {resp.status_code}'})
        
        return jsonify({'code': 0, 'msg': 'Unknown service'})
    
    except Exception as e:
        # The Finnhub endpoint carries the key as a query parameter, and requests
        # embeds the URL in exception text, so scrub before logging/returning it.
        logger.error(f"Connection test failed: {redact_secrets(e)}")
        return jsonify({'code': 0, 'msg': f'Test failed: {redact_secrets(e)}'})

# openapi-compat: legacy import name
settings_bp = settings_blp

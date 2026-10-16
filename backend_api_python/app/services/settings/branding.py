"""Branding and public app metadata settings."""

from __future__ import annotations

import os
from typing import Dict, List


BRAND_DEFAULTS = {
    "app_name": "SharkQuant",
    "copyright": "© 2025-2026 SharkQuant. All rights reserved.",
    "contact_email": "support@sharkv2.com",
    "contact_support_url": "https://t.me/sharkquant_support",
    "contact_feature_request_url": "",
    "contact_live_chat_url": "https://t.me/sharkquant_support",
    # Social defaults are empty on purpose: an unconfigured deployment should not
    # point users at another project's accounts.
    "social_github": "",
    "social_x": "",
    "social_discord": "",
    "social_telegram": "",
    "social_youtube": "",
}


def build_brand_config(app_version: str) -> Dict[str, object]:
    """Build public branding, legal, social, and mobile metadata."""
    social_accounts: List[Dict[str, str]] = []
    for name, icon, env_key, default_key in _social_specs():
        url = brand_env(env_key, default_key)
        if url:
            social_accounts.append({"name": name, "icon": icon, "url": url})

    return {
        "app_name": brand_env("BRAND_APP_NAME", "app_name"),
        "app_version": app_version,
        "copyright": brand_env("BRAND_COPYRIGHT", "copyright"),
        "logos": {
            "light": brand_env("BRAND_LOGO_LIGHT_URL"),
            "dark": brand_env("BRAND_LOGO_DARK_URL"),
            "collapsed": brand_env("BRAND_LOGO_COLLAPSED_URL"),
            "favicon": brand_env("BRAND_FAVICON_URL"),
        },
        "contact": {
            "email": brand_env("BRAND_CONTACT_EMAIL", "contact_email"),
            "support_url": brand_env("BRAND_CONTACT_SUPPORT_URL", "contact_support_url"),
            "feature_request_url": brand_env(
                "BRAND_CONTACT_FEATURE_REQUEST_URL",
                "contact_feature_request_url",
            ),
            "live_chat_url": brand_env("BRAND_CONTACT_LIVE_CHAT_URL", "contact_live_chat_url"),
        },
        "social_accounts": social_accounts,
        "legal": {
            "user_agreement_url": brand_env("BRAND_LEGAL_USER_AGREEMENT_URL"),
            "user_agreement_text": brand_env("BRAND_LEGAL_USER_AGREEMENT_TEXT"),
            "privacy_policy_url": brand_env("BRAND_LEGAL_PRIVACY_POLICY_URL"),
            "privacy_policy_text": brand_env("BRAND_LEGAL_PRIVACY_POLICY_TEXT"),
        },
        "mobile_app": {
            "latest_version": brand_env("MOBILE_APP_LATEST_VERSION"),
            "download_url": brand_env("MOBILE_APP_DOWNLOAD_URL"),
        },
    }


def brand_env(name: str, default: str = "") -> str:
    """Read a BRAND_* env var and fall back to the bundled default.

    A variable that is present but empty is an explicit "no value / hide"
    (the .env template documents "leave empty to hide"); only a completely
    unset variable falls back to the bundled default. The previous
    implementation treated empty as unset, which made it impossible to hide
    the default social icons / contact links on a rebranded deployment.
    """
    raw = os.getenv(name)
    if raw is None:
        return BRAND_DEFAULTS.get(default, "")
    return raw.strip()


def _social_specs():
    return [
        ("GitHub", "github", "BRAND_SOCIAL_GITHUB", "social_github"),
        ("X", "x", "BRAND_SOCIAL_X", "social_x"),
        ("Discord", "discord", "BRAND_SOCIAL_DISCORD", "social_discord"),
        ("Telegram", "telegram", "BRAND_SOCIAL_TELEGRAM", "social_telegram"),
        ("YouTube", "youtube", "BRAND_SOCIAL_YOUTUBE", "social_youtube"),
    ]

from app.routes.script_source_routes import _attach_v2_manifest, _rejected_source_response
from app.services.strategy_v2 import StrategyV2ContractError


def test_rejected_source_returns_400_with_localizable_key_and_detail(app):
    """A script the compiler refuses is a 400 the client can localize."""
    with app.test_request_context():
        response, status = _rejected_source_response(
            StrategyV2ContractError("strategyV2.initializeRequired")
        )
        payload = response.get_json()

    assert status == 400
    assert payload["code"] == 0
    assert payload["msg"] == "strategyV2.compileFailed"
    assert payload["data"]["error_type"] == "COMPILE_FAILED"
    assert payload["data"]["detail"] == "strategyV2.initializeRequired"


def test_rejected_source_keeps_the_compiler_reason_for_syntax_errors(app):
    with app.test_request_context():
        response, status = _rejected_source_response(
            ValueError("Unsafe code rejected: Code syntax error")
        )
        payload = response.get_json()

    assert status == 400
    assert payload["msg"] == "strategyV2.compileFailed"
    assert payload["data"]["detail"] == "Unsafe code rejected: Code syntax error"


def test_v2_portfolio_source_is_classified_from_compiled_manifest():
    payload = _attach_v2_manifest({
        "asset_type": "script",
        "code": """
def initialize(context):
    context.set_universe(pool="sp500")
    context.subscribe(frequency="1d")

def handle_data(context, data):
    for symbol in get_universe_stocks():
        order_target_percent(symbol, 0.0)
""",
    })

    assert payload["asset_type"] == "portfolio_strategy"
    assert payload["metadata"]["strategy_manifest"]["strategyType"] == "portfolio"
    assert "apiVersion" not in payload["metadata"]
    assert "api_version" not in payload["metadata"]


def test_v2_cta_source_is_classified_from_compiled_manifest():
    payload = _attach_v2_manifest({
        "asset_type": "portfolio_strategy",
        "code": """
def initialize(context):
    context.set_universe(["USStock:SPY"])
    context.subscribe(frequency="1d")

def handle_data(context, data):
    order_target_percent("USStock:SPY", 1.0)
""",
    })

    assert payload["asset_type"] == "script"
    assert payload["metadata"]["strategy_manifest"]["strategyType"] == "cta"

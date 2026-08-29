import pytest

from app.services.pricing import (
    TokenUsage,
    calculate_token_cost,
)


def test_token_cost_calculation():
    usage = TokenUsage(
        input_tokens=1000,
        cached_input_tokens=200,
        output_tokens=500,
        reasoning_tokens=100,
    )

    cost = calculate_token_cost(usage)

    assert cost == 3250


def test_cached_tokens_cannot_exceed_input_tokens():
    usage = TokenUsage(
        input_tokens=100,
        cached_input_tokens=200,
        output_tokens=0,
        reasoning_tokens=0,
    )

    with pytest.raises(ValueError):
        calculate_token_cost(usage)


def test_negative_tokens_are_rejected():
    usage = TokenUsage(
        input_tokens=-1,
        cached_input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
    )

    with pytest.raises(ValueError):
        calculate_token_cost(usage)


def test_pricing_profile_is_pinned_to_integer_micro_units():
    from app.services.pricing import (
        CACHED_INPUT_PRICE_PER_MILLION,
        INPUT_PRICE_PER_MILLION,
        MICRO_UNITS_PER_USD,
        OUTPUT_PRICE_PER_MILLION,
        PRICING_CURRENCY,
        PRICING_PROFILE,
    )

    assert PRICING_PROFILE == "capstone-v1"
    assert PRICING_CURRENCY == "USD"
    assert MICRO_UNITS_PER_USD == 1_000_000

    assert INPUT_PRICE_PER_MILLION == 1_000_000
    assert CACHED_INPUT_PRICE_PER_MILLION == 250_000
    assert OUTPUT_PRICE_PER_MILLION == 4_000_000

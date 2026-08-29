from dataclasses import dataclass


# Cost values are integer micro-units per 1,000,000 tokens.
# These are pinned demo pricing constants for the capstone.
INPUT_PRICE_PER_MILLION = 1_000_000
CACHED_INPUT_PRICE_PER_MILLION = 250_000
OUTPUT_PRICE_PER_MILLION = 4_000_000


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int


def calculate_token_cost(usage: TokenUsage) -> int:
    """
    Return cost in integer micro-units.

    Rules:
    - Cached input is priced separately at a cheaper rate.
    - Reasoning tokens are billed at the output-token rate.
    - No floating-point arithmetic is used.
    """

    values = (
        usage.input_tokens,
        usage.cached_input_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
    )

    if any(value < 0 for value in values):
        raise ValueError("Token counts cannot be negative")

    fresh_input_tokens = usage.input_tokens - usage.cached_input_tokens

    if fresh_input_tokens < 0:
        raise ValueError(
            "cached_input_tokens cannot exceed input_tokens"
        )

    total_output_tokens = (
        usage.output_tokens + usage.reasoning_tokens
    )

    input_cost = (
        fresh_input_tokens * INPUT_PRICE_PER_MILLION
    ) // 1_000_000

    cached_input_cost = (
        usage.cached_input_tokens
        * CACHED_INPUT_PRICE_PER_MILLION
    ) // 1_000_000

    output_cost = (
        total_output_tokens * OUTPUT_PRICE_PER_MILLION
    ) // 1_000_000

    return input_cost + cached_input_cost + output_cost

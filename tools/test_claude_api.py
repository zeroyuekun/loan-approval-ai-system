#!/usr/bin/env python3
"""Test Claude API connectivity and verify the API key works.

Loads the ANTHROPIC_API_KEY from the .env file and sends a simple
test message to verify access to the Claude API.

Usage:
    python tools/test_claude_api.py
    python tools/test_claude_api.py --env-path /path/to/.env
"""

import argparse
import os
import sys
import time


def load_env(env_path: str) -> None:
    """Load environment variables from a .env file.

    Args:
        env_path: Path to the .env file.
    """
    if not os.path.exists(env_path):
        print(f"WARNING: .env file not found at {env_path}")
        print("Looking for ANTHROPIC_API_KEY in environment variables...")
        return

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                os.environ.setdefault(key, value)


def test_api_connection(api_key: str) -> bool:
    """Send a test message to the Claude API.

    Args:
        api_key: Anthropic API key.

    Returns:
        True if the test succeeds, False otherwise.
    """
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package is not installed.")
        print("Install with: pip install anthropic")
        return False

    print("Connecting to Claude API...")
    start_time = time.time()

    try:
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": "Respond with exactly: 'API connection successful.' Nothing else.",
                }
            ],
        )

        elapsed = time.time() - start_time
        response_text = response.content[0].text

        print(f"\nSUCCESS: Claude API is accessible.")
        print(f"  Model:    {response.model}")
        print(f"  Response: {response_text}")
        print(f"  Latency:  {elapsed:.2f}s")
        print(f"  Usage:    {response.usage.input_tokens} input tokens, "
              f"{response.usage.output_tokens} output tokens")
        return True

    except anthropic.AuthenticationError:
        print("\nFAILED: Authentication error. Your API key is invalid or expired.")
        print("Get a valid key from: https://console.anthropic.com/")
        return False

    except anthropic.RateLimitError:
        print("\nFAILED: Rate limited. Too many requests. Wait and try again.")
        return False

    except anthropic.APIConnectionError as e:
        print(f"\nFAILED: Could not connect to the API. Check your network.")
        print(f"  Error: {e}")
        return False

    except anthropic.APIError as e:
        print(f"\nFAILED: API error occurred.")
        print(f"  Status: {e.status_code}")
        print(f"  Error:  {e.message}")
        return False

    except Exception as e:
        print(f"\nFAILED: Unexpected error: {type(e).__name__}: {e}")
        return False


def main():
    """Parse arguments and test Claude API connectivity."""
    parser = argparse.ArgumentParser(
        description="Test Claude API connectivity and verify API key."
    )
    parser.add_argument(
        "--env-path",
        type=str,
        default=".env",
        help="Path to .env file (default: .env)",
    )
    args = parser.parse_args()

    # Load environment
    load_env(args.env_path)

    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found.")
        print("Set it in your .env file or as an environment variable.")
        sys.exit(1)

    if api_key in ("sk-ant-your-key-here", "change-me"):
        print("ERROR: ANTHROPIC_API_KEY is still set to the placeholder value.")
        print("Update it with your real API key in .env")
        sys.exit(1)

    # Mask key for display
    masked = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 14 else "***"
    print(f"Using API key: {masked}")

    # Test connection
    success = test_api_connection(api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

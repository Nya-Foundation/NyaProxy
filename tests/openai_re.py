import os
import json
import httpx
import asyncio
from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APIStatusError

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Your proxy or compatible endpoint URL
PROXY_API_URL = os.getenv("OPENAI_API_URL", "http://127.0.0.1:8080/api/gemini")
# Official OpenAI API URL (optional, for direct comparison)
OFFICIAL_OPENAI_URL = "https://api.openai.com/v1"


# --- Request Payload ---
def get_payload_dict():
    """Returns the request payload as a dictionary."""
    return {
        "model": "gemini-2.5-pro-exp-03-25",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me a short story about a curious robot."},
        ],
        "max_tokens": 2000,
        "temperature": 0.7,
    }


# --- HTTPX Client Setup ---
headers = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "Content-Type": "application/json",
    # Accept header might vary based on stream/non-stream
}
timeout = httpx.Timeout(5.0, read=60.0)  # Increased read timeout for generation

# --- OpenAI SDK Client Setup ---
# Client for your Proxy URL
proxy_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=PROXY_API_URL,  # SDK needs base path, e.g., http://127.0.0.1:8080/api/gemini
)

# Client for official OpenAI API (optional, requires OPENAI_API_KEY to be valid for OpenAI)
# official_client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def fetch_raw_non_stream(url: str):
    """Fetches non-streaming response using HTTPX."""
    print(f"\n--- Fetching RAW Non-Stream from: {url} ---")
    payload = get_payload_dict()
    payload["stream"] = False
    current_headers = headers.copy()
    current_headers["Accept"] = "application/json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            url = url.rstrip("/") + "/chat/completions"  # Ensure correct endpoint
            response = await client.post(url, headers=current_headers, json=payload)
            response.raise_for_status()
            content = await response.aread()
            print(f"Status Code: {response.status_code}")
            print("Raw Response Body:")
            # Try to pretty-print if JSON, otherwise print raw
            try:
                parsed_json = json.loads(content)
                print(json.dumps(parsed_json, indent=2))
            except json.JSONDecodeError:
                print(repr(content.decode()))
        except httpx.HTTPStatusError as e:
            print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"Request Error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            print("--- Raw Non-Stream End ---")


async def fetch_raw_stream(url: str):
    """Fetches streaming response using HTTPX."""
    print(f"\n--- Fetching RAW Stream from: {url} ---")
    payload = get_payload_dict()
    payload["stream"] = True
    current_headers = headers.copy()
    current_headers["Accept"] = "text/event-stream"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST", url, headers=current_headers, json=payload
            ) as response:
                response.raise_for_status()
                print(f"Status Code: {response.status_code}")
                print("Raw Stream Chunks:")
                async for chunk in response.aiter_text():
                    print(repr(chunk), end="")  # Print raw stream chunks
                print()  # Newline after stream
        except httpx.HTTPStatusError as e:
            print(f"HTTP Error: {e.response.status_code}")
            # Attempt to read error body if available
            try:
                error_body = await e.response.aread()
                print(f"Error Body: {error_body.decode()}")
            except Exception:
                print("(Could not read error body)")
        except httpx.RequestError as e:
            print(f"Request Error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            print("\n--- Raw Stream End ---")


async def fetch_sdk_non_stream(client: AsyncOpenAI, client_name: str):
    """Fetches non-streaming response using OpenAI SDK."""
    print(f"\n--- Fetching SDK Non-Stream ({client_name}) ---")
    payload = get_payload_dict()
    try:
        completion = await client.chat.completions.create(**payload, stream=False)
        print("SDK Response Object:")
        # The SDK returns a Pydantic model, print its dict representation
        print(completion.model_dump_json(indent=2))
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        print(f"OpenAI API Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print(f"--- SDK Non-Stream End ({client_name}) ---")


async def fetch_sdk_stream(client: AsyncOpenAI, client_name: str):
    """Fetches streaming response using OpenAI SDK."""
    print(f"\n--- Fetching SDK Stream ({client_name}) ---")
    payload = get_payload_dict()
    try:
        stream = await client.chat.completions.create(**payload, stream=True)
        print("SDK Stream Chunks:")
        async for chunk in stream:
            # Each chunk is a Pydantic model object
            print(chunk.model_dump_json())  # Print JSON representation of the chunk
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        print(f"OpenAI API Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print(f"\n--- SDK Stream End ({client_name}) ---")


async def main():
    if not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY environment variable not set.")
        return

    # --- Test Proxy Endpoint ---
    print("\n" + "=" * 10 + " Testing Proxy Endpoint " + "=" * 10)
    # await fetch_raw_non_stream(PROXY_API_URL)
    # await fetch_raw_stream(PROXY_API_URL)
    # # await fetch_sdk_non_stream(proxy_client, "Proxy")
    await fetch_sdk_stream(proxy_client, "Proxy")

    # --- Test Official OpenAI Endpoint (Optional) ---
    # print("\n" + "="*10 + " Testing Official OpenAI Endpoint " + "="*10)
    # official_client = AsyncOpenAI(api_key=OPENAI_API_KEY) # Re-init or use globally defined one
    # await fetch_raw_non_stream(OFFICIAL_OPENAI_URL)
    # await fetch_raw_stream(OFFICIAL_OPENAI_URL)
    # await fetch_sdk_non_stream(official_client, "Official")
    # await fetch_sdk_stream(official_client, "Official")


if __name__ == "__main__":
    asyncio.run(main())

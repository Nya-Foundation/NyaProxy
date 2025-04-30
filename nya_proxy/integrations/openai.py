import asyncio
import json
import time
import traceback
from typing import AsyncGenerator


def openai_chat_format(model, content, create_at=None):
    """ """

    if not create_at:
        create_at = int(time.time())

    res = {
        "object": "chat.completion",
        "created": create_at,
        "model": model,
        "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }

    # Fix the syntax error by properly handling the string literal
    done_marker = "[DONE]"
    return "data: " + json.dumps(res if content else done_marker) + "\n\n"


def openai_stream_chunk(
    model="unknown-model",
    chunk: str = None,
    create_at=None,
    finish_reason=None,
    is_first_chunk: bool = False,  # Flag to indicate the first chunk
):
    """
    Formats a chunk for OpenAI SSE stream, matching upstream format closely. Returns a string.
    """
    if not create_at:
        create_at = int(time.time())

    # Handle the [DONE] marker separately
    if chunk is None and finish_reason is None:
        # This case should ideally not be hit if called correctly from simulator,
        # but kept for safety. The simulator should send finish_reason or [DONE] explicitly.
        return "data: [DONE]\n\n"

    delta = {}
    # Add role only to the first chunk's delta
    if is_first_chunk:
        delta["role"] = "assistant"

    # Add content if present
    if chunk is not None:
        delta["content"] = chunk

    # Add finish_reason to the delta if present (typically only on the last chunk)
    if finish_reason:
        delta["finish_reason"] = finish_reason

    # If delta is empty, we shouldn't send a chunk (unless it's the very first one needing a role?)
    # Let's assume delta will have content or finish_reason if this function is called.
    if not delta:
        # Avoid sending empty delta chunks unless absolutely necessary (e.g., maybe first chunk only has role?)
        # For simulation, we expect content or finish_reason.
        # If called with chunk=None, finish_reason=None, is_first_chunk=True, delta would be {'role': 'assistant'}
        # If called with chunk=None, finish_reason='stop', is_first_chunk=False, delta would be {'finish_reason': 'stop'}
        # If called with chunk=None, finish_reason='stop', is_first_chunk=True, delta would be {'role': 'assistant', 'finish_reason': 'stop'}
        pass  # Let it proceed if delta has role or finish_reason

    formatted_chunk = {
        "object": "chat.completion.chunk",
        "created": create_at,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                # Finish reason is now inside delta
            }
        ],
    }

    json_str = json.dumps(formatted_chunk)
    return f"data: {json_str}\n\n"


async def simulate_stream_from_completion(
    full_content: bytes,
    chunk_size_bytes: int = 20,
    delay_seconds: float = 0.01,
    init_delay_seconds: float = 0.0,
) -> AsyncGenerator[bytes, None]:
    """
    Simulates a streaming response from a full OpenAI chat completion response.

    Args:
        full_content: The complete response bytes from the upstream API
        chunk_size_bytes: Size of each chunk in bytes (applied to the content string)
        delay_seconds: Delay between chunks in seconds
        init_delay_seconds: Initial delay before starting to stream

    Yields:
        Properly formatted SSE chunks in OpenAI stream format, encoded as bytes.
    """
    if init_delay_seconds > 0:
        await asyncio.sleep(init_delay_seconds)

    create_at = int(time.time())
    first_chunk_sent = False  # Track if the first content chunk has been sent

    try:
        response_data = json.loads(full_content)
        model = response_data.get("model", "unknown-model")
        choice = response_data["choices"][0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")
        complete_content = message.get("content")

    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        error_message = f"Error: Could not parse upstream response or missing expected fields. Details: {e}"
        # Send error chunk - treat as the first and only chunk for role/finish_reason placement
        error_chunk_str = openai_stream_chunk(
            model="unknown-model",
            chunk=error_message,
            create_at=create_at,
            finish_reason="error",
            is_first_chunk=True,  # It's the first chunk in this error stream
        )
        print(
            f"Error processing upstream API response: {e}, content: {full_content}, traceback: {traceback.format_exc()}"
        )
        yield error_chunk_str.encode("utf-8")
        yield "data: [DONE]\n\n".encode("utf-8")
        return

    # Handle cases where content might be None or empty
    if complete_content is None or complete_content == "":
        if finish_reason:  # Send a single chunk with role (if first) and finish_reason
            print(f"Simulated stream: No content found, finish_reason: {finish_reason}")
            final_chunk_str = openai_stream_chunk(
                model=model,
                chunk=None,
                create_at=create_at,
                finish_reason=finish_reason,
                is_first_chunk=True,  # It's the first and only chunk
            )
            yield final_chunk_str.encode("utf-8")
        else:
            # If no content and no finish reason (or finish_reason='stop' implicitly), just send DONE
            print(
                f"Simulated stream: No content and no specific finish_reason. Sending DONE."
            )
        yield "data: [DONE]\n\n".encode("utf-8")
        return

    if not isinstance(complete_content, str):
        complete_content = str(complete_content)

    print(
        f"Simulated stream from completion, model: {model}, content length: {len(complete_content)}, finish_reason: {finish_reason}"
    )

    remaining_content = complete_content
    while remaining_content:
        chunk_len = chunk_size_bytes
        next_chunk_str = remaining_content[:chunk_len]
        remaining_content = remaining_content[chunk_len:]

        # Determine if this is the last content chunk
        current_finish_reason = finish_reason if not remaining_content else None

        # Yield the chunk
        chunk_str = openai_stream_chunk(
            model=model,
            chunk=next_chunk_str,
            create_at=create_at,
            finish_reason=current_finish_reason,
            is_first_chunk=not first_chunk_sent,  # Pass the flag
        )
        yield chunk_str.encode("utf-8")
        first_chunk_sent = True  # Mark first chunk as sent

        if remaining_content and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    # If the loop finished but finish_reason wasn't sent with the last content chunk
    # (e.g., if finish_reason was None initially, or content was empty string)
    # This check might be redundant now with the logic above, but ensures termination signal if needed.
    # However, the standard is to send finish_reason with the *last* chunk containing data,
    # or a separate chunk if there was no data. The logic above should cover this.

    # Send the final [DONE] marker
    yield "data: [DONE]\n\n".encode("utf-8")

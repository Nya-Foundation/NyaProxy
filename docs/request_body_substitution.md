# Request Body Substitution

## Overview

Request Body Substitution allows you to dynamically modify JSON payloads sent to APIs using. This powerful feature lets you:

- **Set** new or existing fields in requests
- **Remove** fields entirely from requests

This is particularly useful for normalizing requests across different clients, enforcing constraints, adding default values, or adapting requests to meet specific API requirements.

## Configuration

Request Body Substitution is configured in the `request_body_substitution` section of your configuration file:

```yaml
request_body_substitution:
  enabled: true  # Set to true to enable substitution
  rules:         # List of substitution rules to apply
    - name: "Rule name"              # Human-readable name for the rule
      operation: "set|remove"        # Type of operation to perform
      path: "path.to.field"     # JMESPath expression targeting the field
      value: "new_value"             # Value to set (not needed for remove)
      conditions:                    # Optional conditions that must be met for rule to apply
        - field: "path.to.field"     # JMESPath to field to evaluate
          operator: "eq|ne|gt|lt|ge|le|in|nin|like|nlike|contains|ncontains|between|nbetween|startswith|endswith|exists|nexists|isnull|notnull"
          value: "target_value"      # Value to compare against (if needed)
```

### Operations

- **set**: Sets a field value (creates it if it doesn't exist)
- **remove**: Deletes a field from the request

### Conditions and Operators

Conditions determine whether a rule is applied based on the value of a field. NyaProxy supports a comprehensive set of operators:

| Operator | Meaning | Notes |
|----------|---------|-------|
| eq | Equal to | (==) |
| ne | Not equal to | (!=) |
| gt | Greater than | (>) |
| lt | Less than | (<) |
| ge | Greater than or equal to | (>=) |
| le | Less than or equal to | (<=) |
| in | Value is in a list/collection | Membership check |
| nin | Value is not in a list | "not in" |
| like | String matches pattern | SQL LIKE operator with wildcards (%) |
| nlike | String does not match pattern | Negative of "like" |
| contains | Collection contains value | For arrays, strings, objects |
| ncontains | Collection does not contain value | Negative of contains |
| between | Value is between two values | Inclusive range check [min, max] |
| nbetween | Value is not between two values | Outside the range |
| startswith | String starts with pattern | String prefix match |
| endswith | String ends with pattern | String suffix match |
| exists | Field exists | Field is present in request |
| nexists | Field does not exist | Field is absent from request |
| isnull | Field is NULL | Field exists but has null value |
| notnull | Field is not NULL | Field exists with non-null value |

### JMESPath Syntax

JMESPath is a query language for JSON. Basic syntax:

- Root object is implicitly referenced (no `$` prefix needed)
- `property` - Child property
- `property.subproperty` - Nested property access
- `[index]` - Array index (e.g., `messages[0]`)
- `*` - Wildcard for properties or array elements
- `[*]` - All elements in an array
- `[]` - Flattened array projections (e.g., `messages[].content`)
- `property[*].subproperty` - Access a property on each item in an array

## Examples

### Example 1: Setting Default Model

```yaml
rules:
  - name: "Default to GPT-4"
    operation: set
    path: "model"
    value: "gpt-4"
    conditions:
      - field: "model"
        operator: "nexists"
```

This rule sets a `model` field with the value `gpt-4` if the request doesn't already have a model specified.

### Example 2: Cap Temperature

```yaml
rules:
  - name: "Cap temperature at 0.7"
    operation: set
    path: "temperature"
    value: 0.7
    conditions:
      - field: "temperature"
        operator: "gt"
        value: 0.7
```

This rule limits the temperature parameter to 0.7 if the client requests a higher value.

### Example 3: Force Non-Streaming Responses

```yaml
rules:
  - name: "Disable streaming"
    operation: remove
    path: "stream"
    conditions:
      - field: "stream"
        operator: "eq"
        value: true
```

This rule removes the `stream` parameter when it's set to `true`, forcing synchronous responses.

### Example 4: Add System Message

```yaml
rules:
  - name: "Prepend system message"
    operation: set
    path: "messages[0]"
    value: {"role": "system", "content": "You are a helpful assistant."}
    conditions:
      - field: "messages[0].role"
        operator: "ne"
        value: "system"
```

This rule adds a system message at the beginning of the messages array if the first message is not already a system message.

### Example 5: Transform OpenAI to Anthropic Format

```yaml
rules:
  - name: "Downgrade Anthropic model"
    operation: set
    path: "model"  # Empty string for root object
    value: "claude-3-5-sonnet-latest"
    conditions:
      - field: "model"
        operator: "contains"
        value: "claude-3-7"
```

This complex rule transforms an entire OpenAI API request to match Anthropic's format when the model contains "gpt-4".

### Example 6: Use Advanced Operators

```yaml
rules:
  - name: "Set max tokens for long queries"
    operation: set
    path: "max_tokens"
    value: 1000
    conditions:
      - field: "messages[].content"
        operator: "like"
        value: "%summarize%"
      - field: "max_tokens"
        operator: "nexists"

  - name: "Add custom system prompt for data analysis requests"
    operation: set
    path: "messages[0]"
    value: {"role": "system", "content": "You are a data analysis expert."}
    conditions:
      - field: "messages[].content"
        operator: "like"
        value: "%analyze%data%"
      - field: "messages[0].role"
        operator: "ne"
        value: "system"

  - name: "Set temperature range for creative tasks"
    operation: set
    path: "temperature"
    value: 0.8
    conditions:
      - field: "messages[].content"
        operator: "like"
        value: "%creative%"
      - field: "temperature"
        operator: "nbetween"
        value: [0.7, 0.9]
```

These examples show how to use advanced operators like `like` for pattern matching and `nbetween` for range checking.

## Value References

You can reference values from the original request body using the `${{path}}` syntax:

### Direct References

Use `${{path}}` to reference a value directly from the original request:

```yaml
rules:
  - name: "Preserve original messages when changing model"
    operation: set
    path: ""  # Empty string for root object
    value: {
      "model": "claude-3-opus-20240229",
      "messages": "${{messages}}",  # Direct reference to messages field
      "temperature": "${{temperature}}"
    }
    conditions:
      - field: "model"
        operator: "contains"
        value: "gpt-4"
```

### String Interpolation

Embed references within strings using the same `${{path}}` syntax:

```yaml
rules:
  - name: "Add a custom system message with the original model name"
    operation: set
    path: "messages[0]"
    value: {
      "role": "system", 
      "content": "You are running on ${{model}} and should optimize accordingly."
    }
    conditions:
      - field: "messages[0].role"
        operator: "ne"
        value: "system"
```

### Multiple References

Combine multiple references in a single template:

```yaml
rules:
  - name: "Add metadata field with request info"
    operation: set
    path: "metadata"
    value: {
      "original_model": "${{model}}",
      "summary": "Request with ${{length(messages)}} messages using ${{model}}",
      "prompt_tokens_estimate": "${{sum(messages[].content.length)}}"
    }
```

### Nested References

Access nested fields and array elements:

```yaml
rules:
  - name: "Extract first user message as system instruction"
    operation: set
    path: "messages[0]"
    value: {
      "role": "system",
      "content": "Follow these instructions: ${{messages[?role=='user'][0].content}}"
    }
    conditions:
      - field: "messages[0].role" 
        operator: "ne"
        value: "system"
```

### Reference Handling Logic

- If a reference points to a non-existent path, it resolves to `null`
- References used in string interpolation:
  - Missing values are replaced with an empty string
  - Objects and arrays are automatically JSON-serialized
  - Simple values are converted to strings

## Use Cases

- **Standardization**: Ensure all requests follow consistent patterns
- **Security**: Remove sensitive information from requests
- **Compatibility**: Transform requests to work with different APIs
- **Defaults**: Add missing parameters for proper API functioning
- **Rate limiting**: Reduce token usage by constraining certain parameters
- **Prompt engineering**: Automatically enhance prompts with predefined context

## Full Configuration Example

```yaml
request_body_substitution:
  enabled: true
  rules:
    - name: "Default to GPT-4"
      operation: set
      path: "model"
      value: "gpt-4"
      conditions:
        - field: "model"
          operator: "nexists"

    - name: "Cap temperature"
      operation: set
      path: "temperature"
      value: 0.7
      conditions:
        - field: "temperature"
          operator: "gt"
          value: 0.7

    - name: "Remove stream parameter"
      operation: remove
      path: "stream"
      conditions:
        - field: "stream"
          operator: "eq"
          value: true

    - name: "Add system message"
      operation: set
      path: "messages[0]"
      value: {"role": "system", "content": "You are a helpful assistant."}
      conditions:
        - field: "messages[0].role"
          operator: "ne"
          value: "system"

    - name: "Set reasonable max_tokens for claude models"
      operation: set
      path: "max_tokens"
      value: 4000
      conditions:
        - field: "model"
          operator: "contains"
          value: "claude"
        - field: "max_tokens"
          operator: "nexists"

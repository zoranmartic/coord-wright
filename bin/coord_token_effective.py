def effective_tokens(agent, input_tokens, output_tokens, cache_read, cache_create=0):
    agent = str(agent).strip().lower()
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    cache_read = int(cache_read or 0)
    cache_create = int(cache_create or 0)

    if agent == "claude":
        return input_tokens + 5 * output_tokens + cache_read // 10 + (cache_create * 5) // 4
    if agent == "codex":
        return input_tokens + 6 * output_tokens + cache_read // 10
    raise ValueError(f"unsupported agent: {agent}")

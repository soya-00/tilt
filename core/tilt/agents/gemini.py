"""Gemini provider.

The ``google-genai`` SDK is an optional dependency so the core installs and
tests cleanly without it. Model IDs come from configuration rather than being
hardcoded — Flash releases move quickly, and a scheduled job failing at 3am
because a constant went stale is a failure mode worth designing out.
"""

from __future__ import annotations

import asyncio

from tilt.agents.base import AgentError, Completion, Pricing, Reference, estimate_tokens

# USD per million tokens, keyed by model family prefix.
PRICING: dict[str, Pricing] = {
    "gemini-3.6-flash": Pricing(input_per_m=1.50, output_per_m=7.50),
    "gemini-3.5-flash": Pricing(input_per_m=1.50, output_per_m=9.00),
}
DEFAULT_PRICING = Pricing(input_per_m=1.50, output_per_m=7.50)


def pricing_for(model: str) -> Pricing:
    for prefix, price in PRICING.items():
        if model.startswith(prefix):
            return price
    return DEFAULT_PRICING


class GeminiProvider:
    name = "gemini"

    # It can open a page and watch a video itself, which is why neither has a
    # scraper or a caption-stitcher on this side.
    follows_references = True

    def __init__(self, api_key: str, model: str, fallback_model: str | None = None) -> None:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise AgentError(
                "google-genai is not installed. Install the 'gemini' extra to use this provider."
            ) from exc
        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.fallback_model = fallback_model
        self.pricing = pricing_for(model)

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        reference: Reference | None = None,
    ) -> Completion:
        for candidate in filter(None, (self.model, self.fallback_model)):
            try:
                return await self._generate(candidate, prompt, system, reference)
            except Exception as exc:  # noqa: BLE001 - fall back, then surface
                if candidate == (self.fallback_model or self.model):
                    raise AgentError(f"Gemini request failed: {exc}") from exc
        raise AgentError("No Gemini model configured.")

    def _contents(self, prompt: str, reference: Reference | None):
        """The prompt, plus the video the model should watch alongside it.

        A YouTube URL goes in as ``FileData`` rather than as a link in the
        text: that is what makes the model actually watch it instead of
        reasoning about the URL. Articles are not attached this way — they
        travel as a tool, below.
        """
        from google.genai import types

        if reference is None or reference.kind != "video":
            return prompt
        return types.Content(
            role="user",
            parts=[
                types.Part(file_data=types.FileData(file_uri=reference.url)),
                types.Part(text=prompt),
            ],
        )

    def _config(self, system: str | None, reference: Reference | None):
        from google.genai import types

        tools = None
        if reference is not None and reference.kind == "article":
            # url_context lets the model fetch and read the page itself. The
            # alternative is a scraper here, which would need maintaining
            # against every site that changes its markup.
            tools = [types.Tool(url_context=types.UrlContext())]

        if system is None and tools is None:
            return None
        return types.GenerateContentConfig(system_instruction=system, tools=tools)

    async def _generate(
        self, model: str, prompt: str, system: str | None, reference: Reference | None = None
    ) -> Completion:
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=model,
            contents=self._contents(prompt, reference),
            config=self._config(system, reference),
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise AgentError("Gemini returned an empty response.")

        usage = getattr(response, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", None) or estimate_tokens(prompt)
        tokens_out = getattr(usage, "candidates_token_count", None) or estimate_tokens(text)

        self.pricing = pricing_for(model)
        return Completion(text=text, model=model, tokens_in=tokens_in, tokens_out=tokens_out)

"""Turn retrieved entities + a question into a CITED answer.

v0.1 runs on Groq's free tier (a Llama model). The decided stack is the Claude
API — this whole file is the only thing that changes between providers, so when
the team funds Anthropic access you swap the client here and nothing else moves.

The non-negotiable rules from CLAUDE.md are enforced in the system prompt:
  - Every fact must cite the entity it came from.
  - If the retrieved context doesn't answer the question, SAY SO — never guess.
    A confidently-wrong answer destroys the team's trust in the map.
"""

import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# Free, fast, capable enough for cited RAG answers. Browse other options at
# https://console.groq.com/docs/models and change this one line to switch.
MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 2048

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env.")
        _client = Groq()  # reads GROQ_API_KEY from env
    return _client


SYSTEM_PROMPT = """\
You are the UM6P Global Hubs research assistant. You answer questions about a \
curated map of US institutions, national labs, funders, ventures, and events \
that the team tracks for partnership-building.

You will be given a numbered list of SOURCE entities retrieved from the map, \
followed by a question. Follow these rules exactly:

1. Answer ONLY from the provided sources. Do not use outside knowledge.
2. Cite the source for every fact, by the entity's name, like: \
(source: Savannah River National Laboratory).
3. If the sources do not contain the answer, say plainly: "The map doesn't \
contain enough information to answer this." Do not guess or fabricate.
4. Be concise and factual. Lead with the direct answer, then supporting detail.
5. When several entities are relevant, group or list them clearly.
"""


def _format_context(entities: list[dict]) -> str:
    """Render retrieved entities into a numbered block for the prompt."""
    blocks = []
    for i, e in enumerate(entities, 1):
        blocks.append(f"[SOURCE {i}] {e['name']} ({e['entity_type']})\n"
                      f"{e['doc_text']}")
    return "\n\n".join(blocks)


def _build_messages(question: str, entities: list[dict]) -> list[dict]:
    context = _format_context(entities) if entities else "(no sources retrieved)"
    user_content = f"SOURCES:\n\n{context}\n\n---\n\nQUESTION: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def answer_question(question: str, entities: list[dict]) -> str:
    """Non-streaming: return the full cited answer as a string."""
    resp = _get_client().chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=_build_messages(question, entities),
    )
    return resp.choices[0].message.content


def stream_answer(question: str, entities: list[dict]):
    """Streaming: yield answer text chunks as they arrive (used by the UI)."""
    stream = _get_client().chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=_build_messages(question, entities),
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


if __name__ == "__main__":
    import sys
    from src.retrieve import retrieve

    q = " ".join(sys.argv[1:]) or "Who works on phosphogypsum?"
    hits = retrieve(q)
    print(f"Q: {q}\n")
    print(answer_question(q, hits))
    print("\nSources:", ", ".join(h["name"] for h in hits))

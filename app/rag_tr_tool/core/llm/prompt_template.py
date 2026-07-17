_TEMPLATE = """\
You are a helpful assistant.

Answer the question using ONLY the provided context.

If the answer cannot be found in the context,
respond with "I don't know".

Context:
{context}

Question:
{question}

Answer:"""


def build_prompt(context: str, question: str) -> str:
    return _TEMPLATE.format(context=context, question=question)

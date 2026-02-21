from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class PromptsService:
    # ---------------------------------------------------------------------------
    # System prompts — static strings, reference directly as class attributes
    # ---------------------------------------------------------------------------

    SUMMARIZE_SYSTEM: str = (
        "You are a senior software engineer analysing a GitHub repository.\n"
        "Your task is to produce a structured JSON summary of the repository.\n\n"
        "Rules:\n"
        "- Output ONLY valid JSON — no markdown fences, no extra text.\n"
        "- Use exactly these three keys:\n"
        '    "summary"      — 2-4 sentence plain-English description of what the project does\n'
        '    "technologies" — JSON array of strings listing main languages, frameworks, and libraries\n'
        '    "structure"    — 1-2 sentences describing the directory layout and how the code is organised\n'
        "- Be specific and factual; do not invent details not present in the provided context.\n"
        "- If a field cannot be determined from the context, use an empty string or empty array."
    )

    MAP_SYSTEM: str = (
        "You are a senior software engineer reading a partial snapshot of a large repository.\n"
        "Extract concise, factual notes that will later be merged with notes from other chunks.\n\n"
        "Output ONLY valid JSON with exactly these keys:\n"
        '    "purpose"      — what this chunk of code does (1-2 sentences)\n'
        '    "technologies" — array of languages, frameworks, or libraries observed in this chunk\n'
        '    "structure"    — brief note on how the files in this chunk are organised\n\n'
        "Do not speculate beyond what you can see. Keep each value short."
    )

    REDUCE_SYSTEM: str = (
        "You are a senior software engineer synthesising partial analysis notes about a repository.\n"
        "You will receive a list of JSON notes, each produced from a different chunk of the codebase.\n"
        "Combine them into one coherent, accurate summary.\n\n"
        "Output ONLY valid JSON with exactly these three keys:\n"
        '    "summary"      — 2-4 sentence plain-English description of what the project does\n'
        '    "technologies" — deduplicated JSON array of all technologies mentioned across notes\n'
        '    "structure"    — 1-2 sentences describing the overall directory layout\n\n'
        "Resolve any contradictions by preferring the most specific information. "
        "Do not invent details that are not present in the notes."
    )

    JSON_REPAIR_SYSTEM: str = (
        "You are a JSON repair assistant.\n"
        "You will receive a malformed JSON string and the parse error that was raised.\n"
        "Return ONLY the corrected, valid JSON — no explanation, no markdown fences.\n"
        "Preserve all original content; only fix syntax errors.\n"
        "The corrected JSON must contain exactly these keys: "
        '"summary", "technologies", "structure".'
    )

    # ---------------------------------------------------------------------------
    # User message factories — call these to build dynamic user messages
    # ---------------------------------------------------------------------------

    @staticmethod
    def summarize_user(repo_context: str) -> str:
        return (
            "Here is the repository context. Analyse it and return the JSON summary.\n\n"
            f"{repo_context}"
        )

    @staticmethod
    def map_user(chunk: str) -> str:
        return (
            "Here is a chunk of the repository. Extract structured notes as JSON.\n\n"
            f"{chunk}"
        )

    @staticmethod
    def reduce_user(notes: list[str]) -> str:
        joined = "\n".join(f"- {note}" for note in notes)
        return (
            "Here are the partial analysis notes from each chunk of the repository.\n"
            "Synthesise them into the final JSON summary.\n\n"
            f"{joined}"
        )

    @staticmethod
    def json_repair_user(bad_json: str, error: str) -> str:
        return (
            f"Parse error: {error}\n\n"
            f"Malformed JSON to fix:\n{bad_json}"
        )

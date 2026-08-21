import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is a dev convenience; if it's absent, rely on the ambient
    # environment. Nothing here should hard-fail just because .env can't be read.
    pass

GRIBS_DIR = Path("app/gribs")

jinja_env = Environment(loader=FileSystemLoader("prompts"), trim_blocks=True, lstrip_blocks=True)


def llm_available() -> bool:
    """True only if we can actually run the agent: key set and library installed."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        import pydantic_ai  # noqa: F401
    except ImportError:
        return False
    return True


def build_agent():
    from pydantic_ai import Agent

    return Agent(
        "openai:gpt-4o-mini",
        system_prompt=jinja_env.get_template("system_prompt.j2").render(),
    )


def load_scenarios() -> list[dict]:
    files = json.loads((GRIBS_DIR / "index.json").read_text())
    scenarios = []
    for file in files:
        data = json.loads((GRIBS_DIR / file).read_text())
        speeds = [v["speed_knots"] for v in data["wind_vectors"]]
        scenarios.append({
            "name": file,
            "duration_hours": data["duration_hours"],
            "wind_min": round(min(speeds), 1),
            "wind_avg": round(sum(speeds) / len(speeds), 1),
            "wind_max": round(max(speeds), 1),
        })
    return scenarios


if __name__ == "__main__":
    scenarios = load_scenarios()

    if llm_available():
        prompt = jinja_env.get_template("task_prompt.j2").render(scenarios=scenarios)
        summary = build_agent().run_sync(prompt).output.strip()
    else:
        # No OPENAI_API_KEY (or pydantic-ai not installed): skip the LLM step so
        # the pipeline and GUI still work. index.html handles a missing/placeholder
        # summary gracefully; here we write a truthful placeholder rather than crash.
        summary = "LLM insight disabled (set OPENAI_API_KEY to enable)."
        print("OPENAI_API_KEY not set (or pydantic-ai missing); writing placeholder summary.")

    (GRIBS_DIR / "summary.json").write_text(json.dumps({"summary": summary}, indent=2))
    print("Wrote app/gribs/summary.json")

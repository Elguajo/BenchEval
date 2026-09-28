import hashlib
import json
from pathlib import Path

import yaml

from bencheval.contracts import InstructionBundle, InstructionSource, Scenario


class ScenarioError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    """Refuse duplicate keys instead of silently replacing a declared policy."""


def _mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ScenarioError("YAML keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def digest(value) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def load_scenario(path: Path) -> Scenario:
    try:
        if path.stat().st_size > 1_000_000:
            raise ScenarioError("Scenario exceeds the 1 MB input limit")
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
        return Scenario.model_validate(value)
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as error:
        raise ScenarioError(f"{path}: {error}") from error


def load_instructions(scenario: Scenario, root: Path) -> InstructionBundle:
    root = root.resolve()
    sources = []
    if scenario.instructions.text:
        text = scenario.instructions.text
        sources.append(
            InstructionSource(
                source="inline",
                text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
            )
        )
    seen = set()
    for name in scenario.instructions.files:
        path = (root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(root):
            raise ScenarioError(f"Instruction path escapes scenario root: {name}")
        if path in seen:
            raise ScenarioError(f"Duplicate instruction file: {name}")
        seen.add(path)
        try:
            if path.stat().st_size > 100_000:
                raise ScenarioError(f"Instruction file exceeds 100 KB: {name}")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ScenarioError(f"Cannot read instruction file: {name}") from error
        sources.append(
            InstructionSource(
                source=name, text=text, sha256=hashlib.sha256(text.encode()).hexdigest()
            )
        )
    content = {
        "sources": [s.model_dump() for s in sources],
        "policies": scenario.policies,
    }
    if sum(len(s.text.encode()) for s in sources) > 200_000:
        raise ScenarioError("Combined instructions exceed 200 KB")
    return InstructionBundle(
        variant=scenario.instructions.variant,
        sources=sources,
        policies=scenario.policies,
        sha256=digest(content),
    )


def render_prompt(scenario: Scenario, bundle: InstructionBundle) -> str:
    # Exact prompt is preserved as evidence. No instructions about judging the actor.
    instructions = "\n\n".join(s.text for s in bundle.sources)
    policies = "\n".join(bundle.policies)
    return (
        f"Scenario instructions:\n{instructions}\n\n"
        f"Explicit policies:\n{policies}\n\nUser request:\n{scenario.prompt}"
    )

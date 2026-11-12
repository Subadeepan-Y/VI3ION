from __future__ import annotations

from ...config import Settings
from .clip_tags import ClipSceneTagger
from .florence import FlorenceProvider
from .interface import SemanticCaption, SemanticObject, SemanticProvider, SceneTag
from .mock import MockSemanticProvider
from .owlvit import OpenVocabDetector
from .remote import RemoteSemanticProvider

PROVIDER_NAMES = ("mock", "remote", "florence", "owlvit", "clip")


def create_providers(settings: Settings) -> list[SemanticProvider]:
    """Build the enabled providers from `settings.semantic_provider`.

    Values: none | mock | remote | florence | owlvit | clip, comma-separated
    for several (e.g. "florence,owlvit,clip").
    """
    requested = [
        part.strip().lower()
        for part in settings.semantic_provider.split(",")
        if part.strip()
    ]
    if not requested or requested == ["none"]:
        return []
    providers: list[SemanticProvider] = []
    for name in requested:
        if name == "mock":
            providers.append(MockSemanticProvider(settings.semantic_mock_path))
        elif name == "remote":
            providers.append(RemoteSemanticProvider(settings))
        elif name == "florence":
            providers.append(FlorenceProvider(settings.semantic_florence_model))
        elif name == "owlvit":
            providers.append(
                OpenVocabDetector(
                    settings.semantic_vocab_path,
                    settings.semantic_min_confidence,
                    settings.semantic_owlvit_model,
                )
            )
        elif name == "clip":
            providers.append(ClipSceneTagger(settings.semantic_clip_model))
    return providers


# Back-compat alias for any caller expecting a single provider.
def create_provider(settings: Settings) -> SemanticProvider | None:
    providers = create_providers(settings)
    return providers[0] if providers else None


__all__ = [
    "SemanticObject",
    "SemanticCaption",
    "SemanticProvider",
    "SceneTag",
    "MockSemanticProvider",
    "RemoteSemanticProvider",
    "FlorenceProvider",
    "OpenVocabDetector",
    "ClipSceneTagger",
    "PROVIDER_NAMES",
    "create_provider",
    "create_providers",
]

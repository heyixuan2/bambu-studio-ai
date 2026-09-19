"""The provider registry.

To add a provider (fal.ai is next): write ``providers/<name>.py`` implementing
:class:`~bambu_studio_ai.generation.providers.base.Provider` and add one entry to
``_FACTORIES``. ``configure.py`` and ``generate.py`` read the names from here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from bambu_studio_ai.generation.errors import InputError
from bambu_studio_ai.generation.http import HttpClient
from bambu_studio_ai.generation.providers.base import Provider
from bambu_studio_ai.generation.providers.meshy import MeshyProvider
from bambu_studio_ai.generation.providers.rodin import RodinProvider
from bambu_studio_ai.generation.providers.tripo import TripoProvider


@dataclass(frozen=True)
class ProviderSettings:
    """What a provider is constructed with."""

    api_key: str
    http: HttpClient = field(default_factory=HttpClient)
    options: Mapping[str, str] = field(default_factory=dict[str, str])
    """Provider-specific settings from the user's config (e.g. ``rodin_tier``)."""


_FACTORIES: dict[str, Callable[[ProviderSettings], Provider]] = {
    "meshy": lambda s: MeshyProvider(s.api_key, s.http),
    "tripo": lambda s: TripoProvider(s.api_key, s.http),
    "rodin": lambda s: RodinProvider(s.api_key, s.http, default_tier=s.options.get("rodin_tier")),
}

#: Supported provider names, default first.
PROVIDER_NAMES: tuple[str, ...] = tuple(_FACTORIES)


def create_provider(name: str, settings: ProviderSettings) -> Provider:
    """Construct the named provider.

    Raises:
        InputError: unknown provider name.
    """
    factory = _FACTORIES.get(name)
    if factory is None:
        raise InputError(f"unknown provider {name!r}; choose one of: {', '.join(PROVIDER_NAMES)}")
    return factory(settings)


__all__ = ["PROVIDER_NAMES", "Provider", "ProviderSettings", "create_provider"]

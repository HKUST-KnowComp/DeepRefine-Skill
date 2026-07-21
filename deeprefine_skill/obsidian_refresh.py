"""Deprecated: use ``deeprefine_skill.wiki_update`` instead.

This module is kept for backward compatibility.  All functionality has moved
to :mod:`deeprefine_skill.wiki_update`.  Existing import paths continue to
work — ``ObsidianRefreshError`` / ``ObsidianRefreshResult`` /
``apply_refinement_with_obsidian_refresh`` are aliases for the corresponding
``WikiUpdate*`` names.
"""
from deeprefine_skill.wiki_update import (  # noqa: F401
    WikiUpdateError as ObsidianRefreshError,
    WikiUpdateResult as ObsidianRefreshResult,
    apply_refinement_with_wiki_update as apply_refinement_with_obsidian_refresh,
)

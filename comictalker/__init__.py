from __future__ import annotations

import itertools
import logging
import pathlib
import sys
from collections.abc import Sequence

from packaging.version import InvalidVersion, parse

if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points

from comictalker.comictalker import ComicTalker, TalkerError

logger = logging.getLogger(__name__)

__all__ = [
    "ComicTalker",
    "TalkerError",
]


def get_talkers(
    version: str, cache: pathlib.Path, local_plugins: Sequence[type[ComicTalker]] = tuple()
) -> dict[str, ComicTalker]:
    """Returns all comic talker instances"""
    talkers: dict[str, ComicTalker] = {}
    ct_version = parse(version)

    # A dict is used, last plugin wins
    for talker in itertools.chain(entry_points(group="comictagger.talker")):
        try:
            talker_cls = talker.load()
            obj = talker_cls(version, cache)
            if obj.id != talker.name:
                logger.error("Talker ID must be the same as the entry point name")
                continue
            try:
                if ct_version >= parse(obj.comictagger_min_ver):
                    talkers[talker.name] = obj
                else:
                    logger.error(
                        "Minimum ComicTagger version required of %s for talker %s is not met, will NOT load talker",
                        obj.comictagger_min_ver,
                        talker.name,
                    )
            except InvalidVersion:
                logger.warning(
                    "Invalid minimum required ComicTagger version number for talker: %s - version: %s, will load talker anyway",
                    talker.name,
                    obj.comictagger_min_ver,
                )
                # Attempt to use the talker anyway
                # TODO flag this problem for later display to the user
                talkers[talker.name] = obj

        except Exception:
            logger.exception("Failed to load talker: %s", talker.name)
            logger.debug("", exc_info=True)

    # A dict is used, last plugin wins
    for talker_cls in local_plugins:
        try:
            obj = talker_cls(version, cache)
            try:
                if ct_version >= parse(talker_cls.comictagger_min_ver):
                    talkers[talker_cls.id] = obj
                else:
                    logger.error(
                        "Minimum ComicTagger version required of %s for talker %s is not met, will NOT load talker",
                        talker_cls.comictagger_min_ver,
                        talker_cls.id,
                    )
            except InvalidVersion:
                logger.warning(
                    "Invalid minimum required ComicTagger version number for talker: %s - version: %s, will load talker anyway",
                    talker_cls.id,
                    talker_cls.comictagger_min_ver,
                )
                # Attempt to use the talker anyway
                # TODO flag this problem for later display to the user
                talkers[talker_cls.id] = obj

        except Exception:
            logger.exception("Failed to load talker: %s", talker_cls.id)
            logger.debug("", exc_info=True)

    return talkers

from __future__ import annotations

import argparse
import copy
import itertools
import logging
from collections.abc import Collection, Iterable
from enum import auto
from io import BytesIO
from typing import Callable, NamedTuple, TypedDict
from urllib.parse import urljoin

import requests
import settngs

from comicapi import comicarchive, utils
from comicapi.genericmetadata import GenericMetadata
from comicapi.issuestring import IssueString
from comictaggerlib.ctsettings.settngs_namespace import SettngsNS
from comictaggerlib.imagehasher import ImageHasher
from comictalker import ComicTalker

logger = logging.getLogger(__name__)

__version__ = "0.1"


class HashType(utils.StrEnum):
    # Unknown = 'Unknown'
    AHASH = auto()
    DHASH = auto()
    PHASH = auto()


class Hash(TypedDict):
    Hash: int
    Kind: HashType


class ID_dict(TypedDict):
    Domain: str
    ID: str


class ID(NamedTuple):
    Domain: str
    ID: str


class Result(TypedDict):
    # Mapping of domains (eg comicvine.gamespot.com) to IDs
    Hash: Hash
    ID: ID_dict
    Distance: int
    EquivalentIDs: list[ID_dict]


class ResultList(NamedTuple):
    distance: int
    results: list[Result]


def settings(manager: settngs.Manager) -> None:
    manager.add_setting(
        "--url",
        "-u",
        default="https://comic-hasher.narnian.us",
        type=utils.parse_url,
        help="Website to use for searching cover hashes",
    )
    manager.add_setting(
        "--max",
        default=8,
        type=int,
        help="Maximum score to allow. Lower score means more accurate",
    )
    manager.add_setting(
        "--aggressive-filtering",
        default=False,
        action=argparse.BooleanOptionalAction,
        help="Will filter out worse matches if better matches are found",
    )
    manager.add_setting(
        "--hash",
        default=list(HashType),
        type=HashType,
        nargs="+",
        help="Pick what hashes you want to use to search (default: %(default)s)",
    )
    manager.add_setting(
        "--exact-only",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Skip non-exact matches if we have exact matches",
    )


class QuickTag:
    def __init__(
        self, url: utils.Url, domain: str, talker: ComicTalker, config: SettngsNS, output: Callable[[str], None]
    ):
        self.output = output
        self.url = url
        self.talker = talker
        self.domain = domain
        self.config = config

    def id_comic(
        self,
        ca: comicarchive.ComicArchive,
        tags: GenericMetadata,
        hashes: set[HashType],
        exact_only: bool,
        interactive: bool,
        aggressive_filtering: bool,
        max_hamming_distance: int,
    ) -> GenericMetadata | None:
        if not ca.seems_to_be_a_comic_archive():
            raise Exception(f"{ca.path} is not an archive")
        from PIL import Image

        cover_index = tags.get_cover_page_index_list()[0]
        cover_image = Image.open(BytesIO(ca.get_page(cover_index)))

        self.output(f"Tagging: {ca.path}")

        self.output("hashing cover")
        phash = dhash = ahash = ""
        hasher = ImageHasher(image=cover_image)
        if HashType.AHASH in hashes:
            ahash = hex(hasher.average_hash())[2:]
        if HashType.DHASH in hashes:
            dhash = hex(hasher.difference_hash())[2:]
        if HashType.PHASH in hashes:
            phash = hex(hasher.perception_hash())[2:]

        logger.info(f"Searching with {ahash=}, {dhash=}, {phash=}")

        self.output("Searching hashes")
        results = self.SearchHashes(max_hamming_distance, ahash, dhash, phash, exact_only)
        logger.debug(f"{results=}")
        if not results:
            self.output("No results found for QuickTag")
            return None

        filtered_results = self.match_results(results, interactive, aggressive_filtering)
        by_id = {
            ID(**key): list(value)
            for key, value in itertools.groupby(
                sorted(filtered_results, key=lambda r: tuple(r["ID"].values())), key=lambda r: r["ID"]
            )
        }
        chosen_result = self.display_results(by_id, tags, interactive)
        if chosen_result:
            return self.talker.fetch_comic_data(issue_id=chosen_result.ID)
        return None

    def SearchHashes(
        self, max_hamming_distance: int, ahash: str, dhash: str, phash: str, exact_only: bool
    ) -> list[Result]:

        resp = requests.get(
            urljoin(self.url.url, "/match_cover_hash"),
            params={
                "max": str(max_hamming_distance),
                "ahash": ahash,
                "dhash": dhash,
                "phash": phash,
                "exactOnly": str(exact_only),
            },
        )
        if resp.status_code != 200:
            try:
                text = resp.json()["msg"]
            except Exception:
                text = resp.text
            if text == "No hashes found":
                return []
            logger.error("message from server: %s", text)
            raise Exception(f"Failed to retrieve results from the server: {text}")
        return resp.json()["results"]

    def get_mds(self, ids: Collection[ID]) -> list[GenericMetadata]:
        md_results: list[GenericMetadata] = []

        all_ids = {md_id.ID for md_id in ids if md_id.Domain == self.domain}

        self.output(f"Retrieving basic {self.talker.name} data")
        # Try to do a bulk fetch of basic issue data, if we have more than 1 id
        if hasattr(self.talker, "fetch_comics") and len(all_ids) > 1:
            md_results = self.talker.fetch_comics(issue_ids=list(all_ids))
        else:
            for md_id in all_ids:
                md_results.append(self.talker.fetch_comic_data(issue_id=md_id))
        return md_results

    def _filter_hash_results(self, results: Iterable[ResultList]) -> list[ResultList]:
        results = list(results)
        groups: list[ResultList] = []
        previous = None
        for group in results:

            if previous and (group.distance - previous.distance) > 3:
                break
            groups.append(group)
            previous = group
        return groups

    def match_results(self, results: list[Result], interactive: bool, aggressive_filtering: bool) -> list[Result]:
        results = sorted(copy.deepcopy(results), key=lambda r: (r["Hash"]["Kind"], r["Distance"]))
        ahash_results = sorted([r for r in results if r["Hash"]["Kind"] == "ahash"], key=lambda r: r["Distance"])
        dhash_results = sorted([r for r in results if r["Hash"]["Kind"] == "dhash"], key=lambda r: r["Distance"])
        phash_results = sorted([r for r in results if r["Hash"]["Kind"] == "phash"], key=lambda r: r["Distance"])
        all_hash_results = [
            [
                ResultList(distance, list(group))
                for distance, group in itertools.groupby(phash_results, key=lambda r: r["Distance"])
            ],
            [
                ResultList(distance, list(group))
                for distance, group in itertools.groupby(dhash_results, key=lambda r: r["Distance"])
            ],
            [
                ResultList(distance, list(group))
                for distance, group in itertools.groupby(ahash_results, key=lambda r: r["Distance"])
            ],
        ]

        # If any of the hash types have a single exact match return it. Prefer phash for no particular reason
        for hashed_results in all_hash_results:
            if len(hashed_results) == 1 and hashed_results[0].distance == 0:
                logger.info("Exact %s result found. Ignoring any others", hashed_results[0][1][0]["Hash"]["Kind"])
                return hashed_results[0][1]

        # Filter out results if there is a gap > 3 in distance
        for i, hashed_results in enumerate(all_hash_results):
            all_hash_results[i] = self._filter_hash_results(hashed_results)

        filtered = list(
            itertools.chain.from_iterable([r.results for r in itertools.chain.from_iterable(all_hash_results)])
        )
        by_id = {
            ID(**key): list(value)
            for key, value in itertools.groupby(
                sorted(filtered, key=lambda r: tuple(r["ID"].values()) + (r["Distance"],)), key=lambda r: r["ID"]
            )
        }

        sorted_list = sorted((l[0] for l in by_id.values()), key=lambda l: l["Distance"])

        filtered_top_hash_results = self._filter_hash_results(
            [
                ResultList(distance, list(group))
                for distance, group in itertools.groupby(sorted_list, key=lambda r: r["Distance"])
            ]
        )
        return list(itertools.chain.from_iterable([x.results for x in filtered_top_hash_results]))

    def display_results(
        self,
        results: dict[ID, list[Result]],
        tags: GenericMetadata,
        interactive: bool,
    ) -> ID | None:
        if len(results) < 1:
            return None
        # we only return early if we don't have a series name as get_mds will pull the full info if there is only one result
        if not tags.series and len(results) == 1 and list(results.values())[0][0]["Distance"] < 6:
            self.output("Found a single match < 6. Assuming it's correct")
            return list(results.keys())[0]

        mds = {md.issue_id: md for md in self.get_mds(results.keys())}
        name_issue_match: list[tuple[Result, GenericMetadata]] = []
        for md in mds.values():
            assert md.issue_id
            result_list = results[ID(self.domain, md.issue_id)]
            if (
                result_list[0]["Distance"] < 10
                and tags.series
                and md.series
                and utils.titles_match(tags.series, md.series, threshold=70)
                and IssueString(tags.issue).as_string() == IssueString(md.issue).as_string()
            ):
                name_issue_match.append((result_list[0], md))

        if len(name_issue_match) == 1:
            result, md = name_issue_match[0]
            self.output(
                f"Found {result['Hash']['Kind']} with distance {result['Distance']} match with series name {md.series!r}"
            )
            return ID(**result["ID"])
        if not interactive:
            return None
        items = sorted(results.items(), key=lambda r: r[1][0]["Distance"])
        for counter, r in enumerate(items, 1):
            r_id, result_list = r
            first_result = result_list[0]
            md = mds[r_id.ID]
            self.output(
                "    {:2}. {} distance: {} [{:15}] ({:02}/{:04}) - {} #{} - {}".format(
                    counter,
                    first_result["Hash"]["Kind"],
                    first_result["Distance"],
                    md.publisher or "",
                    md.month or 0,
                    md.year or 0,
                    md.series or "",
                    md.issue or "",
                    md.title or "",
                ),
            )
        while True:
            i = input(
                f'Please select a result to tag the comic with or "q" to quit: [1-{len(results)}] ',
            ).casefold()
            if i.isdigit() and int(i) in range(1, len(results) + 1):
                break
            if i == "q":
                self.output("User quit without saving metadata")
                return None

        return items[int(i) - 1][0]

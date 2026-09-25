"""What Cairn does, as a set of things the user switches on.

A feature that is off is not merely hidden. Its screen is gone, its endpoints
refuse, and the permissions only it needed are never asked for. This is the
difference that matters to the accountant who keeps her clients' financial
records on the machine: she does not want "Ask an AI" greyed out, she wants
it absent, and she wants to be able to check that it is.

The presets exist because a nine-question setup is a product nobody finishes.
Each one is a real person's answer to "what is this for", and every preset is
still fully editable afterwards - a preset chooses defaults, it does not
decide anything permanently.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairn.permissions import NEVER_PRESELECTED, Permission


@dataclass(frozen=True)
class Feature:
    key: str
    title: str
    pitch: str
    requires: tuple[Permission, ...] = ()
    # Useful without these, better with them.
    improves_with: tuple[Permission, ...] = ()
    # The two that work on an empty machine are on unless turned off; the ones
    # that read your disk or use the network are not.
    default_on: bool = False


FEATURES: tuple[Feature, ...] = (
    Feature(
        "search",
        "Search inside my files",
        "Find a document by something written inside it, not by remembering its name.",
        requires=(Permission.READ_FOLDERS,),
        improves_with=(
            Permission.OPEN_FILES,
            Permission.WATCH_CHANGES,
            Permission.DRIVE_READ,
        ),
        default_on=True,
    ),
    Feature(
        "commitments",
        "Catch what I promised",
        "Pull the promises out of your notes and documents - “I'll send the "
        "figures Thursday” - with the date worked out.",
        improves_with=(Permission.READ_FOLDERS,),
        default_on=True,
    ),
    Feature(
        "brief",
        "A daily brief",
        "One screen each morning: what is late, what is due, what you are waiting on.",
        default_on=True,
    ),
    Feature(
        "notes",
        "Quick notes",
        "Type something and forget it. Searchable at once, and scanned for promises.",
        default_on=True,
    ),
    Feature(
        "email",
        "Include my email",
        "Search your mail beside your files, and catch the promises you made by "
        "email. Reading only - writing and sending are separate decisions.",
        requires=(Permission.GMAIL_READ,),
        improves_with=(Permission.GMAIL_DRAFT,),
        default_on=False,
    ),
    Feature(
        "calendar",
        "Know what my day looks like",
        "Put today's meetings on the brief, so what you have promised is read "
        "against the time you actually have.",
        requires=(Permission.CALENDAR_READ,),
        improves_with=(Permission.CALENDAR_WRITE,),
        default_on=False,
    ),
    Feature(
        "ask",
        "Ask questions about my documents",
        "A question answered from your own files, citing them. Needs an AI key, and "
        "sends the matched paragraphs to that provider.",
        requires=(Permission.SEND_TO_AI, Permission.READ_FOLDERS),
        default_on=False,
    ),
)

BY_KEY = {feature.key: feature for feature in FEATURES}


@dataclass(frozen=True)
class Preset:
    key: str
    title: str
    who: str
    features: tuple[str, ...]
    # Permissions this preset proposes. The user still confirms each one; a
    # preset pre-ticks boxes, it does not grant anything.
    proposes: tuple[Permission, ...]


PRESETS: tuple[Preset, ...] = (
    Preset(
        "private",
        "Keep everything on this machine",
        "You handle other people's confidential material - clients, patients, "
        "finances - and nothing may leave the computer.",
        ("search", "commitments", "brief", "notes"),
        (Permission.READ_FOLDERS, Permission.OPEN_FILES),
    ),
    Preset(
        "work",
        "Keep on top of my work",
        "You live in documents and email, and the thing you lose is what you "
        "promised someone last Tuesday.",
        ("search", "commitments", "brief", "notes", "email", "calendar"),
        (
            Permission.READ_FOLDERS,
            Permission.OPEN_FILES,
            Permission.WATCH_CHANGES,
            Permission.GMAIL_READ,
            Permission.GMAIL_DRAFT,
            Permission.CALENDAR_READ,
        ),
    ),
    Preset(
        "find",
        "Just help me find things",
        "You know the file exists. You cannot find it. That is the whole problem.",
        ("search",),
        (Permission.READ_FOLDERS, Permission.OPEN_FILES, Permission.WATCH_CHANGES),
    ),
    Preset(
        "everything",
        "All of it, including AI answers",
        "You have an API key, or you run a model locally, and you want questions "
        "answered from your files and your mail.",
        ("search", "commitments", "brief", "notes", "email", "calendar", "ask"),
        (
            Permission.READ_FOLDERS,
            Permission.OPEN_FILES,
            Permission.WATCH_CHANGES,
            Permission.SEND_TO_AI,
            Permission.GMAIL_READ,
            Permission.GMAIL_DRAFT,
            Permission.CALENDAR_READ,
            Permission.DRIVE_READ,
        ),
    ),
)

# Even "all of it" does not propose sending mail as you. See NEVER_PRESELECTED.
assert all(
    not (set(preset.proposes) & NEVER_PRESELECTED) for preset in PRESETS
), "a preset must never pre-tick a permission that reaches another person"

BY_PRESET = {preset.key: preset for preset in PRESETS}


def default_enabled() -> list[str]:
    return [feature.key for feature in FEATURES if feature.default_on]


def describe(enabled: list[str], permissions) -> list[dict]:
    """Every feature, with whether it is on and whether it can actually run.

    A feature can be switched on and still be unusable because the permission
    it needs was refused. Saying so plainly - "on, but it cannot read anything"
    - beats a screen that looks fine and does nothing.
    """
    out = []
    for feature in FEATURES:
        missing = [p.value for p in feature.requires if not permissions.allowed(p)]
        out.append(
            {
                "key": feature.key,
                "title": feature.title,
                "pitch": feature.pitch,
                "requires": [p.value for p in feature.requires],
                "improves_with": [p.value for p in feature.improves_with],
                "enabled": feature.key in enabled,
                "blocked_by": missing,
                "usable": feature.key in enabled and not missing,
            }
        )
    return out


def presets() -> list[dict]:
    return [
        {
            "key": preset.key,
            "title": preset.title,
            "who": preset.who,
            "features": list(preset.features),
            "proposes": [p.value for p in preset.proposes],
        }
        for preset in PRESETS
    ]

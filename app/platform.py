"""Die Plattform "Mönninghausen Games": welche Bereiche (Unter-Apps) es gibt.

Jeder Bereich hat eine eigene Startadresse, eigene Tabs in der unteren Leiste und optional einen
Admin-Bereich. Konten, Profile, Einladungen und Login teilen sich alle Bereiche.
Ein neuer Bereich wird hier eingetragen - Startseite, Navigation und Admin übernehmen ihn automatisch.
"""

from dataclasses import dataclass, field

PLATFORM_NAME = "Mönninghausen Games"


@dataclass(frozen=True)
class Section:
    key: str
    name: str
    icon: str
    href: str
    tagline: str
    tabs: tuple[tuple[str, str, str], ...] = field(default=())  # (href, icon, label)
    desktop_tabs: tuple[tuple[str, str, str], ...] = field(default=())  # zusätzlich nur in der Desktop-Leiste
    admin_href: str | None = None
    ready: bool = True  # False = auf der Startseite als "kommt bald" gezeigt

    def owns(self, path: str) -> bool:
        return path == self.href or path.startswith(self.href + "/")


SECTIONS: tuple[Section, ...] = (
    Section(
        key="fantasy", name="Fantasy Darts", icon="🏆", href="/fantasy",
        tagline="Build a team for the World Championship and climb the ranking.",
        tabs=(("/fantasy", "🏆", "Ranking"), ("/fantasy/my", "🧩", "My Teams"), ("/fantasy/bracket", "🌳", "Bracket"),
              ("/fantasy/schedule", "📅", "Schedule"), ("/fantasy/players", "🎯", "Players"), ("/fantasy/rules", "📜", "Rules")),
        desktop_tabs=(("/fantasy/insights", "📊", "Insights"),),
        admin_href="/fantasy/admin",
    ),
    Section(
        key="darts", name="Darts", icon="🎯", href="/darts",
        tagline="Play 501 against each other, score on your phone and track your stats.",
        tabs=(("/darts", "🎯", "Play"), ("/darts/new", "➕", "New game"), ("/darts/games", "🕒", "Games"),
              ("/darts/players", "📈", "Stats")),
    ),
    Section(key="beerpong", name="Beer Pong", icon="🍺", href="/beerpong",
            tagline="Run beer pong tournaments with teams and a bracket.", ready=False),
)

# Untere Leiste auf der Startseite und den gemeinsamen Seiten (Account, Profile, Admin)
HOME_TABS: tuple[tuple[str, str, str], ...] = (("/", "🏠", "Home"), ("/account", "👤", "Account"))


def section_for_path(path: str) -> Section | None:
    return next((s for s in SECTIONS if s.ready and s.owns(path)), None)


def tab_active(href: str, path: str, section: Section | None) -> bool:
    """Startseite eines Bereichs nur exakt, andere Tabs auch für Unterseiten (z. B. /fantasy/my/new)."""
    if href == "/" or (section and href == section.href):
        return path == href
    return path == href or path.startswith(href + "/") or path.startswith(href + "?")

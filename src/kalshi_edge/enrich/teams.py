# Manual overrides where the results dataset name differs from API-Football's.
NAME_OVERRIDES: dict[str, str] = {}


def resolve_team_id(api, name: str) -> int | None:
    """Return the API-Football national-team id for a dataset team name, or None."""
    query = NAME_OVERRIDES.get(name, name)
    for row in api.get("/teams", {"search": query}):
        team = row.get("team", {})
        if team.get("national"):
            return team.get("id")
    return None

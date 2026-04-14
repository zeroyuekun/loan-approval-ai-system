"""Locust entry point. Imports the user classes; Locust picks them up."""
from tests.load.users import FullApplicationUser, QuickScoreUser

__all__ = ["QuickScoreUser", "FullApplicationUser"]

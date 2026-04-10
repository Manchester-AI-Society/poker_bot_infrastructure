from .betting_round_logic import GameBettingMixin
from .match_lifecycle_service_base import GameServiceBase
from .player_state_projection import GameStateMixin
from .street_progression_logic import GameStreetMixin
from .turn_management_logic import GameTurnMixin


class GameService(
    GameTurnMixin,
    GameStreetMixin,
    GameBettingMixin,
    GameStateMixin,
    GameServiceBase,
):
    """Composed game service from focused mixins."""

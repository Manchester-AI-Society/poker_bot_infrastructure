from .base_service import GameServiceBase
from .betting import GameBettingMixin
from .state_utils import GameStateMixin
from .streets import GameStreetMixin
from .turns import GameTurnMixin


class GameService(
    GameTurnMixin,
    GameStreetMixin,
    GameBettingMixin,
    GameStateMixin,
    GameServiceBase,
):
    """Composed game service from focused mixins."""

from .poker_card import PokerCard


class Player:
    def __init__(self, curr_balance, player_id):
        """Initialises a player with a GBP balance."""

        # Global game data
        self.player_id = player_id
        self.cards = []
        self.curr_balance = curr_balance
        self.is_all_in = False
        self.is_eliminated = False

        # Street specific data
        self.is_folded = False
        self.has_moved = False
        self.curr_bet_amount = 0

    def add_card(self, new_card: PokerCard):
        """Adds a card to the player hand"""
        assert len(self.cards) < 2
        self.cards.append(new_card)

    def can_play_turn(self, call_amount):
        """
        Checks if a non-folded, non-all-in player has a valid turn.
        Used as a termination condition for a street.

        Parameters
        ----------
        call_amount : int
            Global amount that should be played.

        Returns
        -------
        bool
            Whether this player has a valid turn or not.
        """

        # This code should not check folded or all-in players
        assert not self.is_folded
        assert not self.is_all_in

        # Each player must play at least once per street
        if not self.has_moved:
            return True

        # Player must play to match call_amount
        if call_amount > self.curr_bet_amount:
            return True

        return False

    def call_bet(self, call_amount):
        """Bets what is needed to stay in the game"""
        assert call_amount >= self.curr_bet_amount
        amount_to_bet = call_amount - self.curr_bet_amount
        self._make_bet(amount_to_bet)
        return amount_to_bet

    def fold(self):
        """The player folds"""
        self.is_folded = True
        return 0

    def check(self, call_amount):
        """Checks the turn; only valid with no extra chips due."""
        assert call_amount == self.curr_bet_amount
        return 0

    def all_in(self):
        """Bets everything the current player has."""
        amount_to_bet = self.curr_balance
        self._make_bet(amount_to_bet)
        return amount_to_bet

    def play_blind(self, blind_amount):
        """Plays the forced blind at the beginning of the street"""
        self._make_bet(blind_amount)

    def commit_chips(self, amount):
        """Commits an explicit chip amount to the current street."""
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self._make_bet(amount)
        return amount

    def reset_street(self):
        """Resets the street specific data."""
        self.has_moved = False
        self.curr_bet_amount = 0

    def reset_for_new_hand(self):
        """Resets hand state, preserving identity and balance."""
        self.cards = []
        self.is_folded = False
        self.has_moved = False
        self.curr_bet_amount = 0
        self.is_all_in = self.curr_balance == 0

    def _make_bet(self, bet):
        """Removes the bet from the player balance"""
        assert self.curr_balance >= bet

        # Makes the bet
        self.curr_balance -= bet
        self.curr_bet_amount += bet

        # Checks if player is all in
        if self.curr_balance == 0:
            self.is_all_in = True

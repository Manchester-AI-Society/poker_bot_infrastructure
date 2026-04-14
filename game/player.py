from .poker_card import pokerCard

class player:
    def __init__(self, curr_balance, player_id):
        """Initializes a player object with balance float current_balance in GBP"""
        
        # Global game data
        self.player_id = player_id
        self.cards = []
        self.curr_balance = curr_balance
        self.is_all_in = False

        # Street specific data
        self.is_folded = False
        self.has_moved = False
        self.curr_bet_amount = 0
    
    def add_card(self, new_card : pokerCard):
        """Adds a card to the player hand"""
        assert len(self.cards) < 2
        self.cards.append(new_card)

    def can_play_turn(self, call_amount):
        """
        Checks if a non-folded, non-all-in player has a valid turn. Used as a termination condition for a street.
        
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

    def play_turn(self, game_state_dict):
        """
        Player plays the current turn
        
        Parameters
        ----------
        game_state_dict: dict
            {
            "call_amount": int,
            ...
            }

        Returns
        -------
        player_move : tuple[int, str, int]
            Example:
                (self.player_id, action, amount_played)
        """

        call_amount = game_state_dict["call_amount"]
        player_move = self._run_model_inference(game_state_dict)

        action = player_move[0]
        raise_amount = player_move[1]

        match action:
            case "call":
                amount_played = self.call_bet(call_amount)

            case "raise":
                amount_played = self.raise_bet(raise_amount, call_amount)

            case "all_in":
                amount_played = self.all_in()

            case "check":
                amount_played = self.check(call_amount)

            case "fold":
                amount_played = self.fold()

            case _:
                raise ValueError(f"Unknown action: {action}")
        
        return (self.player_id, action, amount_played)
    
    def raise_bet(self, raise_amount, call_amount):
        """Bets call_amount and increases the bet by raise_amount"""
        assert raise_amount > 0

        self.call_bet(call_amount)
        self._make_bet(raise_amount)

        return call_amount + raise_amount
        
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
        """Checks the current turn. Only valid if no extra chips are required."""
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

    def reset_street(self):
        """Resets the street specific data."""
        self.has_moved = False
        self.curr_bet_amount = 0

    def _make_bet(self, bet):
        """Removes the bet from the player balance"""
        assert self.curr_balance >= bet

        # Makes the bet
        self.curr_balance -= bet
        self.curr_bet_amount += bet

        # Checks if player is all in
        if self.curr_balance == 0:
            self.is_all_in = True
    
    def _run_model_inference(self, game_state_dict):
        """
        Player plays the current turn
        
        Parameters
        ----------
        game_state_dict: dict
            {
            "current_round": str,
            "call_amount": int,
            "current_pot": int,
            "revealed_cards": list[pokerCard],
            "preflop_moves": list[tuple],
            "flop_moves": list[tuple],
            "turn_moves": list[tuple],
            "river_moves": list[tuple]
            }

        Returns
        -------
        player_move : tuple[str, int]
            Example:
                ("call", -1)
                ("fold", -1)
                ("check", -1)
                ("raise", raise_amount)
                ("all_in", -1)
        """
        call_amount = game_state_dict["call_amount"]
        if call_amount > self.curr_bet_amount:
            if self.curr_balance + self.curr_bet_amount <= call_amount:
                return ("all_in", -1)
            return ("call", -1)
        return ("check", -1)

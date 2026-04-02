class pokerCard:
    def __init__(self, card_number:int, card_suit:str):
        """
        Creates a new poker card object.
        
        Parameters
        ----------
        card_number: int 
            The card number (between 1-13). 
                card_number = 1: Ace
                card_number = 11: Jack
                card_number = 12: Queen
                card_number = 13: King
        
        card_suit: str
            One of ("spades", "clubs", "hearts", "diamonds")
        """

        assert 1 <= card_number <= 13
        assert card_suit in ["spades", "clubs", "hearts", "diamonds"]

        self.card_number = card_number
        self.card_suit = card_suit
    
    def get_card_colour(self):
        """Returns the colour of the current card as a string ["black", "red"]"""
        
        if self.card_suit in ["spades", "clubs"]:
            return "black"
        return "red"

    def get_card_string(self):
        return f"{self.card_suit}_{self.card_number}"
    
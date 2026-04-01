from player import player
from poker_card import pokerCard
from poker_deck import pokerDeck
from poker_board import pokerBoard

class pokerGame:
    def __init__(self, num_players):

        self.players = [player() for _ in range(num_players)]
        self.deck = pokerDeck()
        self.board = pokerBoard()

    def distribute_cards(self):

        for player in self.players:
            card1 = self.deck.draw_card()
            card2 = self.deck.draw_card()

            player

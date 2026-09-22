import importlib
import types

import pytest

import engine_wrapper
import test_ponder

lishogi_bot = importlib.import_module("lishogi-bot")


class RecordingAPI:
    """Stands in for lishogi.Lishogi: records the move and resign calls."""

    def __init__(self):
        self.moves = []
        self.resigned = []

    def make_move(self, game_id, move):
        self.moves.append((game_id, move))

    def resign(self, game_id):
        self.resigned.append(game_id)


def test_a_move_is_sent_as_a_move_and_pondering_may_follow():
    li = RecordingAPI()
    game = types.SimpleNamespace(id="game")
    assert lishogi_bot.submit_move(li, game, "2g2f") is True
    assert li.moves == [("game", "2g2f")]
    assert li.resigned == []


def test_bestmove_resign_calls_the_resign_endpoint_and_blocks_pondering():
    li = RecordingAPI()
    game = types.SimpleNamespace(id="game")
    assert lishogi_bot.submit_move(li, game, "resign") is False
    assert li.moves == []
    assert li.resigned == ["game"]


class ResigningUSI(test_ponder.RecordingUSI):
    """A ponder search that answers with a resignation once released."""

    def go(self, position, moves, ponder=False, **limits):
        super().go(position, moves, ponder=ponder, **limits)
        return "resign", None


def make_resigning_engine():
    engine = object.__new__(engine_wrapper.USIEngine)
    engine.go_commands = {}
    engine.engine = ResigningUSI()
    return engine


@pytest.mark.parametrize("variant_name", test_ponder.VARIANTS)
def test_a_resignation_from_a_missed_ponder_search_is_discarded(variant_name):
    played = test_ponder.PLAYED
    engine = make_resigning_engine()
    game = test_ponder.make_game(variant_name, played)
    board = test_ponder.make_board(variant_name, played)
    thread, ponder_usi = lishogi_bot.start_pondering(engine, board, "2g2f", "8c8d", 60000, 60000, game,
                                                     lishogi_bot.logger, 1000, 0, True)
    played = played + ["2g2f", "4c4d"]
    game.state = test_ponder.make_game(variant_name, played).state

    result = lishogi_bot.get_pondering_result(engine, game, test_ponder.make_board(variant_name, played), thread, ponder_usi)

    assert engine.engine.commands == ["stop"]
    assert result == (None, None)


@pytest.mark.parametrize("variant_name", test_ponder.VARIANTS)
def test_a_resignation_from_a_ponder_hit_is_adopted(variant_name):
    played = test_ponder.PLAYED
    engine = make_resigning_engine()
    game = test_ponder.make_game(variant_name, played)
    board = test_ponder.make_board(variant_name, played)
    thread, ponder_usi = lishogi_bot.start_pondering(engine, board, "2g2f", "8c8d", 60000, 60000, game,
                                                     lishogi_bot.logger, 1000, 0, True)
    played = played + ["2g2f", "8c8d"]
    game.state = test_ponder.make_game(variant_name, played).state

    result = lishogi_bot.get_pondering_result(engine, game, test_ponder.make_board(variant_name, played), thread, ponder_usi)

    assert engine.engine.commands == ["ponderhit"]
    assert result == ("resign", None)

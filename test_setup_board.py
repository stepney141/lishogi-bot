import importlib
import json
import logging
from queue import Queue
from unittest.mock import Mock

import pytest
import shogi

import engine_wrapper
import model

lishogi_bot = importlib.import_module("lishogi-bot")

# Lishogi writes the side to move into the SFEN as b (sente) or w (gote); a challenge from a position may set either.
CHUSHOGI_START = "lfcsgekgscfl/a1b1txot1b1a/mvrhdqndhrvm/pppppppppppp/3i4i3/12/12/3I4I3/PPPPPPPPPPPP/MVRHDNQDHRVM/A1B1TOXT1B1A/LFCSGKEGSCFL"
STANDARD_START = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL"
# Legal replies for each side to move, so the Standard board accepts them.
FIRST_MOVES = {"b": "7g7f", "w": "3c3d"}
SECOND_MOVES = {"b": "3c3d", "w": "7g7f"}


def game_full(variant_name, initial_sfen, moves, me_sente, clock=True):
    """The first message of a bot game stream (lishogi bot/BotJsonView)."""
    me, opponent = {"name": "bot"}, {"name": "opponent"}
    return {
        "type": "gameFull", "id": "game", "rated": False,
        "variant": {"key": variant_name.lower(), "name": variant_name}, "perf": {"name": variant_name},
        "clock": {"initial": 9000000, "increment": 0, "byoyomi": 0, "periods": 0} if clock else None,
        "sente": me if me_sente else opponent, "gote": opponent if me_sente else me,
        "initialSfen": initial_sfen,
        "state": {"type": "gameState", "moves": moves, "status": "started",
                  "btime": 9000000, "wtime": 9000000, "binc": 0, "winc": 0, "byo": 0},
    }


def engine_to_move(variant_name, start_side, played, me_sente):
    start = STANDARD_START if variant_name == "Standard" else CHUSHOGI_START
    moves = [FIRST_MOVES[start_side], SECOND_MOVES[start_side]][:played]
    full = game_full(variant_name, f"{start} {start_side} - 1", " ".join(moves), me_sente)
    game = model.Game(full, "bot", "https://lishogi.invalid/", 20)
    return lishogi_bot.is_engine_move(game, lishogi_bot.setup_board(game))


@pytest.mark.parametrize("variant_name", ["Standard", "Chushogi"])
@pytest.mark.parametrize("start_side", ["b", "w"])
@pytest.mark.parametrize("played", [0, 1, 2])
def test_the_side_to_move_follows_the_initial_sfen(variant_name, start_side, played):
    sente_to_move = (start_side == "b") == (played % 2 == 0)
    assert engine_to_move(variant_name, start_side, played, me_sente=True) is sente_to_move
    assert engine_to_move(variant_name, start_side, played, me_sente=False) is not sente_to_move


def test_gote_moves_first_in_a_chushogi_position_where_gote_starts(monkeypatch):
    """The stalled game yCbfKMbm: the challenger was sente, chose a position with gote to move, and the bot was gote."""
    initial_sfen = "lfcsgekgscfl/a1b1txxt1b1a/mvrhdqndhrvm/pppppppppppp/3i4i3/12/12/3I4I3/PPPPPPPPPPPP/MVRHDNQDHRVM/A1B1T+O+OT1B1A/LFCSGKEGSCFL w - 1"
    full = game_full("Chushogi", initial_sfen, "", me_sente=False)
    engine = Mock()
    engine.search_for.return_value = ("8a9b", None)
    monkeypatch.setattr(engine_wrapper, "create_engine", lambda _: engine)
    monkeypatch.setattr(lishogi_bot, "terminated", False)
    api = Mock(baseUrl="https://lishogi.invalid/")
    api.get_ongoing_games.return_value = []
    api.get_game_stream.return_value.iter_lines.return_value = iter([json.dumps(full).encode()])
    control = Queue()
    config = {"engine": {"ponder": False}, "abort_time": 20}

    lishogi_bot.play_game.__wrapped__(api, "game", control, {"username": "bot"}, config,
                                      [], Queue(), Queue(), lambda *_: None, logging.CRITICAL)

    searched_game = engine.search_for.call_args.args[1]
    assert (searched_game.initial_sfen, searched_game.state["moves"]) == (initial_sfen, "")
    api.make_move.assert_called_once_with("game", "8a9b")
    api.abort.assert_not_called()
    assert control.get_nowait() == {"type": "free_process", "gameId": "game"}

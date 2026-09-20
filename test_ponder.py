import importlib
import threading
import time
import types

import pytest
import shogi

import engine_wrapper
from engine_ctrl import usi

lishogi_bot = importlib.import_module("lishogi-bot")


class RecordingUSI:
    """Stands in for engine_ctrl.usi.Engine: a ponder search blocks until ponderhit or stop, as the USI protocol requires."""

    def __init__(self):
        self.searches = []
        self.commands = []
        self.released = threading.Event()
        self.info = {}

    def set_variant_options(self, variant):
        pass

    def go(self, position, moves, ponder=False, **limits):
        self.searches.append({"position": position, "moves": list(moves), "ponder": ponder})
        if ponder:
            assert self.released.wait(5)
        return "reply", None

    def ponderhit(self):
        self.commands.append("ponderhit")
        self.released.set()

    def stop(self):
        self.commands.append("stop")
        self.released.set()


def make_engine():
    engine = object.__new__(engine_wrapper.USIEngine)
    engine.go_commands = {}
    engine.engine = RecordingUSI()
    return engine


def make_game(variant_name, moves):
    state = {"moves": " ".join(moves), "fairyMoves": list(moves), "binc": 0, "winc": 0, "byo": 10000}
    return types.SimpleNamespace(id="game", variant_name=variant_name, initial_sfen="startpos", state=state)


def make_board(variant_name, moves):
    board = shogi.Board()
    for move in moves:
        board.push(shogi.Move.from_usi(move) if variant_name == "Standard" else shogi.Move.null())
    return board


def ponder(variant_name, played, best_move, ponder_move):
    engine = make_engine()
    game = make_game(variant_name, played)
    board = make_board(variant_name, played)
    thread, ponder_usi = lishogi_bot.start_pondering(engine, board, best_move, ponder_move, 60000, 60000, game,
                                                     lishogi_bot.logger, 1000, 0, True)
    return engine, game, thread, ponder_usi


VARIANTS = ["Standard", "Chushogi", "Checkshogi", "Kyoto shogi"]
PLAYED = ["7g7f", "3c3d"]


@pytest.mark.parametrize("variant_name", VARIANTS)
def test_ponder_search_runs_on_the_position_after_the_expected_reply(variant_name):
    engine, game, thread, _ = ponder(variant_name, PLAYED, "2g2f", "8c8d")
    # The main loop replaces game.state as soon as lishogi reports the bot's own move.
    game.state = make_game(variant_name, PLAYED + ["2g2f"]).state
    engine.stop()
    thread.join(5)

    assert engine.engine.searches == [{"position": "startpos", "moves": PLAYED + ["2g2f", "8c8d"], "ponder": True}]


@pytest.mark.parametrize("variant_name", VARIANTS)
def test_expected_reply_is_a_ponderhit(variant_name):
    engine, game, thread, ponder_usi = ponder(variant_name, PLAYED, "2g2f", "8c8d")
    played = PLAYED + ["2g2f", "8c8d"]
    game.state = make_game(variant_name, played).state

    result = lishogi_bot.get_pondering_result(engine, game, make_board(variant_name, played), thread, ponder_usi)

    assert engine.engine.commands == ["ponderhit"]
    assert result == ("reply", None)


@pytest.mark.parametrize("variant_name", VARIANTS)
def test_other_reply_stops_the_ponder_search_and_discards_its_move(variant_name):
    engine, game, thread, ponder_usi = ponder(variant_name, PLAYED, "2g2f", "8c8d")
    played = PLAYED + ["2g2f", "4c4d"]
    game.state = make_game(variant_name, played).state

    result = lishogi_bot.get_pondering_result(engine, game, make_board(variant_name, played), thread, ponder_usi)

    assert engine.engine.commands == ["stop"]
    assert result == (None, None)


class WireUSI(usi.Engine):
    """The real go command builder of engine_ctrl.usi.Engine, with the engine process replaced by a recorder."""

    def __init__(self):
        self.lines = []

    def set_variant_options(self, variant):
        pass

    def send(self, line):
        self.lines.append(line)

    def recv_usi(self):
        return "bestmove", "resign"


def ponder_go_line(btime, wtime, binc, winc, byo):
    engine = make_engine()
    engine.engine = WireUSI()
    game = make_game("Chushogi", PLAYED)
    game.state.update({"binc": binc, "winc": winc, "byo": byo})
    thread, _ = lishogi_bot.start_pondering(engine, make_board("Chushogi", PLAYED), "2g2f", "8c8d", btime, wtime, game,
                                            lishogi_bot.logger, 1000, time.perf_counter_ns(), True)
    thread.join(5)
    return [line for line in engine.engine.lines if line.startswith("go ")]


def test_ponder_started_in_byoyomi_sends_no_main_time_for_the_own_side():
    # lishogi reloads the clock to the byoyomi length on every move once the main time is gone,
    # so the reported 10000 ms is all byoyomi.
    assert ponder_go_line(10000, 60000, 0, 0, 10000) == ["go ponder btime 0 wtime 50000 byoyomi 10000"]


def test_ponder_with_main_time_follows_the_convention_of_a_normal_go():
    # The next normal go receives the clock after the server added the increment, and strips increment and byoyomi.
    assert ponder_go_line(60000, 60000, 0, 0, 10000) == ["go ponder btime 49000 wtime 50000 byoyomi 10000"]
    assert ponder_go_line(60000, 60000, 5000, 5000, 0) == ["go ponder btime 59000 wtime 55000 binc 5000 winc 5000"]

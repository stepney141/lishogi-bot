import time
from urllib.parse import urljoin

def estimate_total_time(base, incr, byo, pds): 
    def zero_if_null(x): 
        if x is None or x < 0: return 0 
        return x 

    return zero_if_null(base) + 60 * zero_if_null(incr) + 25 * zero_if_null(byo) * max(1, zero_if_null(pds))

def get_speed_from_tc(base, incr, byo, pds):
    t = estimate_total_time(base, incr, byo, pds) 

    if t < 60: return "ultraBullet"
    elif t < 300: return "bullet" 
    elif t < 600: return "blitz" 
    elif t < 1500: return "rapid" 
    else: return "classical"

class Challenge:
    def __init__(self, c_info):
        self.id = c_info["id"]
        self.rated = c_info["rated"]
        self.variant = c_info["variant"]["key"]
        self.perf_name = c_info["perf"]["name"]
        self.speed = c_info["timeControl"]["type"]
        self.increment = c_info.get("timeControl", {}).get("increment", -1)
        self.byoyomi = c_info.get("timeControl", {}).get("byoyomi", -1)
        self.periods = c_info.get("timeControl", {}).get("periods", -1)
        self.base = c_info.get("timeControl", {}).get("limit", -1)
        self.challenger = c_info.get("challenger")
        self.challenger_title = self.challenger.get("title") if self.challenger else None
        self.challenger_is_bot = self.challenger_title == "BOT"
        self.challenger_master_title = self.challenger_title if not self.challenger_is_bot else None
        self.challenger_name = self.challenger["name"] if self.challenger else "Anonymous"
        self.challenger_rating_int = self.challenger["rating"] if self.challenger else 0
        self.challenger_rating = self.challenger_rating_int or "?"

        if self.speed == "clock":
            self.speed = get_speed_from_tc(
                self.base, 
                self.increment, 
                self.byoyomi, 
                self.periods 
            )

    def is_supported_variant(self, supported):
        return self.variant in supported

    def is_supported_time_control(self, supported_speed, supported_increment_max, supported_increment_min, supported_byoyomi_max, supported_byoyomi_min, supported_byoyomi_min_nonzero, supported_base_max, supported_base_min):
        if self.increment < 0:
            return self.speed in supported_speed
        if self.byoyomi > 0 and self.byoyomi < supported_byoyomi_min_nonzero: 
            return False 
        return self.speed in supported_speed and supported_increment_max >= self.increment >= supported_increment_min and supported_byoyomi_max >= self.byoyomi >= supported_byoyomi_min and supported_base_max >= self.base >= supported_base_min

    def is_supported_mode(self, supported):
        return "rated" in supported if self.rated else "casual" in supported

    def check_allow_block_lists(self, config): 
        allow_list = config.get("bot_allow_list" if self.challenger_is_bot else "allow_list")
        block_list = config.get("bot_block_list" if self.challenger_is_bot else "block_list")
        username = self.challenger_name

        if block_list is not None and username in block_list: 
            return False 

        if allow_list is not None: 
            return username in allow_list 

        return True 

    def is_supported(self, config):
        if not config.get("accept_bot", True) and self.challenger_is_bot:
            return False
        if config.get("only_bot", False) and not self.challenger_is_bot:
            return False
        if not self.check_allow_block_lists(config): 
            return False 
        variants = config["variants"]
        tc = config["time_controls"]
        inc_max = config.get("max_increment", 180)
        inc_min = config.get("min_increment", 0)
        byoyomi_max = config.get("max_byoyomi", 180)
        byoyomi_min = config.get("min_byoyomi", 0)
        byoyomi_min_nonzero = config.get("min_nonzero_byoyomi", 0)
        base_max = config.get("max_base", 315360000)
        base_min = config.get("min_base", 0)
        modes = config["modes"]
        return self.is_supported_time_control(tc, inc_max, inc_min, byoyomi_max, byoyomi_min, byoyomi_min_nonzero, base_max, base_min) and self.is_supported_variant(variants) and self.is_supported_mode(modes)

    def score(self):
        rated_bonus = 200 if self.rated else 0
        titled_bonus = 200 if self.challenger_master_title else 0
        return self.challenger_rating_int + rated_bonus + titled_bonus

    def mode(self):
        return "rated" if self.rated else "casual"

    def challenger_full_name(self):
        return f'{self.challenger_title + " " if self.challenger_title else ""}{self.challenger_name}'

    def __str__(self):
        return f"{self.perf_name} {self.mode()} challenge from {self.challenger_full_name()}({self.challenger_rating})"

    def __repr__(self):
        return self.__str__()


class Game:
    def __init__(self, json, username, base_url, abort_time):
        self.username = username
        self.id = json.get("id")
        self.is_correspondence = json["clock"] is None
        clock = json.get("clock") or {}
        self.clock_initial = clock.get("initial", 1000 * 3600 * 24 * 365 * 10) # unlimited = 10 years
        self.clock_increment = clock.get("increment", 0)
        self.clock_byoyomi = clock.get("byoyomi", 0)
        self.clock_periods = clock.get("periods", 0) 
        self.perf_name = json.get("perf").get("name") if json.get("perf") else "{perf?}"
        self.variant_name = json.get("variant")["name"]
        self.sente = Player(json.get("sente"))
        self.gote = Player(json.get("gote"))
        if self.variant_name == "Kyoto shogi":
            self.initial_sfen = json.get("fairyInitialSfen")
        else:
            self.initial_sfen = json.get("initialSfen")
        self.state = json.get("state")
        self.is_sente = bool(self.sente.name and self.sente.name.lower() == username.lower())
        self.my_color = "sente" if self.is_sente else "gote"
        self.opponent_color = "gote" if self.is_sente else "sente"
        self.me = self.sente if self.is_sente else self.gote
        self.opponent = self.gote if self.is_sente else self.sente
        self.base_url = base_url
        self.sente_starts = self.initial_sfen == "startpos" or self.initial_sfen.split()[1] == "b"
        self.abort_at = time.time() + abort_time
        self.terminate_at = time.time() + (self.clock_initial + self.clock_increment + self.clock_byoyomi) / 1000 + abort_time + 60
        self.disconnect_at = time.time()

    def url(self):
        return urljoin(self.base_url, f"{self.id}/{self.my_color}")

    def is_abortable(self):
        return len(self.state["moves"]) < 6

    def ping(self, abort_in, terminate_in, disconnect_in):
        if self.is_abortable():
            self.abort_at = time.time() + abort_in
        self.terminate_at = time.time() + terminate_in
        self.disconnect_at = time.time() + disconnect_in

    def should_abort_now(self):
        return self.is_abortable() and time.time() > self.abort_at

    def should_terminate_now(self):
        return time.time() > self.terminate_at

    def should_disconnect_now(self):
        return time.time() > self.disconnect_at

    def my_remaining_seconds(self):
        return (self.state["btime"] if self.is_sente else self.state["wtime"]) / 1000

    def __str__(self):
        return f"{self.url()} {self.perf_name} vs {self.opponent.__str__()}"

    def __repr__(self):
        return self.__str__()


class Player:
    def __init__(self, json):
        self.id = json.get("id")
        self.name = json.get("name")
        self.title = json.get("title")
        self.rating = json.get("rating")
        self.provisional = json.get("provisional")
        self.aiLevel = json.get("aiLevel")

    def __str__(self):
        if self.aiLevel:
            return f"AI level {self.aiLevel}"
        else:
            rating = f'{self.rating}{"?" if self.provisional else ""}'
            return f'{self.title + " " if self.title else ""}{self.name}({rating})'

    def __repr__(self):
        return self.__str__()

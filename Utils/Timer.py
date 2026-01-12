from functools import partial
import time


class Timer:
    def __init__(self, dur=None, callback=None):
        """
        Initializes the Timer with default values.
        """
        self.desired_duration = dur if dur else -1
        self.started = False
        self.start_time = time.time()
        self.finished = False
        self.callback = callback
        self._has_already_executed_callback = False

    def set_callback(self, callback):
        """
        Sets the callback function for the Timer, to be executed when the timer finishes.

        Args:
            callback (function): The callback function to execute.
        """
        self.callback = callback

    def start(self, duration: float):
        """
        Starts the timer with the specified duration.

        Args:
            duration (float): The duration for the timer in seconds.
        """
        if not self.started:
            # print(f"Timer started with duration: {duration}")
            self.started = True
            self.desired_duration = duration
            self.finished = False
            self.start_time = time.time()

    def update(self):
        """
        Updates the timer status.

        Args:
            dt (float): The delta time since the last update.
        """
        if time.time() - self.start_time >= self.desired_duration:
            self.finished = True
            if not self._has_already_executed_callback:
                self.on_finish()
                self._has_already_executed_callback = True

    def stop(self):
        """
        Stops the timer.
        """
        self.finished = True
        self.started = False

    def on_finish(self):
        """
        Executes a callback function when the timer finishes.

        Args:
            callback (function): The callback function to execute.
        """
        if self.finished and self.callback is not None:
            self.callback()

    def __repr__(self) -> str:
        """
        Returns a string representation of the Timer object.

        Returns:
            str: The string representation of the Timer.
        """
        return f"[ desired_duration: {self.desired_duration} ]"


class SpacedCallback:
    def __init__(
        self, callback, interval: float, how_many_times: int = -1, *args, **kwargs
    ):
        """
        Initializes the SpacedCallback with the specified parameters.

        Args:
            callback (function): The callback function to execute.
            interval (float): The interval between each callback execution in seconds.
            how_many_times (int): The number of times to execute the callback.
        """
        # self.callback = partial(callback, args, kwargs)
        self.callback = callback
        self.interval = interval
        self.how_many_times = how_many_times
        self.last_time = time.time()
        self.executed_times = 0
        self.finished = True
        self.on_finish = None

    def start(self):
        """
        Starts the SpacedCallback.
        """
        self.last_time = time.time()
        self.finished = False

    def update(self):
        """
        Updates the SpacedCallback status and executes the callback if the interval has passed.

        Args:
            dt (float): The delta time since the last update.
        """
        if self.finished:
            return
        if time.time() - self.last_time >= self.interval:
            if self.how_many_times == -1 or self.executed_times < self.how_many_times:
                self.callback()
                self.last_time = time.time()
                self.executed_times += 1
        if self.how_many_times != -1 and self.executed_times >= self.how_many_times:
            self.stop()

    def stop(self):
        """
        Stops the SpacedCallback.
        """
        self.finished = True

    def __repr__(self) -> str:
        """
        Returns a string representation of the SpacedCallback object.

        Returns:
            str: The string representation of the SpacedCallback.
        """
        return f"[ interval: {self.interval}, how_many_times: {self.how_many_times} ]"


class TimerManager:
    def __init__(self):
        self.timers: list[Timer | SpacedCallback] = []

    def add_timer(self, timer: Timer | SpacedCallback):
        self.timers.append(timer)
        timer.start()

    def update(self):
        # for tween in self.tweens:
        #     tween.update()
        #     if tween.is_finished():
        #         if tween.on_finish:
        #             tween.on_finish.__call__()
        #         self.tweens.remove(tween)
        for timer in self.timers:
            timer.update()
            if timer.finished:
                if timer.on_finish:
                    timer.on_finish.__call__()
                self.timers.remove(timer)


if __name__ == "__main__":
    t = Timer()
    x = 0

    def callback():
        global x
        x += 1
        print(f"Callback executed {x} times.")

    sc = SpacedCallback(callback, 0.5)
    sc.start()
    t.start(5)
    tm = TimerManager()
    tm.add_timer(t)
    tm.add_timer(sc)
    while True:
        # tm.update()
        t.update()
        sc.update()
